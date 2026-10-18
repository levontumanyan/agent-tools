package main

import (
	"context"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type DB struct {
	pool *pgxpool.Pool
}

const upsertSessionSQL = `
	INSERT INTO sessions (
		session_id, short_id, workspace, first_prompt, start_time, end_time,
		duration_seconds, total_steps, user_turns, model_turns,
		total_tool_calls, autonomous_calls, chat_initiated_calls, approved_calls, rejected_calls, failed_calls,
		updated_at
	) VALUES (
		$1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, NOW()
	)
	ON CONFLICT (session_id) DO UPDATE SET
		workspace = EXCLUDED.workspace,
		first_prompt = COALESCE(NULLIF(EXCLUDED.first_prompt, ''), sessions.first_prompt),
		end_time = EXCLUDED.end_time,
		duration_seconds = EXCLUDED.duration_seconds,
		total_steps = EXCLUDED.total_steps,
		user_turns = EXCLUDED.user_turns,
		model_turns = EXCLUDED.model_turns,
		total_tool_calls = EXCLUDED.total_tool_calls,
		autonomous_calls = EXCLUDED.autonomous_calls,
		chat_initiated_calls = EXCLUDED.chat_initiated_calls,
		approved_calls = EXCLUDED.approved_calls,
		rejected_calls = EXCLUDED.rejected_calls,
		failed_calls = EXCLUDED.failed_calls,
		updated_at = NOW();
`

const insertToolCallReturningIDSQL = `
	INSERT INTO tool_calls (
		session_id, workspace, timestamp, step_index, tool_name, command_bin, tool_action,
		sanitized_command, exit_code, is_failed, failure_reason, duration_seconds, mode
	) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
	RETURNING id
`

const updateToolCallByIDSQL = `
	UPDATE tool_calls
	SET workspace = $1, exit_code = $2, is_failed = $3, failure_reason = $4, duration_seconds = $5, mode = $6
	WHERE id = $7
`

const insertLoopEventSQL = `
	INSERT INTO loop_events (session_id, workspace, timestamp, loop_type, target, count, message)
	VALUES ($1, $2, $3, $4, $5, $6, $7)
`

const insertPromptSQL = `
	INSERT INTO user_prompts (session_id, workspace, turn_number, step_index, timestamp, prompt_text)
	VALUES ($1, $2, $3, $4, $5, $6)
`

func ConnectDB(ctx context.Context, connString string) (*DB, error) {
	config, err := pgxpool.ParseConfig(connString)
	if err != nil {
		return nil, fmt.Errorf("unable to parse connection string: %w", err)
	}

	config.MaxConns = 10
	config.MinConns = 2
	config.MaxConnLifetime = 1 * time.Hour

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("unable to connect to database: %w", err)
	}

	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("database ping failed: %w", err)
	}

	schemaSQL := `
		CREATE TABLE IF NOT EXISTS user_prompts (
			id BIGSERIAL PRIMARY KEY,
			session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
			workspace TEXT NOT NULL,
			turn_number INT NOT NULL,
			step_index INT NOT NULL,
			timestamp TIMESTAMPTZ NOT NULL,
			prompt_text TEXT NOT NULL
		);
		CREATE INDEX IF NOT EXISTS idx_user_prompts_session ON user_prompts(session_id, turn_number ASC);
		CREATE INDEX IF NOT EXISTS idx_user_prompts_workspace ON user_prompts(workspace);
		CREATE INDEX IF NOT EXISTS idx_user_prompts_timestamp ON user_prompts(timestamp DESC);
	`
	if _, err := pool.Exec(ctx, schemaSQL); err != nil {
		pool.Close()
		return nil, fmt.Errorf("schema migration failed: %w", err)
	}

	return &DB{pool: pool}, nil
}

func (db *DB) Close() {
	if db.pool != nil {
		db.pool.Close()
	}
}

