package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"strings"
	"syscall"
	"time"
)

func main() {
	var (
		pgConnStr   = flag.String("db", "", "PostgreSQL connection string (e.g. postgres://user:pass@localhost:5432/antigravity)")
		pollSec     = flag.Int("interval", 60, "Polling interval in seconds")
		once        = flag.Bool("once", false, "Run single sync pass and exit")
		recentLimit = flag.Int("limit", 0, "Number of recent sessions to monitor (0 for all)")
		stateFile   = flag.String("state", "", "Path to state cache file (default ~/.gemini/antigravity-shipper-state.json)")
	)
	flag.Parse()

	connStr := *pgConnStr
	if connStr == "" {
		connStr = os.Getenv("ANTIGRAVITY_PG_URL")
	}
	if connStr == "" && runtime.GOOS == "darwin" {
		if out, err := exec.Command("security", "find-generic-password", "-s", "antigravity-telemetry-pg-url", "-w").Output(); err == nil {
			connStr = strings.TrimSpace(string(out))
		}
	}
	if connStr == "" {
		log.Fatal("Error: PostgreSQL connection string required via -db, ANTIGRAVITY_PG_URL environment variable, or macOS Keychain (antigravity-telemetry-pg-url)")
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		log.Println("Received termination signal, shutting down shipper...")
		cancel()
	}()

	log.Printf("Connecting to PostgreSQL at %s...", redactConnStr(connStr))
	db, err := ConnectDB(ctx, connStr)
	if err != nil {
		log.Fatalf("Database connection error: %v", err)
	}
	defer db.Close()
	log.Println("Connected to PostgreSQL successfully.")

	resolvedStatePath := *stateFile
	if resolvedStatePath == "" {
		if p, err := DefaultStatePath(); err == nil {
			resolvedStatePath = p
		}
	}

	state, err := LoadState(resolvedStatePath)
	if err != nil {
		log.Printf("Warning: error loading state cache (%v), starting fresh", err)
	}

	// Track incremental parser state and DB sync watermarks per transcript path
	sessionStates := make(map[string]*TranscriptState)
	if state != nil && len(state.Sessions) > 0 {
		state.PopulateSessionStates(sessionStates)
		log.Printf("Loaded %d session watermarks from state cache (%s).", len(state.Sessions), resolvedStatePath)
	}

	syncPass := func() {
		transcripts, err := DiscoverRecentTranscripts(*recentLimit)
		if err != nil {
			log.Printf("Error discovering transcripts: %v", err)
			return
		}

		dirty := false
		for _, t := range transcripts {
			st, seen := sessionStates[t.Path]
			if seen && st.InitialSynced && !t.ModTime.After(st.ModTime) && t.Size == st.FileSize {
				continue
			}
			if !seen || st.Meta == nil {
				st = NewTranscriptState(t.Path)
				sessionStates[t.Path] = st
			}

			changed, err := st.UpdateIncremental(t.ModTime, t.Size)
			if err != nil {
				log.Printf("Error parsing transcript %s: %v", t.Path, err)
				continue
			}
			if !changed && st.InitialSynced {
				continue
			}

			if err := db.SyncSession(ctx, st); err != nil {
				log.Printf("[%s] Error syncing session: %v", st.ShortID, err)
				continue
			}

			dirty = true
			if state != nil {
				state.UpdateFromSession(st)
			}

			meta := st.Meta
			log.Printf("[%s] Synced session: %d steps, %d prompts, %d tools (%d autonomous, %d failed), %d loops (ws: %s)",
				meta.ShortID, meta.TotalSteps, len(meta.Prompts), meta.TotalToolCalls, meta.AutonomousCalls, meta.FailedCalls, len(meta.LoopEvents), meta.Workspace)
		}

		if dirty && state != nil && resolvedStatePath != "" {
			if err := state.SaveState(resolvedStatePath); err != nil {
				log.Printf("Warning: failed saving state cache: %v", err)
			}
		}
	}

	if *recentLimit <= 0 {
		log.Println("Running initial telemetry sync pass (monitoring all sessions)...")
	} else {
		log.Printf("Running initial telemetry sync pass (monitoring last %d sessions)...", *recentLimit)
	}
	syncPass()

	if *once {
		log.Println("Single sync pass complete. Exiting.")
		return
	}

	ticker := time.NewTicker(time.Duration(*pollSec) * time.Second)
	defer ticker.Stop()

	log.Printf("Shipper daemon active. Watching for transcript changes every %ds...", *pollSec)
	for {
		select {
		case <-ctx.Done():
			log.Println("Shipper stopped.")
			return
		case <-ticker.C:
			syncPass()
		}
	}
}

func redactConnStr(conn string) string {
	idxAt := -1
	idxColon := -1
	for i, c := range conn {
		if c == '@' {
			idxAt = i
			break
		}
		if c == ':' && i > 10 && idxColon == -1 {
			idxColon = i
		}
	}
	if idxColon != -1 && idxAt != -1 && idxAt > idxColon {
		return conn[:idxColon+1] + "[REDACTED]" + conn[idxAt:]
	}
	return conn
}
