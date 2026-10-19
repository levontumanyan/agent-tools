package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type ToolCall struct {
	Name string          `json:"name"`
	Args json.RawMessage `json:"args"`
}

type Event struct {
	StepIndex int        `json:"step_index"`
	Type      string     `json:"type"`
	Status    string     `json:"status"`
	CreatedAt string     `json:"created_at"`
	Content   string     `json:"content"`
	ToolCalls []ToolCall `json:"tool_calls"`
}

type ToolCallRecord struct {
	DBID             int64
	StepIndex        int
	Tool             string
	CommandBin       string // extracted CLI binary (for run_command)
	SanitizedCommand string
	ToolAction       string
	IsFailed         bool
	FailureReason    string
	ExitCode         *int
	Timestamp        time.Time
	DurationSeconds  float64
	Mode             string // autonomous, chat_initiated, user_approved, user_rejected
}

type LoopEvent struct {
	Timestamp time.Time
	LoopType  string
	Target    string
	Count     int
	Message   string
}

type PromptRecord struct {
	TurnNumber int
	StepIndex  int
	Timestamp  time.Time
	PromptText string
}

type SessionMetadata struct {
	SessionID          string
	ShortID            string
	Workspace          string
	FirstPrompt        string
	StartTime          time.Time
	EndTime            time.Time
	DurationSeconds    float64
	TotalSteps         int
	UserTurns          int
	ModelTurns         int
	TotalToolCalls     int
	AutonomousCalls    int
	ChatInitiatedCalls int
	ApprovedCalls      int
	RejectedCalls      int
	FailedCalls        int
	Prompts            []PromptRecord
	ToolCalls          []ToolCallRecord
	LoopEvents         []LoopEvent
}

// ParseLine decodes a JSONL line into an Event.
func ParseLine(line []byte) (*Event, error) {
	clean := strings.TrimSpace(string(line))
	if len(clean) == 0 {
		return nil, fmt.Errorf("empty line")
	}
	var evt Event
	if err := json.Unmarshal([]byte(clean), &evt); err != nil {
		return nil, err
	}
	return &evt, nil
}

type cachedLogConfirmations struct {
	modTime time.Time
	size    int64
	byConv  map[string]map[int]bool
}

var logConfirmationCache = make(map[string]cachedLogConfirmations)

// LoadToolConfirmations searches Antigravity CLI log files for interactive tool confirmations
// belonging to the given conversation ID. Returns a map of stepIdx -> approved.
func LoadToolConfirmations(convID string) map[int]bool {
	confirmations := make(map[int]bool)
	if convID == "" {
		return confirmations
	}

	home, err := os.UserHomeDir()
	if err != nil {
		return confirmations
	}

	searchDirs := []string{
		filepath.Join(home, ".gemini", "antigravity-cli", "log"),
		filepath.Join(home, ".gemini", "antigravity", "log"),
		filepath.Join(home, ".gemini", "antigravity-ide", "log"),
	}

	for _, dir := range searchDirs {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}

		for _, entry := range entries {
			if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".log") {
				continue
			}

			fullPath := filepath.Join(dir, entry.Name())
			fi, err := os.Lstat(fullPath)
			if err != nil || !fi.Mode().IsRegular() {
				continue
			}

			cached, ok := logConfirmationCache[fullPath]
			if !ok || !fi.ModTime().Equal(cached.modTime) || fi.Size() != cached.size {
				byConv := parseLogFileConfirmations(fullPath, fi.Size())
				cached = cachedLogConfirmations{
					modTime: fi.ModTime(),
					size:    fi.Size(),
					byConv:  byConv,
				}
				logConfirmationCache[fullPath] = cached
			}

			if steps, found := cached.byConv[convID]; found {
				for stepIdx, approved := range steps {
					confirmations[stepIdx] = approved
				}
			}
		}
	}

	return confirmations
}