// SyncSession synchronizes a TranscriptState with PostgreSQL.
// On the first pass for a session (or after file truncation), it performs an idempotent full sync in a single batch.
// On subsequent passes, it performs an append/update-only delta sync without deleting existing rows.
func (db *DB) SyncSession(ctx context.Context, st *TranscriptState) error {
	if !st.InitialSynced {
		return db.syncSessionInitial(ctx, st)
	}
	return db.syncSessionDelta(ctx, st)
}

func (db *DB) syncSessionInitial(ctx context.Context, st *TranscriptState) error {
	s := st.Meta
	tx, err := db.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	batch := &pgx.Batch{}
	batch.Queue(upsertSessionSQL,
		s.SessionID, s.ShortID, s.Workspace, s.FirstPrompt, s.StartTime, s.EndTime,
		s.DurationSeconds, s.TotalSteps, s.UserTurns, s.ModelTurns,
		s.TotalToolCalls, s.AutonomousCalls, s.ChatInitiatedCalls, s.ApprovedCalls, s.RejectedCalls, s.FailedCalls,
	)

	batch.Queue(`DELETE FROM tool_calls WHERE session_id = $1`, s.SessionID)
	for _, c := range s.ToolCalls {
		batch.Queue(insertToolCallReturningIDSQL,
			s.SessionID, s.Workspace, c.Timestamp, c.StepIndex, c.Tool, c.CommandBin, c.ToolAction,
			c.SanitizedCommand, c.ExitCode, c.IsFailed, c.FailureReason, c.DurationSeconds, c.Mode,
		)
	}

	batch.Queue(`DELETE FROM loop_events WHERE session_id = $1`, s.SessionID)
	for _, e := range s.LoopEvents {
		batch.Queue(insertLoopEventSQL, s.SessionID, s.Workspace, e.Timestamp, e.LoopType, e.Target, e.Count, e.Message)
	}

	batch.Queue(`DELETE FROM user_prompts WHERE session_id = $1`, s.SessionID)
	for _, p := range s.Prompts {
		batch.Queue(insertPromptSQL, s.SessionID, s.Workspace, p.TurnNumber, p.StepIndex, p.Timestamp, p.PromptText)
	}

	br := tx.SendBatch(ctx, batch)

	// 1. UpsertSession
	if _, err := br.Exec(); err != nil {
		br.Close()
		return fmt.Errorf("failed upserting session: %w", err)
	}

	// 2. DELETE tool_calls + INSERT tool_calls RETURNING id
	if _, err := br.Exec(); err != nil {
		br.Close()
		return fmt.Errorf("failed deleting tool calls: %w", err)
	}
	for i := range s.ToolCalls {
		var id int64
		if err := br.QueryRow().Scan(&id); err != nil {
			br.Close()
			return fmt.Errorf("failed inserting tool call %d: %w", i, err)
		}
		s.ToolCalls[i].DBID = id
	}

	// 3. DELETE loop_events + INSERT loop_events
	if _, err := br.Exec(); err != nil {
		br.Close()
		return fmt.Errorf("failed deleting loop events: %w", err)
	}
	for range s.LoopEvents {
		if _, err := br.Exec(); err != nil {
			br.Close()
			return fmt.Errorf("failed inserting loop event: %w", err)
		}
	}

	// 4. DELETE user_prompts + INSERT user_prompts
	if _, err := br.Exec(); err != nil {
		br.Close()
		return fmt.Errorf("failed deleting user prompts: %w", err)
	}
	for range s.Prompts {
		if _, err := br.Exec(); err != nil {
			br.Close()
			return fmt.Errorf("failed inserting user prompt: %w", err)
		}
	}

	if err := br.Close(); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}

	st.InitialSynced = true
	st.LastSyncedWorkspace = s.Workspace
	st.SyncedToolCalls = len(s.ToolCalls)
	st.SyncedLoopEvents = len(s.LoopEvents)
	st.SyncedPrompts = len(s.Prompts)
	clear(st.DirtyToolCallIdxs)
	return nil
}

