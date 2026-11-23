import importlib.machinery
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

SHIPPER = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser-shipper"


def load_shipper():
	loader = importlib.machinery.SourceFileLoader("stealth_browser_shipper", str(SHIPPER))
	spec = importlib.util.spec_from_loader("stealth_browser_shipper", loader)
	module = importlib.util.module_from_spec(spec)
	loader.exec_module(module)
	return module


@pytest.fixture(scope="module")
def ship():
	return load_shipper()


def test_redact_secrets(ship):
	assert ship.redact("Bearer abc-DEF123._~+/") == "Bearer [REDACTED]"
	assert "[REDACTED]" in ship.redact("Authorization: Basic dXNlcjpwYXNz")
	assert "[REDACTED]" in ship.redact("key sk-proj-abcdefghijklmnopqrst1234")
	assert "[REDACTED]" in ship.redact("https://user:hunter2@example.com/x")
	assert "[REDACTED]" in ship.redact('{"password": "hunter2"}')
	assert "[REDACTED]" in ship.redact("api_key=abc123def456")
	assert "[REDACTED]" in ship.redact("xoxb-123456789012-abc")
	assert "[REDACTED]" in ship.redact("ghp_abcdefghijklmnopqrst")
	assert "[REDACTED]" in ship.redact("AKIAIOSFODNN7EXAMPLE")
	jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
	assert "[REDACTED]" in ship.redact(f"token {jwt}")
	assert ship.redact("plain selector text") == "plain selector text"


def test_redact_truncation_bounds(ship):
	long_arg = json.dumps({"selector": "x" * 500})
	row = ship.call_row("stealth-browser", {}, {
		"source": "agy", "session_id": "s", "call_seq": 0, "called_at": None,
		"tool": "click", "outcome": "", "is_error": False, "is_soft": False,
		"error_detail": "", "js_intent": "", "domain": "",
		"output_chars": 1, "input_chars": 1, "is_overflow": False,
		"snapshot_rows": 0, "duration_s": None, "is_approval_wait": False,
		"nested": False, "args_preview": long_arg, "error_preview": "e" * 500,
	})
	args_idx = -2
	assert len(row[args_idx]) <= 140
	assert len(row[-1]) <= 220


def test_dirty_agy_detects_change(ship, tmp_path):
	brain = tmp_path / "brain" / "abc123" / ".system_generated" / "logs"
	brain.mkdir(parents=True)
	full = brain / "transcript_full.jsonl"
	full.write_bytes(b"x" * 10)
	old_brain = ship.BRAIN_DIR
	ship.BRAIN_DIR = tmp_path / "brain"
	try:
		dirty, seen = ship.dirty_agy_sessions({})
		assert "abc123" in dirty and "abc123" in seen
		dirty2, _ = ship.dirty_agy_sessions({"agy": {"abc123": seen["abc123"]}})
		assert dirty2 == []
		full.write_bytes(b"x" * 20)
		dirty3, _ = ship.dirty_agy_sessions({"agy": {"abc123": seen["abc123"]}})
		assert dirty3 == ["abc123"]
	finally:
		ship.BRAIN_DIR = old_brain


def test_session_row_fallback_and_fields(ship, tmp_path):
	audit = load_shipper().load_audit_module()
	sess = {
		"source": "agy", "sid": "deadbeef-1234", "title": "My Bank Login 2FA",
		"calls": 3, "errors": 1, "chars": 1000, "input_chars": 100,
		"schema_reads": 2, "schema_chars": 400, "overflows": 1,
		"date": "2026-11-22", "domains": ["example.com"],
		"top_tools": [("click", 2), ("screenshot", 1)],
		"snapshot_calls": 1, "snapshot_chars": 900, "snapshot_rows": 10,
		"is_subagent": False, "first_call_at": None, "last_call_at": None,
	}
	calls = [
		{"outcome": "click_error", "is_soft": False, "is_error": True, "duration_s": 5.0, "tool": "click", "is_approval_wait": False},
		{"outcome": "click_error", "is_soft": False, "is_error": True, "duration_s": 30.0, "tool": "click", "is_approval_wait": False},
		{"outcome": "set_headless_refused", "is_soft": True, "is_error": False, "duration_s": None, "tool": "set_headless", "is_approval_wait": False},
	]
	row = ship.session_row("stealth-browser", sess, calls, audit)
	assert row != ()
	assert row[7] == row[6]
	assert row[10] == 1
	assert row[13] == 1
	assert row[15] == 2
	assert row[20] == 1 and row[22] == 10
	assert row[26] is True
	assert "example.com" in row[27]


def test_session_row_skips_untimed(ship):
	sess = {"source": "agy", "sid": "x", "calls": 2, "date": "", "first_call_at": None}
	assert ship.session_row("stealth-browser", sess, [], mock.Mock()) == ()


def test_schema_sql_is_idempotent(ship):
	assert ship.SCHEMA_SQL.count("CREATE TABLE IF NOT EXISTS") == 2
	assert "PRIMARY KEY (server, source, session_id)" in ship.SCHEMA_SQL