func parseLogFileConfirmations(fullPath string, fileSize int64) map[string]map[int]bool {
	byConv := make(map[string]map[int]bool)
	file, err := os.Open(fullPath)
	if err != nil {
		return byConv
	}
	defer file.Close()

	const tailSize = 2 * 1024 * 1024
	if fileSize > tailSize {
		_, _ = file.Seek(-tailSize, io.SeekEnd)
	}

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.Contains(line, "approved=true") && !strings.Contains(line, "approved=false") {
			continue
		}

		var convID string
		if idx := strings.Index(line, "convID="); idx != -1 {
			rest := line[idx+len("convID="):]
			if end := strings.IndexAny(rest, " \t\r\n"); end != -1 {
				convID = rest[:end]
			} else {
				convID = rest
			}
		} else if idx := strings.Index(line, "Tool confirmation for conversation "); idx != -1 {
			rest := line[idx+len("Tool confirmation for conversation "):]
			if end := strings.IndexAny(rest, " :\t\r\n"); end != -1 {
				convID = rest[:end]
			} else {
				convID = rest
			}
		}
		if convID == "" {
			continue
		}

		approved := strings.Contains(line, "approved=true")
		var stepIdx int
		parsedStep := false
		if idx := strings.Index(line, "stepIdx="); idx != -1 {
			if _, err := fmt.Sscanf(line[idx:], "stepIdx=%d", &stepIdx); err == nil {
				parsedStep = true
			}
		} else if idx := strings.Index(line, "step "); idx != -1 {
			if _, err := fmt.Sscanf(line[idx:], "step %d", &stepIdx); err == nil {
				parsedStep = true
			}
		}
		if parsedStep {
			if byConv[convID] == nil {
				byConv[convID] = make(map[int]bool)
			}
			byConv[convID][stepIdx] = approved
		}
	}

	return byConv
}

// ExtractCommandBinary extracts the root executable name from a command line string.
// It handles leading environment variables (e.g. VAR=val cmd), command prefixes
// like sudo/nohup/time/xargs, and path prefixes (e.g. /usr/bin/git -> git).
func ExtractCommandBinary(cmdLine string) string {
	cmdLine = strings.TrimSpace(cmdLine)
	if cmdLine == "" {
		return ""
	}

	fields := strings.Fields(cmdLine)
	if len(fields) == 0 {
		return ""
	}

	skipPrefixes := map[string]bool{
		"sudo":  true,
		"env":   true,
		"nohup": true,
		"time":  true,
		"xargs": true,
		"exec":  true,
	}

	for _, field := range fields {
		// Skip environment variable assignments like FOO=bar or A=1
		if strings.Contains(field, "=") && !strings.HasPrefix(field, "-") && !strings.HasPrefix(field, "/") && !strings.HasPrefix(field, "./") {
			continue
		}
		bin := filepath.Base(field)
		bin = strings.Trim(bin, `"'`)
		if skipPrefixes[bin] {
			continue
		}
		if bin == "" || bin == "." || bin == ".." {
			continue
		}
		return bin
	}
	return ""
}

// TranscriptState holds incremental parsing and database synchronization state for a session transcript.
type TranscriptState struct {
	Path     string
	ConvID   string
	ShortID  string
	ModTime  time.Time
	FileSize int64
	Offset   int64
	Meta     *SessionMetadata

	// Incremental parser state across appended JSONL lines
	taskPollingFreq              map[string]int
	filesReadFreq                map[string]int
	lastCommand                  string
	consecutiveCommandCount      int
	nextPlannerIsPromptTriggered bool
	pendingToolIndices           []int
	stepToToolIndices            map[int][]int
	explicitlyDeniedTools        map[int]bool

	// Database delta-sync watermarks
	InitialSynced       bool
	LastSyncedWorkspace string
	SyncedToolCalls     int
	SyncedLoopEvents    int
	SyncedPrompts       int
	DirtyToolCallIdxs   map[int]bool
}

// NewTranscriptState initializes an empty incremental parser state for a transcript file.
func NewTranscriptState(transcriptPath string) *TranscriptState {
	convID := extractConversationID(transcriptPath)
	shortID := convID
	if len(shortID) > 8 {
		shortID = shortID[:8]
	}

	st := &TranscriptState{
		Path:    transcriptPath,
		ConvID:  convID,
		ShortID: shortID,
	}
	st.Reset()
	return st
}

