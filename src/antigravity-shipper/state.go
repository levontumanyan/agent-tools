package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const (
	CurrentStateVersion  = 1
	DefaultStateFileName = "antigravity-shipper-state.json"
)

// SessionWatermark records synchronization state for a single conversation transcript.
type SessionWatermark struct {
	Path                string    `json:"path"`
	ConvID              string    `json:"conv_id"`
	ShortID             string    `json:"short_id"`
	ModTime             time.Time `json:"mod_time"`
	FileSize            int64     `json:"file_size"`
	Offset              int64     `json:"offset"`
	InitialSynced       bool      `json:"initial_synced"`
	LastSyncedWorkspace string    `json:"last_synced_workspace,omitempty"`
	SyncedToolCalls     int       `json:"synced_tool_calls"`
	SyncedLoopEvents    int       `json:"synced_loop_events"`
	SyncedPrompts       int       `json:"synced_prompts"`
}

// PersistentState stores watermarks for all sessions.
type PersistentState struct {
	Version   int                          `json:"version"`
	UpdatedAt time.Time                    `json:"updated_at"`
	Sessions  map[string]*SessionWatermark `json:"sessions"`
	mu        sync.RWMutex
}

// NewPersistentState returns an initialized PersistentState struct.
func NewPersistentState() *PersistentState {
	return &PersistentState{
		Version:  CurrentStateVersion,
		Sessions: make(map[string]*SessionWatermark),
	}
}

// DefaultStatePath returns ~/.gemini/antigravity-shipper-state.json.
func DefaultStatePath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".gemini", DefaultStateFileName), nil
}

// LoadState reads and unmarshals PersistentState from the specified file.
// If the file does not exist, it returns a new empty PersistentState without error.
func LoadState(path string) (*PersistentState, error) {
	if path == "" {
		var err error
		path, err = DefaultStatePath()
		if err != nil {
			return nil, err
		}
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return NewPersistentState(), nil
		}
		return nil, fmt.Errorf("failed to read state file: %w", err)
	}

	state := NewPersistentState()
	if err := json.Unmarshal(data, state); err != nil {
		return NewPersistentState(), fmt.Errorf("malformed state file (will regenerate): %w", err)
	}
	if state.Sessions == nil {
		state.Sessions = make(map[string]*SessionWatermark)
	}
	return state, nil
}

// SaveState writes PersistentState atomically to disk (write to .tmp then rename).
func (s *PersistentState) SaveState(path string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if path == "" {
		var err error
		path, err = DefaultStatePath()
		if err != nil {
			return err
		}
	}

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("failed to create state dir: %w", err)
	}

	s.Version = CurrentStateVersion
	s.UpdatedAt = time.Now().UTC()

	data, err := json.MarshalIndent(s, "", "\t")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}

	tmpPath := fmt.Sprintf("%s.tmp.%d", path, time.Now().UnixNano())
	if err := os.WriteFile(tmpPath, data, 0o644); err != nil {
		return fmt.Errorf("failed to write tmp state file: %w", err)
	}

	if err := os.Rename(tmpPath, path); err != nil {
		_ = os.Remove(tmpPath)
		return fmt.Errorf("failed to commit state file atomically: %w", err)
	}

	return nil
}

// UpdateFromSession updates or inserts the watermark for a given TranscriptState.
func (s *PersistentState) UpdateFromSession(st *TranscriptState) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.Sessions[st.Path] = &SessionWatermark{
		Path:                st.Path,
		ConvID:              st.ConvID,
		ShortID:             st.ShortID,
		ModTime:             st.ModTime,
		FileSize:            st.FileSize,
		Offset:              st.Offset,
		InitialSynced:       st.InitialSynced,
		LastSyncedWorkspace: st.LastSyncedWorkspace,
		SyncedToolCalls:     st.SyncedToolCalls,
		SyncedLoopEvents:    st.SyncedLoopEvents,
		SyncedPrompts:       st.SyncedPrompts,
	}
}

// PopulateSessionStates seeds in-memory sessionStates from loaded watermarks.
func (s *PersistentState) PopulateSessionStates(sessionStates map[string]*TranscriptState) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for path, wm := range s.Sessions {
		st := &TranscriptState{
			Path:                  wm.Path,
			ConvID:                wm.ConvID,
			ShortID:               wm.ShortID,
			ModTime:               wm.ModTime,
			FileSize:              wm.FileSize,
			Offset:                wm.Offset,
			InitialSynced:         wm.InitialSynced,
			LastSyncedWorkspace:   wm.LastSyncedWorkspace,
			SyncedToolCalls:       wm.SyncedToolCalls,
			SyncedLoopEvents:      wm.SyncedLoopEvents,
			SyncedPrompts:         wm.SyncedPrompts,
			DirtyToolCallIdxs:     make(map[int]bool),
			stepToToolIndices:     make(map[int][]int),
			explicitlyDeniedTools: make(map[int]bool),
		}
		sessionStates[path] = st
	}
}