func (db *DB) syncSessionDelta(ctx context.Context, st *TranscriptState) error {
	s := st.Meta

	// If any existing tool call lacking a DBID is dirty, fall back to a full initial sync
	var dirtyIdxs []int
	for idx := range st.DirtyToolCallIdxs {
		if idx < st.SyncedToolCalls {
			if s.ToolCalls[idx].DBID == 0 {
				st.InitialSynced = false
				return db.syncSessionInitial(ctx, st)
			}
			dirtyIdxs = append(dirtyIdxs, idx)
		}
	}
	sort.Ints(dirtyIdxs)

	tx, err := db.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	batch := &pgx.Batch{}
	execCount := 0

	// 1. Upsert session summary
	batch.Queue(upsertSessionSQL,
		s.SessionID, s.ShortID, s.Workspace, s.FirstPrompt, s.StartTime, s.EndTime,
		s.DurationSeconds, s.TotalSteps, s.UserTurns, s.ModelTurns,
		s.TotalToolCalls, s.AutonomousCalls, s.ChatInitiatedCalls, s.ApprovedCalls, s.RejectedCalls, s.FailedCalls,
	)
	execCount++

	// 2. Propagate workspace update if workspace transitioned from unknown to a known path
	if st.LastSyncedWorkspace != "" && st.LastSyncedWorkspace != s.Workspace {
		batch.Queue(`UPDATE tool_calls SET workspace = $1 WHERE session_id = $2`, s.Workspace, s.SessionID)
		batch.Queue(`UPDATE loop_events SET workspace = $1 WHERE session_id = $2`, s.Workspace, s.SessionID)
		batch.Queue(`UPDATE user_prompts SET workspace = $1 WHERE session_id = $2`, s.Workspace, s.SessionID)
		execCount += 3
	}

	// 3. Update existing tool calls modified by GENERIC completion or retroactive confirmation
	for _, idx := range dirtyIdxs {
		c := s.ToolCalls[idx]
		batch.Queue(updateToolCallByIDSQL,
			s.Workspace, c.ExitCode, c.IsFailed, c.FailureReason, c.DurationSeconds, c.Mode, c.DBID,
		)
		execCount++
	}

	// 4. Append newly parsed tool calls (RETURNING id)
	newToolsStart := st.SyncedToolCalls
	newTools := s.ToolCalls[newToolsStart:]
	for _, c := range newTools {
		batch.Queue(insertToolCallReturningIDSQL,
			s.SessionID, s.Workspace, c.Timestamp, c.StepIndex, c.Tool, c.CommandBin, c.ToolAction,
			c.SanitizedCommand, c.ExitCode, c.IsFailed, c.FailureReason, c.DurationSeconds, c.Mode,
		)
	}

	// 5. Append newly detected loop events
	newLoops := s.LoopEvents[st.SyncedLoopEvents:]
	for _, e := range newLoops {
		batch.Queue(insertLoopEventSQL, s.SessionID, s.Workspace, e.Timestamp, e.LoopType, e.Target, e.Count, e.Message)
	}

	// 6. Append newly parsed user prompts
	newPrompts := s.Prompts[st.SyncedPrompts:]
	for _, p := range newPrompts {
		batch.Queue(insertPromptSQL, s.SessionID, s.Workspace, p.TurnNumber, p.StepIndex, p.Timestamp, p.PromptText)
	}

	br := tx.SendBatch(ctx, batch)

	for i := 0; i < execCount; i++ {
		if _, err := br.Exec(); err != nil {
			br.Close()
			return fmt.Errorf("failed executing delta update statement %d: %w", i, err)
		}
	}

	for i := range newTools {
		var id int64
		if err := br.QueryRow().Scan(&id); err != nil {
			br.Close()
			return fmt.Errorf("failed inserting delta tool call %d: %w", i, err)
		}
		s.ToolCalls[newToolsStart+i].DBID = id
	}

	for range newLoops {
		if _, err := br.Exec(); err != nil {
			br.Close()
			return fmt.Errorf("failed inserting delta loop event: %w", err)
		}
	}

	for range newPrompts {
		if _, err := br.Exec(); err != nil {
			br.Close()
			return fmt.Errorf("failed inserting delta user prompt: %w", err)
		}
	}

	if err := br.Close(); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}

	st.LastSyncedWorkspace = s.Workspace
	st.SyncedToolCalls = len(s.ToolCalls)
	st.SyncedLoopEvents = len(s.LoopEvents)
	st.SyncedPrompts = len(s.Prompts)
	clear(st.DirtyToolCallIdxs)
	return nil
}