// Reset clears all parsed state and watermarks so the file will be parsed and synced from byte 0.
func (st *TranscriptState) Reset() {
	st.Offset = 0
	st.ModTime = time.Time{}
	st.FileSize = 0
	st.Meta = &SessionMetadata{
		SessionID:  st.ConvID,
		ShortID:    st.ShortID,
		Workspace:  "unknown",
		Prompts:    make([]PromptRecord, 0),
		ToolCalls:  make([]ToolCallRecord, 0),
		LoopEvents: make([]LoopEvent, 0),
	}
	st.taskPollingFreq = make(map[string]int)
	st.filesReadFreq = make(map[string]int)
	st.lastCommand = ""
	st.consecutiveCommandCount = 0
	st.nextPlannerIsPromptTriggered = false
	st.pendingToolIndices = nil
	st.stepToToolIndices = make(map[int][]int)
	st.explicitlyDeniedTools = make(map[int]bool)

	st.InitialSynced = false
	st.LastSyncedWorkspace = ""
	st.SyncedToolCalls = 0
	st.SyncedLoopEvents = 0
	st.SyncedPrompts = 0
	st.DirtyToolCallIdxs = make(map[int]bool)
}

// UpdateIncremental seeks to the last read byte offset in the transcript and parses only newly appended lines.
// Returns true if any new steps or confirmation changes were parsed.
func (st *TranscriptState) UpdateIncremental(modTime time.Time, size int64) (bool, error) {
	if size < st.Offset {
		// File was truncated or rewritten from scratch
		st.Reset()
	}

	file, err := os.Open(st.Path)
	if err != nil {
		return false, fmt.Errorf("failed to open transcript: %w", err)
	}
	defer file.Close()

	if st.Offset > 0 {
		if _, err := file.Seek(st.Offset, io.SeekStart); err != nil {
			return false, fmt.Errorf("failed to seek transcript to %d: %w", st.Offset, err)
		}
	}

	confirmations := LoadToolConfirmations(st.ConvID)
	changed := st.reconcileConfirmations(confirmations)

	reader := bufio.NewReaderSize(file, 64*1024)
	const maxLineBytes = 10 * 1024 * 1024 // 10 MB line limit

	for {
		var line []byte
		var bytesInLine int64
		var oversized bool
		var hitEOF bool

		for {
			chunk, err := reader.ReadSlice('\n')
			bytesInLine += int64(len(chunk))
			if !oversized && len(chunk) > 0 {
				if len(line)+len(chunk) > maxLineBytes {
					oversized = true
					line = nil
				} else {
					line = append(line, chunk...)
				}
			}

			if err == nil {
				break
			}
			if err == bufio.ErrBufferFull {
				continue
			}
			if err == io.EOF {
				hitEOF = true
				break
			}
			return changed, fmt.Errorf("failed to read transcript: %w", err)
		}

		if bytesInLine == 0 && hitEOF {
			break
		}

		hasTrailingNewline := len(line) > 0 && line[len(line)-1] == '\n'

		if oversized {
			if hitEOF && !hasTrailingNewline {
				// Wait for the rest of the oversized line to finish flushing before advancing offset
				break
			}
			st.Offset += bytesInLine
			continue
		}

		trimmed := strings.TrimSpace(string(line))
		if len(trimmed) == 0 {
			if hitEOF && !hasTrailingNewline {
				break
			}
			st.Offset += bytesInLine
			continue
		}

		evt, err := ParseLine(line)
		if err != nil {
			if hitEOF && !hasTrailingNewline {
				// Incomplete partial JSON line at EOF during concurrent write; wait for next pass
				break
			}
			// Malformed complete line; skip past it
			st.Offset += bytesInLine
			continue
		}

		st.Offset += bytesInLine
		st.processEvent(evt, confirmations)
		changed = true

		if hitEOF {
			break
		}
	}

	if !st.Meta.StartTime.IsZero() && !st.Meta.EndTime.IsZero() {
		st.Meta.DurationSeconds = st.Meta.EndTime.Sub(st.Meta.StartTime).Seconds()
	}
	if st.Meta.Workspace == "" {
		st.Meta.Workspace = "unknown"
	}

	st.ModTime = modTime
	st.FileSize = size
	return changed, nil
}

func (st *TranscriptState) reconcileConfirmations(confirmations map[int]bool) bool {
	if len(confirmations) == 0 || len(st.Meta.ToolCalls) == 0 {
		return false
	}
	changed := false
	sm := st.Meta
	for stepIdx, approved := range confirmations {
		indices := st.stepToToolIndices[stepIdx]
		for _, idx := range indices {
			if !approved && sm.ToolCalls[idx].Mode != "user_rejected" {
				st.changeToolCallMode(idx, "user_rejected")
				changed = true
			} else if approved && sm.ToolCalls[idx].Mode != "user_approved" && !st.explicitlyDeniedTools[idx] {
				st.changeToolCallMode(idx, "user_approved")
				changed = true
			}
		}
	}
	return changed
}

