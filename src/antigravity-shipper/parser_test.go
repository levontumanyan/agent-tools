package main

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestIncrementalTailing_MatchesFullParseAndHandlesPartialWrites(t *testing.T) {
	tmpDir := t.TempDir()
	convID := "11111111-2222-3333-4444-555555555555"
	logDir := filepath.Join(tmpDir, "brain", convID, ".system_generated", "logs")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		t.Fatal(err)
	}
	transcriptPath := filepath.Join(logDir, "transcript.jsonl")

	lines := []string{
		`{"step_index":0,"type":"USER_INPUT","status":"DONE","created_at":"2026-10-17T20:00:00Z","content":"<USER_REQUEST>\noptimize shipper performance\n</USER_REQUEST>\nActive Workspaces:\n- /workspace/project\n"}`,
		`{"step_index":1,"type":"PLANNER_RESPONSE","status":"DONE","created_at":"2026-10-17T20:00:02Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"go test ./...","Cwd":"/workspace/project","toolAction":"Running Go tests"}}]}`,
		`{"step_index":2,"type":"GENERIC","status":"DONE","created_at":"2026-10-17T20:00:05Z","content":"The command exited with code 0.\nOutput:\nok"}`,
		`{"step_index":3,"type":"PLANNER_RESPONSE","status":"DONE","created_at":"2026-10-17T20:00:06Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"git status","toolAction":"Checking git"}},{"name":"view_file","args":{"AbsolutePath":"/workspace/project/main.go","toolAction":"Reading main"}}]}`,
		`{"step_index":4,"type":"GENERIC","status":"DONE","created_at":"2026-10-17T20:00:07Z","content":"The command exited with code 1.\nOutput:\nerror"}`,
		`{"step_index":5,"type":"GENERIC","status":"DONE","created_at":"2026-10-17T20:00:08Z","content":"File contents..."}`,
		`{"step_index":6,"type":"PLANNER_RESPONSE","status":"DONE","created_at":"2026-10-17T20:00:09Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"ls -la","toolAction":"Listing"}},{"name":"run_command","args":{"CommandLine":"ls -la","toolAction":"Listing"}},{"name":"run_command","args":{"CommandLine":"ls -la","toolAction":"Listing"}}]}`,
	}

	st := NewTranscriptState(transcriptPath)

	// Write line 0 and line 1
	writeChunk(t, transcriptPath, lines[0]+"\n"+lines[1]+"\n")
	fi, err := os.Stat(transcriptPath)
	if err != nil {
		t.Fatal(err)
	}
	changed, err := st.UpdateIncremental(fi.ModTime(), fi.Size())
	if err != nil || !changed {
		t.Fatalf("expected changed=true, err=nil; got changed=%v, err=%v", changed, err)
	}
	// Simulate initial DB sync watermark at 1 tool call (still pending GENERIC completion)
	st.InitialSynced = true
	st.SyncedToolCalls = len(st.Meta.ToolCalls)
	st.SyncedLoopEvents = len(st.Meta.LoopEvents)
	st.SyncedPrompts = len(st.Meta.Prompts)

	// Write a partial mid-flush JSON line (no trailing newline, incomplete JSON)
	partial := lines[2][:40]
	writeChunk(t, transcriptPath, partial)
	offsetBeforePartial := st.Offset
	fi, _ = os.Stat(transcriptPath)
	changed, err = st.UpdateIncremental(fi.ModTime(), fi.Size())
	if err != nil {
		t.Fatalf("unexpected error on partial line: %v", err)
	}
	if changed {
		t.Fatalf("expected changed=false on incomplete trailing JSON line")
	}
	if st.Offset != offsetBeforePartial {
		t.Fatalf("expected Offset to stay at %d on partial line, got %d", offsetBeforePartial, st.Offset)
	}

	// Complete line 2 (GENERIC resolving tool call 0)
	writeChunk(t, transcriptPath, lines[2][40:]+"\n")
	fi, _ = os.Stat(transcriptPath)
	changed, err = st.UpdateIncremental(fi.ModTime(), fi.Size())
	if err != nil || !changed {
		t.Fatalf("expected changed=true after completing line 2, got changed=%v, err=%v", changed, err)
	}
	if !st.DirtyToolCallIdxs[0] {
		t.Fatalf("expected tool call 0 to be marked dirty after GENERIC completion")
	}
	if st.Meta.ToolCalls[0].DurationSeconds != 3.0 {
		t.Fatalf("expected duration 3.0s, got %v", st.Meta.ToolCalls[0].DurationSeconds)
	}

	// Append remaining lines one by one
	for i := 3; i < len(lines); i++ {
		writeChunk(t, transcriptPath, lines[i]+"\n")
		fi, _ = os.Stat(transcriptPath)
		changed, err = st.UpdateIncremental(fi.ModTime(), fi.Size())
		if err != nil || !changed {
			t.Fatalf("step %d: expected changed=true, err=nil; got %v, %v", i, changed, err)
		}
	}

	// Compare incremental state against a fresh full ParseTranscript
	fullMeta, err := ParseTranscript(transcriptPath)
	if err != nil {
		t.Fatalf("ParseTranscript failed: %v", err)
	}
	if !reflect.DeepEqual(st.Meta, fullMeta) {
		t.Fatalf("Incremental Meta mismatch with full ParseTranscript:\ngot:  %+v\nwant: %+v", st.Meta, fullMeta)
	}

	// Test truncation reset: overwrite file with just line 0
	if err := os.WriteFile(transcriptPath, []byte(lines[0]+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	fi, _ = os.Stat(transcriptPath)
	changed, err = st.UpdateIncremental(fi.ModTime(), fi.Size())
	if err != nil || !changed {
		t.Fatalf("expected changed=true after truncation, got %v, %v", changed, err)
	}
	if st.InitialSynced {
		t.Fatalf("expected InitialSynced=false after truncation reset")
	}
	if st.Meta.TotalSteps != 1 || len(st.Meta.ToolCalls) != 0 {
		t.Fatalf("unexpected state after truncation reset: steps=%d, tools=%d", st.Meta.TotalSteps, len(st.Meta.ToolCalls))
	}
}

func TestIncrementalTailing_OnRealTranscripts(t *testing.T) {
	ResetDiscoveryCache()
	recent, err := DiscoverRecentTranscripts(5)
	if err != nil || len(recent) == 0 {
		t.Skip("no local transcripts found to test")
	}

	for _, summary := range recent {
		raw, err := os.ReadFile(summary.Path)
		if err != nil || len(raw) == 0 {
			continue
		}

		// Parse full transcript in one shot
		wantMeta, err := ParseTranscript(summary.Path)
		if err != nil {
			t.Fatalf("ParseTranscript(%s) failed: %v", summary.ShortID, err)
		}

		// Feed the same transcript in 7 incremental byte chunks to a temp file
		tmpDir := t.TempDir()
		simPath := filepath.Join(tmpDir, "brain", summary.ID, ".system_generated", "logs", "transcript.jsonl")
		if err := os.MkdirAll(filepath.Dir(simPath), 0o755); err != nil {
			t.Fatal(err)
		}

		st := NewTranscriptState(simPath)
		chunkSize := len(raw)/7 + 1
		for pos := 0; pos < len(raw); pos += chunkSize {
			end := pos + chunkSize
			if end > len(raw) {
				end = len(raw)
			}
			writeChunk(t, simPath, string(raw[pos:end]))
			fi, err := os.Stat(simPath)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := st.UpdateIncremental(fi.ModTime(), fi.Size()); err != nil {
				t.Fatalf("[%s] UpdateIncremental failed at byte %d: %v", summary.ShortID, end, err)
			}
		}

		if !reflect.DeepEqual(st.Meta, wantMeta) {
			t.Fatalf("[%s] Incremental chunked parse did not match full ParseTranscript:\ngot steps=%d tools=%d prompts=%d loops=%d\nwant steps=%d tools=%d prompts=%d loops=%d",
				summary.ShortID,
				st.Meta.TotalSteps, st.Meta.TotalToolCalls, len(st.Meta.Prompts), len(st.Meta.LoopEvents),
				wantMeta.TotalSteps, wantMeta.TotalToolCalls, len(wantMeta.Prompts), len(wantMeta.LoopEvents))
		}
	}
}

func TestDiscoverRecentTranscripts_TwoTierCache(t *testing.T) {
	origHome := os.Getenv("HOME")
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)
	defer func() {
		os.Setenv("HOME", origHome)
		ResetDiscoveryCache()
	}()
	ResetDiscoveryCache()

	brainDir := filepath.Join(tmpHome, ".gemini", "antigravity-cli", "brain")
	if err := os.MkdirAll(brainDir, 0o755); err != nil {
		t.Fatal(err)
	}

	// Create 60 session folders with transcripts
	baseTime := time.Now().Add(-2 * time.Hour)
	for i := 0; i < 60; i++ {
		cid := filepath.Join(brainDir, "session-"+string(rune('a'+i/26))+string(rune('a'+i%26))+"-00000000")
		tPath := filepath.Join(cid, ".system_generated", "logs", "transcript.jsonl")
		if err := os.MkdirAll(filepath.Dir(tPath), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(tPath, []byte(`{"step_index":0,"type":"USER_INPUT"}`+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		mt := baseTime.Add(time.Duration(i) * time.Minute)
		_ = os.Chtimes(tPath, mt, mt)
	}

	// Pass 1: initial full discovery
	list1, err := DiscoverRecentTranscripts(5)
	if err != nil {
		t.Fatalf("DiscoverRecentTranscripts pass 1 failed: %v", err)
	}
	if len(list1) != 5 {
		t.Fatalf("expected 5 transcripts, got %d", len(list1))
	}

	// Create a brand new conversation directory WITHOUT transcript.jsonl yet (simulating t=0s folder creation)
	newConvID := "brandnew-9999-8888-7777-666666666666"
	newLogDir := filepath.Join(brainDir, newConvID, ".system_generated", "logs")
	if err := os.MkdirAll(newLogDir, 0o755); err != nil {
		t.Fatal(err)
	}
	futureTime := time.Now().Add(10 * time.Minute)
	_ = os.Chtimes(brainDir, futureTime, futureTime)

	// Pass 2 (fast tick): sees new directory even though transcript.jsonl is not written yet
	_, err = DiscoverRecentTranscripts(5)
	if err != nil {
		t.Fatal(err)
	}

	// Now write transcript.jsonl inside the already-created newConvID folder (brainDir mtime does NOT change!)
	newTranscript := filepath.Join(newLogDir, "transcript.jsonl")
	if err := os.WriteFile(newTranscript, []byte(`{"step_index":0,"type":"USER_INPUT"}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_ = os.Chtimes(newTranscript, futureTime.Add(time.Minute), futureTime.Add(time.Minute))

	// Pass 3 (fast tick): must immediately pick up newTranscript as #1 most recent!
	list3, err := DiscoverRecentTranscripts(5)
	if err != nil {
		t.Fatal(err)
	}
	if len(list3) == 0 || list3[0].ID != newConvID {
		t.Fatalf("expected new session %s to be #1 on fast tick, got %+v", newConvID, list3)
	}
}

func TestDeltaDBSync_EndToEnd(t *testing.T) {
	connStr := os.Getenv("ANTIGRAVITY_PG_URL")
	if connStr == "" {
		out, err := exec.Command("security", "find-generic-password", "-s", "antigravity-telemetry-pg-url", "-w").Output()
		if err == nil {
			connStr = strings.TrimSpace(string(out))
		}
	}
	if connStr == "" {
		t.Skip("ANTIGRAVITY_PG_URL not set; skipping live PostgreSQL delta sync test")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	db, err := ConnectDB(ctx, connStr)
	if err != nil {
		t.Skipf("skipping DB test (cannot connect): %v", err)
	}
	defer db.Close()

	tmpDir := t.TempDir()
	testSessionID := "00000000-test-delta-sync-000000000001"
	transcriptPath := filepath.Join(tmpDir, "brain", testSessionID, ".system_generated", "logs", "transcript.jsonl")
	if err := os.MkdirAll(filepath.Dir(transcriptPath), 0o755); err != nil {
		t.Fatal(err)
	}

	// Ensure cleanup of test session from PostgreSQL when done
	defer func() {
		_, _ = db.pool.Exec(context.Background(), `DELETE FROM sessions WHERE session_id = $1`, testSessionID)
	}()

	st := NewTranscriptState(transcriptPath)

	// Step 1: Write initial user prompt + first pending tool call (workspace initially unknown)
	step1 := `{"step_index":0,"type":"USER_INPUT","status":"DONE","created_at":"2026-10-17T20:00:00Z","content":"<USER_REQUEST>\ntest delta db sync\n</USER_REQUEST>"}` + "\n" +
		`{"step_index":1,"type":"PLANNER_RESPONSE","status":"DONE","created_at":"2026-10-17T20:00:01Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"echo hello","toolAction":"Echoing"}}]}` + "\n"
	writeChunk(t, transcriptPath, step1)
	fi, _ := os.Stat(transcriptPath)
	if _, err := st.UpdateIncremental(fi.ModTime(), fi.Size()); err != nil {
		t.Fatal(err)
	}
	if err := db.SyncSession(ctx, st); err != nil {
		t.Fatalf("initial SyncSession failed: %v", err)
	}
	if !st.InitialSynced || st.Meta.ToolCalls[0].DBID == 0 {
		t.Fatalf("expected InitialSynced=true and non-zero DBID, got InitialSynced=%v, DBID=%d", st.InitialSynced, st.Meta.ToolCalls[0].DBID)
	}
	firstToolDBID := st.Meta.ToolCalls[0].DBID

	// Step 2: Append GENERIC (failing tool call 0) + new tool call with Cwd (discovering workspace) + 3 identical commands (loop event) + second user prompt
	step2 := `{"step_index":2,"type":"GENERIC","status":"DONE","created_at":"2026-10-17T20:00:04Z","content":"The command exited with code 2."}` + "\n" +
		`{"step_index":3,"type":"USER_INPUT","status":"DONE","created_at":"2026-10-17T20:00:05Z","content":"<USER_REQUEST>\nsecond prompt\n</USER_REQUEST>"}` + "\n" +
		`{"step_index":4,"type":"PLANNER_RESPONSE","status":"DONE","created_at":"2026-10-17T20:00:06Z","tool_calls":[{"name":"run_command","args":{"CommandLine":"uptime","Cwd":"/workspace/test","toolAction":"Uptime"}},{"name":"run_command","args":{"CommandLine":"uptime","toolAction":"Uptime"}},{"name":"run_command","args":{"CommandLine":"uptime","toolAction":"Uptime"}}]}` + "\n"
	writeChunk(t, transcriptPath, step2)
	fi, _ = os.Stat(transcriptPath)
	if _, err := st.UpdateIncremental(fi.ModTime(), fi.Size()); err != nil {
		t.Fatal(err)
	}
	if err := db.SyncSession(ctx, st); err != nil {
		t.Fatalf("delta SyncSession failed: %v", err)
	}

	// Verify tool call 0 kept its exact same primary key id (no DELETE!) and was updated in-place
	var dbExitCode int
	var dbIsFailed bool
	var dbDuration float64
	var dbWorkspace string
	err = db.pool.QueryRow(ctx,
		`SELECT exit_code, is_failed, duration_seconds, workspace FROM tool_calls WHERE id = $1`,
		firstToolDBID,
	).Scan(&dbExitCode, &dbIsFailed, &dbDuration, &dbWorkspace)
	if err != nil {
		t.Fatalf("failed querying updated tool_call by original id %d: %v", firstToolDBID, err)
	}
	if dbExitCode != 2 || !dbIsFailed || dbDuration != 3.0 || dbWorkspace != "/workspace/test" {
		t.Fatalf("unexpected updated tool_call row: exit=%d failed=%v dur=%v ws=%q", dbExitCode, dbIsFailed, dbDuration, dbWorkspace)
	}

	// Verify row counts in tool_calls, loop_events, and user_prompts
	var toolCount, loopCount, promptCount int
	_ = db.pool.QueryRow(ctx, `SELECT COUNT(*) FROM tool_calls WHERE session_id = $1`, testSessionID).Scan(&toolCount)
	_ = db.pool.QueryRow(ctx, `SELECT COUNT(*) FROM loop_events WHERE session_id = $1`, testSessionID).Scan(&loopCount)
	_ = db.pool.QueryRow(ctx, `SELECT COUNT(*) FROM user_prompts WHERE session_id = $1`, testSessionID).Scan(&promptCount)

	if toolCount != 4 || loopCount != 1 || promptCount != 2 {
		t.Fatalf("unexpected row counts after delta sync: tools=%d (want 4), loops=%d (want 1), prompts=%d (want 2)",
			toolCount, loopCount, promptCount)
	}
}

func writeChunk(t *testing.T, path string, content string) {
	t.Helper()
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if _, err := f.WriteString(content); err != nil {
		t.Fatal(err)
	}
}

func BenchmarkDiscoverRecentTranscripts_FullScan(b *testing.B) {
	for i := 0; i < b.N; i++ {
		ResetDiscoveryCache()
		_, _ = DiscoverRecentTranscripts(20)
	}
}

func BenchmarkDiscoverRecentTranscripts_FastTick(b *testing.B) {
	ResetDiscoveryCache()
	_, _ = DiscoverRecentTranscripts(20)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if c, ok := discoveryCaches[filepath.Join(os.Getenv("HOME"), ".gemini", "antigravity-cli", "brain")]; ok {
			c.ticksSinceFullSweep = 0
		}
		_, _ = DiscoverRecentTranscripts(20)
	}
}

func BenchmarkTranscriptParse_FullVsIncremental(b *testing.B) {
	ResetDiscoveryCache()
	recent, err := DiscoverRecentTranscripts(20)
	if err != nil || len(recent) == 0 {
		b.Skip("no transcripts available")
	}
	// Pick largest recent transcript
	largest := recent[0]
	for _, r := range recent {
		if r.Size > largest.Size {
			largest = r
		}
	}
	raw, err := os.ReadFile(largest.Path)
	if err != nil {
		b.Fatal(err)
	}

	tmpDir := b.TempDir()
	simPath := filepath.Join(tmpDir, "brain", largest.ID, ".system_generated", "logs", "transcript.jsonl")
	_ = os.MkdirAll(filepath.Dir(simPath), 0o755)
	_ = os.WriteFile(simPath, raw, 0o644)
	fi, _ := os.Stat(simPath)

	// Warm up logConfirmationCache
	_ = LoadToolConfirmations(largest.ID)

	b.Run("FullParse", func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			_, _ = ParseTranscript(simPath)
		}
	})

	b.Run("IncrementalOneStep", func(b *testing.B) {
		st := NewTranscriptState(simPath)
		_, _ = st.UpdateIncremental(fi.ModTime(), fi.Size())
		savedOffset := st.Offset - 200
		if savedOffset < 0 {
			savedOffset = 0
		}
		b.ResetTimer()
		for i := 0; i < b.N; i++ {
			st.Offset = savedOffset
			_, _ = st.UpdateIncremental(fi.ModTime(), fi.Size())
		}
	})
}
