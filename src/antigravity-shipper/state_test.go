package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestState_LoadNonExistent(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "missing.json")

	state, err := LoadState(path)
	if err != nil {
		t.Fatalf("unexpected error loading non-existent state: %v", err)
	}
	if state == nil || state.Sessions == nil {
		t.Fatalf("expected non-nil state with initialized Sessions map")
	}
	if len(state.Sessions) != 0 {
		t.Fatalf("expected empty sessions, got %d", len(state.Sessions))
	}
}

func TestState_SaveAndLoadRoundTrip(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "sub", "state.json")

	state := NewPersistentState()
	now := time.Now().Truncate(time.Second).UTC()

	st := &TranscriptState{
		Path:                "/tmp/test/transcript.jsonl",
		ConvID:              "conv-1234-abcd",
		ShortID:             "conv-123",
		ModTime:             now,
		FileSize:            54321,
		Offset:              54321,
		InitialSynced:       true,
		LastSyncedWorkspace: "/workspace/project",
		SyncedToolCalls:     15,
		SyncedLoopEvents:    2,
		SyncedPrompts:       3,
	}

	state.UpdateFromSession(st)

	if err := state.SaveState(path); err != nil {
		t.Fatalf("SaveState failed: %v", err)
	}

	loaded, err := LoadState(path)
	if err != nil {
		t.Fatalf("LoadState failed: %v", err)
	}

	if loaded.Version != CurrentStateVersion {
		t.Errorf("expected version %d, got %d", CurrentStateVersion, loaded.Version)
	}
	wm, ok := loaded.Sessions[st.Path]
	if !ok {
		t.Fatalf("session %s not found in loaded state", st.Path)
	}

	if wm.ConvID != st.ConvID || wm.ShortID != st.ShortID || wm.FileSize != st.FileSize ||
		wm.Offset != st.Offset || !wm.InitialSynced || wm.LastSyncedWorkspace != st.LastSyncedWorkspace ||
		wm.SyncedToolCalls != 15 || wm.SyncedLoopEvents != 2 || wm.SyncedPrompts != 3 {
		t.Errorf("watermark mismatch: got %+v, want %+v", wm, st)
	}

	// Test PopulateSessionStates
	sessionStates := make(map[string]*TranscriptState)
	loaded.PopulateSessionStates(sessionStates)

	restored, ok := sessionStates[st.Path]
	if !ok {
		t.Fatalf("session %s not found in populated sessionStates", st.Path)
	}
	if restored.ConvID != st.ConvID || !restored.InitialSynced || restored.Offset != st.Offset {
		t.Errorf("restored state mismatch: got %+v, want %+v", restored, st)
	}
}

func TestState_MalformedFileRecoversGracefully(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "broken.json")

	if err := os.WriteFile(path, []byte("{ this is not valid json "), 0o644); err != nil {
		t.Fatal(err)
	}

	state, err := LoadState(path)
	if err == nil {
		t.Fatal("expected error on malformed JSON, got nil")
	}
	if state == nil || state.Sessions == nil {
		t.Fatal("expected non-nil recovery state even on malformed JSON")
	}
}