func (st *TranscriptState) changeToolCallMode(idx int, newMode string) {
	sm := st.Meta
	oldMode := sm.ToolCalls[idx].Mode
	if oldMode == newMode {
		return
	}
	switch oldMode {
	case "autonomous":
		sm.AutonomousCalls--
	case "chat_initiated":
		sm.ChatInitiatedCalls--
	case "user_approved":
		sm.ApprovedCalls--
	case "user_rejected":
		sm.RejectedCalls--
	}
	sm.ToolCalls[idx].Mode = newMode
	switch newMode {
	case "autonomous":
		sm.AutonomousCalls++
	case "chat_initiated":
		sm.ChatInitiatedCalls++
	case "user_approved":
		sm.ApprovedCalls++
	case "user_rejected":
		sm.RejectedCalls++
	}
	if idx < st.SyncedToolCalls {
		st.DirtyToolCallIdxs[idx] = true
	}
}

func (st *TranscriptState) processEvent(evt *Event, confirmations map[int]bool) {
	sm := st.Meta
	sm.TotalSteps++

	var stepTime time.Time
	if evt.CreatedAt != "" {
		t, err := time.Parse(time.RFC3339, evt.CreatedAt)
		if err == nil {
			stepTime = t
			if sm.StartTime.IsZero() || t.Before(sm.StartTime) {
				sm.StartTime = t
			}
			if t.After(sm.EndTime) {
				sm.EndTime = t
			}
		}
	}

	switch evt.Type {
	case "USER_INPUT":
		sm.UserTurns++
		st.pendingToolIndices = nil
		st.nextPlannerIsPromptTriggered = true

		if sm.FirstPrompt == "" {
			sm.FirstPrompt = extractCleanPrompt(evt.Content)
		}
		cleanPrompt := extractCleanPromptLimit(evt.Content, 2000)
		if cleanPrompt != "" {
			sm.Prompts = append(sm.Prompts, PromptRecord{
				TurnNumber: sm.UserTurns,
				StepIndex:  evt.StepIndex,
				Timestamp:  stepTime,
				PromptText: cleanPrompt,
			})
		}

		if sm.Workspace == "" || sm.Workspace == "unknown" {
			if strings.Contains(evt.Content, "Active Workspaces:") {
				parts := strings.Split(evt.Content, "Active Workspaces:")
				if len(parts) > 1 {
					for _, l := range strings.Split(parts[1], "\n") {
						l = strings.TrimSpace(l)
						if strings.HasPrefix(l, "- ") {
							ws := strings.TrimSpace(strings.TrimPrefix(l, "- "))
							sm.Workspace = Sanitize(ws, 120)
							break
						}
					}
				}
			}
			if (sm.Workspace == "" || sm.Workspace == "unknown") && strings.Contains(evt.Content, "Command Working Directory:") {
				parts := strings.Split(evt.Content, "Command Working Directory:")
				if len(parts) > 1 {
					lines := strings.Split(parts[1], "\n")
					if len(lines) > 0 {
						sm.Workspace = Sanitize(strings.TrimSpace(lines[0]), 120)
					}
				}
			}
		}

	case "PLANNER_RESPONSE":
		sm.ModelTurns++
		isPromptTurn := st.nextPlannerIsPromptTriggered
		st.nextPlannerIsPromptTriggered = false

		for _, call := range evt.ToolCalls {
			sm.TotalToolCalls++

			mode := "autonomous"
			if conf, prompted := confirmations[evt.StepIndex]; prompted {
				if conf {
					mode = "user_approved"
					sm.ApprovedCalls++
				} else {
					mode = "user_rejected"
					sm.RejectedCalls++
				}
			} else if isPromptTurn {
				mode = "chat_initiated"
				sm.ChatInitiatedCalls++
			} else {
				sm.AutonomousCalls++
			}

			rec := ToolCallRecord{
				StepIndex: evt.StepIndex,
				Tool:      call.Name,
				Mode:      mode,
				Timestamp: stepTime,
			}

			switch call.Name {
			case "run_command":
				var args struct {
					CommandLine string `json:"CommandLine"`
					ToolSummary string `json:"toolSummary"`
					ToolAction  string `json:"toolAction"`
					Cwd         string `json:"Cwd"`
				}
				if err := json.Unmarshal(call.Args, &args); err == nil && args.CommandLine != "" {
					cmd := strings.Trim(strings.TrimSpace(args.CommandLine), "\"'")
					rec.SanitizedCommand = Sanitize(cmd, 120)
					rec.CommandBin = ExtractCommandBinary(cmd)
					rec.ToolAction = Sanitize(args.ToolAction, 120)
					if (sm.Workspace == "" || sm.Workspace == "unknown") && args.Cwd != "" {
						cleanCwd := strings.Trim(strings.TrimSpace(args.Cwd), "\"'")
						if cleanCwd != "" {
							sm.Workspace = Sanitize(cleanCwd, 120)
						}
					}

					// Consecutive command loop detection (>= 3 times in a row)
					if cmd == st.lastCommand {
						st.consecutiveCommandCount++
						if st.consecutiveCommandCount >= 3 {
							msg := fmt.Sprintf("Consecutive command loop: %q executed %d times in a row", Sanitize(cmd, 60), st.consecutiveCommandCount)
							sm.LoopEvents = append(sm.LoopEvents, LoopEvent{
								Timestamp: stepTime,
								LoopType:  "consecutive_command",
								Target:    Sanitize(cmd, 120),
								Count:     st.consecutiveCommandCount,
								Message:   msg,
							})
						}
					} else {
						st.lastCommand = cmd
						st.consecutiveCommandCount = 1
					}
				}

			case "view_file":
				var args struct {
					AbsolutePath string `json:"AbsolutePath"`
					ToolAction   string `json:"toolAction"`
				}
				if err := json.Unmarshal(call.Args, &args); err == nil && args.AbsolutePath != "" {
					cleanPath := strings.Trim(strings.TrimSpace(args.AbsolutePath), "\"'")
					rec.SanitizedCommand = "Read " + Sanitize(cleanPath, 120)
					rec.ToolAction = Sanitize(args.ToolAction, 120)
					sanitizedTarget := Sanitize(cleanPath, 120)

					st.filesReadFreq[sanitizedTarget]++
					if st.filesReadFreq[sanitizedTarget] >= 4 {
						msg := fmt.Sprintf("Frequent file re-read: %s inspected %d times", sanitizedTarget, st.filesReadFreq[sanitizedTarget])
						sm.LoopEvents = append(sm.LoopEvents, LoopEvent{
							Timestamp: stepTime,
							LoopType:  "frequent_file_read",
							Target:    sanitizedTarget,
							Count:     st.filesReadFreq[sanitizedTarget],
							Message:   msg,
						})
					}
				}

			case "replace_file_content", "write_to_file":
				var args struct {
					TargetFile string `json:"TargetFile"`
					ToolAction string `json:"toolAction"`
				}
				if err := json.Unmarshal(call.Args, &args); err == nil && args.TargetFile != "" {
					cleanTarget := strings.Trim(strings.TrimSpace(args.TargetFile), "\"'")
					rec.SanitizedCommand = "Edit " + Sanitize(cleanTarget, 120)
					rec.ToolAction = Sanitize(args.ToolAction, 120)
				}

			case "manage_task":
				var args struct {
					Action      string `json:"Action"`
					TaskId      string `json:"TaskId"`
					ToolSummary string `json:"toolSummary"`
					ToolAction  string `json:"toolAction"`
				}
				if err := json.Unmarshal(call.Args, &args); err == nil {
					summary := fmt.Sprintf("Task %s (%s)", args.Action, args.TaskId)
					if args.ToolSummary != "" {
						summary = args.ToolSummary
					}
					rec.SanitizedCommand = Sanitize(summary, 120)
					rec.ToolAction = Sanitize(args.ToolAction, 120)
					if args.Action == "status" {
						st.taskPollingFreq[args.TaskId]++
						if st.taskPollingFreq[args.TaskId] >= 3 {
							msg := fmt.Sprintf("Task polling loop: status of %q checked %d times", args.TaskId, st.taskPollingFreq[args.TaskId])
							sm.LoopEvents = append(sm.LoopEvents, LoopEvent{
								Timestamp: stepTime,
								LoopType:  "polling_spiral",
								Target:    args.TaskId,
								Count:     st.taskPollingFreq[args.TaskId],
								Message:   msg,
							})
						}
					}
				}

			case "schedule":
				var args struct {
					DurationSeconds int    `json:"DurationSeconds"`
					ToolAction      string `json:"toolAction"`
				}
				if err := json.Unmarshal(call.Args, &args); err == nil {
					rec.SanitizedCommand = fmt.Sprintf("Timer (%ds)", args.DurationSeconds)
					rec.ToolAction = Sanitize(args.ToolAction, 120)
				}

			default:
				var args struct {
					ToolAction string `json:"toolAction"`
				}
				_ = json.Unmarshal(call.Args, &args)
				rec.SanitizedCommand = Sanitize(call.Name, 120)
				rec.ToolAction = Sanitize(args.ToolAction, 120)
			}

			recIdx := len(sm.ToolCalls)
			sm.ToolCalls = append(sm.ToolCalls, rec)
			st.stepToToolIndices[evt.StepIndex] = append(st.stepToToolIndices[evt.StepIndex], recIdx)
			st.pendingToolIndices = append(st.pendingToolIndices, recIdx)
		}

	case "GENERIC":
		if len(st.pendingToolIndices) > 0 {
			idx := st.pendingToolIndices[0]
			st.pendingToolIndices = st.pendingToolIndices[1:]

			content := evt.Content
			isFailed := false
			var failureMsg string
			var exitCode *int

			if evt.Status == "ERROR" {
				isFailed = true
				failureMsg = "Tool reported error status"
			} else if strings.Contains(content, "Encountered error in tool execution") {
				isFailed = true
				for _, l := range strings.Split(content, "\n") {
					if strings.Contains(l, "Encountered error in tool execution") {
						failureMsg = Sanitize(strings.TrimSpace(l), 120)
						break
					}
				}
			} else {
				var lastExitCodeStr string
				var lastExitCodeMsg string
				for _, l := range strings.Split(content, "\n") {
					trimmed := strings.TrimSpace(l)
					if strings.HasPrefix(trimmed, "The command exited with code ") {
						codeStr := strings.TrimSuffix(strings.TrimPrefix(trimmed, "The command exited with code "), ".")
						lastExitCodeStr = codeStr
						lastExitCodeMsg = trimmed
					}
				}
				if lastExitCodeStr != "" {
					var code int
					if _, err := fmt.Sscanf(lastExitCodeStr, "%d", &code); err == nil {
						exitCode = &code
						if code != 0 {
							isFailed = true
							failureMsg = Sanitize(lastExitCodeMsg, 120)
						}
					}
				}
			}

			if isFailed {
				sm.ToolCalls[idx].IsFailed = true
				sm.ToolCalls[idx].FailureReason = failureMsg
				sm.FailedCalls++
			}
			sm.ToolCalls[idx].ExitCode = exitCode

			// Retroactively check if this tool execution was confirmed or denied by human in terminal
			isDenied := false
			if strings.Contains(evt.Content, "user denied permission") || strings.Contains(evt.Content, "permission check failed") {
				isDenied = true
				st.explicitlyDeniedTools[idx] = true
			}
			if conf, prompted := confirmations[evt.StepIndex]; prompted && !conf {
				isDenied = true
			}

			if isDenied && sm.ToolCalls[idx].Mode != "user_rejected" {
				st.changeToolCallMode(idx, "user_rejected")
			} else if conf, prompted := confirmations[evt.StepIndex]; prompted && conf && sm.ToolCalls[idx].Mode != "user_approved" {
				st.changeToolCallMode(idx, "user_approved")
			}

			if !stepTime.IsZero() && !sm.ToolCalls[idx].Timestamp.IsZero() {
				if stepTime.After(sm.ToolCalls[idx].Timestamp) {
					sm.ToolCalls[idx].DurationSeconds = stepTime.Sub(sm.ToolCalls[idx].Timestamp).Seconds()
				}
			}

			if idx < st.SyncedToolCalls {
				st.DirtyToolCallIdxs[idx] = true
			}
		}
	}
}