// UpsertSession inserts or updates a session summary record.
func (db *DB) UpsertSession(ctx context.Context, s *SessionMetadata) error {
	_, err := db.pool.Exec(ctx, upsertSessionSQL,
		s.SessionID, s.ShortID, s.Workspace, s.FirstPrompt, s.StartTime, s.EndTime,
		s.DurationSeconds, s.TotalSteps, s.UserTurns, s.ModelTurns,
		s.TotalToolCalls, s.AutonomousCalls, s.ChatInitiatedCalls, s.ApprovedCalls, s.RejectedCalls, s.FailedCalls,
	)
	return err
}

// SyncToolCalls replaces existing tool calls for a session with the full updated parsed state.
func (db *DB) SyncToolCalls(ctx context.Context, sessionID string, workspace string, calls []ToolCallRecord) error {
	tx, err := db.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, `DELETE FROM tool_calls WHERE session_id = $1`, sessionID); err != nil {
		return err
	}

	if len(calls) > 0 {
		batch := &pgx.Batch{}
		for _, c := range calls {
			batch.Queue(insertToolCallReturningIDSQL,
				sessionID, workspace, c.Timestamp, c.StepIndex, c.Tool, c.CommandBin, c.ToolAction,
				c.SanitizedCommand, c.ExitCode, c.IsFailed, c.FailureReason, c.DurationSeconds, c.Mode,
			)
		}

		br := tx.SendBatch(ctx, batch)
		for i := range calls {
			var id int64
			if err := br.QueryRow().Scan(&id); err != nil {
				br.Close()
				return fmt.Errorf("failed inserting tool call batch: %w", err)
			}
			calls[i].DBID = id
		}
		if err := br.Close(); err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}

// SyncLoopEvents replaces detected loop events for a session.
func (db *DB) SyncLoopEvents(ctx context.Context, sessionID string, workspace string, events []LoopEvent) error {
	tx, err := db.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, `DELETE FROM loop_events WHERE session_id = $1`, sessionID); err != nil {
		return err
	}

	if len(events) > 0 {
		batch := &pgx.Batch{}
		for _, e := range events {
			batch.Queue(insertLoopEventSQL, sessionID, workspace, e.Timestamp, e.LoopType, e.Target, e.Count, e.Message)
		}

		br := tx.SendBatch(ctx, batch)
		for range events {
			if _, err := br.Exec(); err != nil {
				br.Close()
				return fmt.Errorf("failed inserting loop event batch: %w", err)
			}
		}
		if err := br.Close(); err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}

// SyncPrompts replaces user prompts for a session with the full ordered prompt list.
func (db *DB) SyncPrompts(ctx context.Context, sessionID string, workspace string, prompts []PromptRecord) error {
	tx, err := db.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, `DELETE FROM user_prompts WHERE session_id = $1`, sessionID); err != nil {
		return err
	}

	if len(prompts) > 0 {
		batch := &pgx.Batch{}
		for _, p := range prompts {
			batch.Queue(insertPromptSQL, sessionID, workspace, p.TurnNumber, p.StepIndex, p.Timestamp, p.PromptText)
		}

		br := tx.SendBatch(ctx, batch)
		for range prompts {
			if _, err := br.Exec(); err != nil {
				br.Close()
				return fmt.Errorf("failed inserting user prompt batch: %w", err)
			}
		}
		if err := br.Close(); err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}
