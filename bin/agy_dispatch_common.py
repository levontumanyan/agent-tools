#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Shared SQLite, path validation, and config helpers for agy-mcp-server and agy-task-runner.
"""

from contextlib import contextmanager
import datetime
import os
import re
import sqlite3
from typing import Iterator

REPOS_BASE = os.path.expanduser("~/repos")
LOGS_BASE = os.path.expanduser("~/logs/agy-tasks")
WORKTREES_BASE = os.path.expanduser("~/.local/share/agy-dispatch/worktrees")
TMP_BASE = os.path.expanduser("~/.local/share/agy-dispatch/tmp")
DEFAULT_DB_PATH = os.path.expanduser("~/.local/share/agy-dispatch/state.db")
TMUX_BIN = os.environ.get("TMUX_BIN", "/home/linuxbrew/.linuxbrew/bin/tmux")

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9_./-]{1,128}$")


def utc_now_iso() -> str:
	"""Return current UTC timestamp in ISO-8601 format."""
	return datetime.datetime.now(datetime.timezone.utc).isoformat()


def validate_safe_id(value: str, field_name: str = "id") -> str:
	"""Ensure identifier contains only safe characters and no path/tmux metacharacters."""
	if not value or not SAFE_ID_RE.match(value):
		raise ValueError(f"Invalid {field_name}: must match {SAFE_ID_RE.pattern}")
	return value


def validate_branch_name(value: str) -> str:
	"""Validate git branch name against unsafe flags or path traversal."""
	if not value or ".." in value or not SAFE_BRANCH_RE.match(value):
		raise ValueError(f"Invalid branch name: {value!r}")
	return value


def resolve_repo_path(repo_arg: str) -> str:
	"""Resolve repository strictly inside REPOS_BASE, preventing path traversal."""
	if not repo_arg or os.path.isabs(repo_arg):
		raise ValueError(f"Repository must be a relative name under {REPOS_BASE}: {repo_arg!r}")
	real_base = os.path.realpath(REPOS_BASE)
	real_target = os.path.realpath(os.path.join(real_base, repo_arg))
	if real_target == real_base or os.path.commonpath([real_base, real_target]) != real_base:
		raise ValueError(f"Repository path escapes {REPOS_BASE}: {repo_arg!r}")
	if not os.path.isdir(real_target):
		raise ValueError(f"Repository not found: {repo_arg}")
	return real_target


def ensure_private_dirs() -> None:
	"""Create private runtime directories with owner-only permissions."""
	for path in (os.path.dirname(get_db_path()), WORKTREES_BASE, TMP_BASE, LOGS_BASE):
		os.makedirs(path, mode=0o700, exist_ok=True)


def get_db_path() -> str:
	"""Return SQLite database path."""
	return os.environ.get("AGY_DISPATCH_DB", DEFAULT_DB_PATH)


def init_db() -> None:
	"""Initialize SQLite WAL mode, schema tables, and indexes once at startup."""
	ensure_private_dirs()
	conn = sqlite3.connect(get_db_path(), timeout=15.0)
	try:
		conn.execute("PRAGMA journal_mode=WAL;")
		conn.execute("PRAGMA busy_timeout=10000;")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS tasks (
				task_id TEXT PRIMARY KEY,
				run_id TEXT,
				worker_name TEXT,
				repo TEXT NOT NULL,
				base_branch TEXT NOT NULL DEFAULT 'main',
				branch TEXT,
				worktree_dir TEXT,
				tmux_session TEXT,
				prompt TEXT NOT NULL,
				mode TEXT NOT NULL DEFAULT 'autonomous',
				status TEXT NOT NULL,
				conversation_id TEXT,
				pr_url TEXT,
				evidence_receipt TEXT,
				summary TEXT,
				report_md TEXT,
				error_log TEXT,
				started_at TEXT NOT NULL,
				completed_at TEXT,
				duration_seconds REAL
			);
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS agent_messages (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				run_id TEXT,
				from_agent TEXT NOT NULL,
				to_agent TEXT NOT NULL,
				body TEXT NOT NULL,
				created_at TEXT NOT NULL
			);
		""")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_run_started ON tasks(run_id, started_at DESC);")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_worker ON tasks(worker_name);")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_msgs_to_id ON agent_messages(to_agent, id);")
		conn.commit()
	finally:
		conn.close()


@contextmanager
def get_db_conn() -> Iterator[sqlite3.Connection]:
	"""Yield a SQLite connection with row_factory and guarantee commit/close."""
	conn = sqlite3.connect(get_db_path(), timeout=15.0)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA busy_timeout=10000;")
	try:
		yield conn
		conn.commit()
	except Exception:
		conn.rollback()
		raise
	finally:
		conn.close()