// ParseTranscript analyzes a transcript.jsonl file from start to finish into full SessionMetadata.
func ParseTranscript(transcriptPath string) (*SessionMetadata, error) {
	fi, err := os.Stat(transcriptPath)
	if err != nil {
		return nil, fmt.Errorf("failed to stat transcript: %w", err)
	}
	st := NewTranscriptState(transcriptPath)
	if _, err := st.UpdateIncremental(fi.ModTime(), fi.Size()); err != nil {
		return nil, err
	}
	return st.Meta, nil
}

func extractCleanPrompt(content string) string {
	return extractCleanPromptLimit(content, 80)
}

func extractCleanPromptLimit(content string, maxRunes int) string {
	content = strings.TrimSpace(content)
	if strings.Contains(content, "<USER_REQUEST>") {
		parts := strings.Split(content, "<USER_REQUEST>")
		if len(parts) > 1 {
			sub := strings.Split(parts[1], "</USER_REQUEST>")
			content = strings.TrimSpace(sub[0])
		}
	}
	if strings.Contains(content, "<ADDITIONAL_METADATA>") {
		parts := strings.Split(content, "<ADDITIONAL_METADATA>")
		content = strings.TrimSpace(parts[0])
	}
	content = strings.ReplaceAll(content, "\n", " ")
	return Sanitize(content, maxRunes)
}

func extractConversationID(path string) string {
	parts := strings.Split(path, "/brain/")
	if len(parts) > 1 {
		sub := strings.Split(parts[1], "/")
		if len(sub) > 0 && sub[0] != "" {
			return sub[0]
		}
	}
	return filepath.Base(filepath.Dir(filepath.Dir(filepath.Dir(path))))
}

type SessionSummary struct {
	ID      string
	ShortID string
	ModTime time.Time
	Size    int64
	Path    string
}

type cachedTranscriptEntry struct {
	convID     string
	shortID    string
	path       string
	modTime    time.Time
	size       int64
	hasFile    bool
	discovered time.Time
}

type brainDirCache struct {
	dirModTime          time.Time
	entries             map[string]*cachedTranscriptEntry
	orderedIDs          []string
	ticksSinceFullSweep int
}

var discoveryCaches = make(map[string]*brainDirCache)

// ResetDiscoveryCache clears the in-memory directory discovery cache (used in tests).
func ResetDiscoveryCache() {
	discoveryCaches = make(map[string]*brainDirCache)
}

const (
	fullSweepTickInterval = 12 // Full sweep of archival sessions every 12 ticks (60s at 5s interval)
	minHotStatCount       = 40 // Number of top recent transcripts to stat on every fast tick
	pendingNewDirTTL      = 15 * time.Minute
)

// DiscoverRecentTranscripts finds recent transcript.jsonl files across ~/.gemini app data paths
// using a two-tier cache to avoid calling os.Stat on hundreds of dormant session folders every tick.
func DiscoverRecentTranscripts(maxCount int) ([]SessionSummary, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}

	candidates := []string{
		filepath.Join(home, ".gemini", "antigravity-cli", "brain"),
		filepath.Join(home, ".gemini", "antigravity", "brain"),
		filepath.Join(home, ".gemini", "antigravity-ide", "brain"),
	}

	hotLimit := minHotStatCount
	if maxCount*2 > hotLimit {
		hotLimit = maxCount * 2
	}

	now := time.Now()
	var activeList []*cachedTranscriptEntry
	seen := make(map[string]bool)

	for _, dir := range candidates {
		dirInfo, err := os.Stat(dir)
		if err != nil || !dirInfo.IsDir() {
			continue
		}

		cache, exists := discoveryCaches[dir]
		if !exists {
			cache = &brainDirCache{
				entries: make(map[string]*cachedTranscriptEntry),
			}
			discoveryCaches[dir] = cache
			scanBrainDirFull(dir, dirInfo.ModTime(), cache, now)
		} else {
			cache.ticksSinceFullSweep++
			dirChanged := !dirInfo.ModTime().Equal(cache.dirModTime)

			if cache.ticksSinceFullSweep >= fullSweepTickInterval {
				scanBrainDirFull(dir, dirInfo.ModTime(), cache, now)
			} else {
				if dirChanged {
					scanBrainDirNewEntries(dir, dirInfo.ModTime(), cache, now)
				}
				effectiveHotLimit := hotLimit
				if maxCount <= 0 {
					effectiveHotLimit = len(cache.orderedIDs)
				}
				statHotTranscripts(cache, effectiveHotLimit, now)
			}
		}

		for _, convID := range cache.orderedIDs {
			if seen[convID] {
				continue
			}
			entry := cache.entries[convID]
			if entry == nil || !entry.hasFile || entry.size == 0 {
				continue
			}
			seen[convID] = true
			activeList = append(activeList, entry)
		}
	}

	sort.Slice(activeList, func(i, j int) bool {
		return activeList[i].modTime.After(activeList[j].modTime)
	})

	if maxCount > 0 && len(activeList) > maxCount {
		activeList = activeList[:maxCount]
	}

	results := make([]SessionSummary, 0, len(activeList))
	for _, c := range activeList {
		results = append(results, SessionSummary{
			ID:      c.convID,
			ShortID: c.shortID,
			ModTime: c.modTime,
			Size:    c.size,
			Path:    c.path,
		})
	}

	return results, nil
}

func scanBrainDirFull(dir string, dirModTime time.Time, cache *brainDirCache, now time.Time) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	cache.dirModTime = dirModTime
	cache.ticksSinceFullSweep = 0

	present := make(map[string]bool, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		convID := entry.Name()
		present[convID] = true

		item, ok := cache.entries[convID]
		if !ok {
			shortID := convID
			if len(shortID) > 8 {
				shortID = shortID[:8]
			}
			item = &cachedTranscriptEntry{
				convID:     convID,
				shortID:    shortID,
				path:       filepath.Join(dir, convID, ".system_generated", "logs", "transcript.jsonl"),
				discovered: now,
			}
			cache.entries[convID] = item
		}

		if fi, err := os.Stat(item.path); err == nil && fi.Size() > 0 {
			item.modTime = fi.ModTime()
			item.size = fi.Size()
			item.hasFile = true
		} else {
			item.hasFile = false
			item.size = 0
		}
	}

	for convID := range cache.entries {
		if !present[convID] {
			delete(cache.entries, convID)
		}
	}

	rebuildOrderedIDs(cache)
}

func scanBrainDirNewEntries(dir string, dirModTime time.Time, cache *brainDirCache, now time.Time) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	cache.dirModTime = dirModTime

	present := make(map[string]bool, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		convID := entry.Name()
		present[convID] = true

		if _, ok := cache.entries[convID]; !ok {
			shortID := convID
			if len(shortID) > 8 {
				shortID = shortID[:8]
			}
			tPath := filepath.Join(dir, convID, ".system_generated", "logs", "transcript.jsonl")
			item := &cachedTranscriptEntry{
				convID:     convID,
				shortID:    shortID,
				path:       tPath,
				discovered: now,
			}
			if fi, err := os.Stat(tPath); err == nil && fi.Size() > 0 {
				item.modTime = fi.ModTime()
				item.size = fi.Size()
				item.hasFile = true
			}
			cache.entries[convID] = item
		}
	}

	for convID := range cache.entries {
		if !present[convID] {
			delete(cache.entries, convID)
		}
	}

	rebuildOrderedIDs(cache)
}

func statHotTranscripts(cache *brainDirCache, hotLimit int, now time.Time) {
	checked := make(map[string]bool, hotLimit)

	for i, convID := range cache.orderedIDs {
		if i >= hotLimit {
			break
		}
		item := cache.entries[convID]
		if item == nil {
			continue
		}
		checked[convID] = true
		if fi, err := os.Stat(item.path); err == nil && fi.Size() > 0 {
			item.modTime = fi.ModTime()
			item.size = fi.Size()
			item.hasFile = true
		} else {
			item.hasFile = false
			item.size = 0
		}
	}

	// Also check recently created session folders that did not have a non-empty transcript.jsonl yet
	for convID, item := range cache.entries {
		if checked[convID] || item.hasFile {
			continue
		}
		if now.Sub(item.discovered) <= pendingNewDirTTL {
			if fi, err := os.Stat(item.path); err == nil && fi.Size() > 0 {
				item.modTime = fi.ModTime()
				item.size = fi.Size()
				item.hasFile = true
			}
		}
	}

	rebuildOrderedIDs(cache)
}

func rebuildOrderedIDs(cache *brainDirCache) {
	ids := make([]string, 0, len(cache.entries))
	for convID, item := range cache.entries {
		if item.hasFile && item.size > 0 {
			ids = append(ids, convID)
		}
	}
	sort.Slice(ids, func(i, j int) bool {
		return cache.entries[ids[i]].modTime.After(cache.entries[ids[j]].modTime)
	})
	cache.orderedIDs = ids
}
