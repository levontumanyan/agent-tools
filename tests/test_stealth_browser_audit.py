import collections
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser-audit"
_loader = importlib.machinery.SourceFileLoader("stealth_browser_audit", str(_SCRIPT_PATH))
_spec = importlib.util.spec_from_loader("stealth_browser_audit", _loader)
assert _spec is not None
sba = importlib.util.module_from_spec(_spec)
_loader.exec_module(sba)


def make_sess_state() -> dict:
	return {
		"calls": 0,
		"errors": 0,
		"schema_reads": 0,
		"chars": 0,
		"input_chars": 0,
		"schema_chars": 0,
		"overflows": 0,
		"shared_execute_outputs": 0,
		"domains": set(),
		"tools": collections.Counter(),
		"date": "",
		"prev_tool": None,
		"prev_errored": False,
		"prev_was_screenshot": False,
	}


def make_execute_item(call_id: str, nested: list[tuple[str, str, dict]], out_text: str, status: str = "completed", error: str | None = None) -> dict:
	return {
		"id": call_id,
		"name": "execute",
		"state": {
			"status": status,
			"input": {"code": 'return await tools["stealth-browser"].navigate({url: "https://example.com"});'},
			"content": [{"type": "text", "text": out_text}],
			"error": error,
			"metadata": {
				"toolCalls": [
					{"tool": f"stealth-browser.{tool}", "status": tc_status, "input": inp}
					for tool, tc_status, inp in nested
				]
			},
		},
	}


class TestClassifyOutcome:
	def test_wait_timed_out_classified(self):
		assert sba.classify_outcome("wait_for", "Wait timed out after 30000ms waiting for selector 'table'") == "wait_timeout"

	def test_wait_for_error_prefixes(self):
		assert sba.classify_outcome("wait_for", "error in wait_for: boom") == "tool_error"
		assert sba.classify_outcome("extract", "error extracting rows: boom") == "tool_error"
		assert sba.classify_outcome("downloads", "error listing downloads: boom") == "tool_error"
		assert sba.classify_outcome("network_requests", "error listing network requests: boom") == "tool_error"
		assert sba.classify_outcome("console_logs", "error listing console logs: boom") == "tool_error"
		assert sba.classify_outcome("wait_for_human", "error during human handoff: boom") == "tool_error"

	def test_wrapped_json_error_miss(self):
		wrapped = '{"result":"Error clicking element \'#x\': Locator.click: Timeout 10000ms exceeded."}'
		assert sba.classify_outcome("click", wrapped) is None
		assert sba.classify_outcome("click", sba.unwrap_result_json(wrapped)) == "click_error"


class TestParseValidationSignature:
	def test_wrapped_json_validation_error(self):
		wrapped = '{"result":"1 validation error for navigateArgs\\nurl\\n  Field required [type=missing]"}'
		assert sba.classify_outcome("navigate", sba.unwrap_result_json(wrapped)) == "validation_error"
		sig = sba.parse_validation_signature("navigate", sba.unwrap_result_json(wrapped), {"timeout_ms": 5000})
		assert "field 'url'" in sig
		assert "passed: timeout_ms" in sig

	def test_pretty_printed_result_json_unwraps(self):
		pretty = '{\n  "result": "Wait timed out after 30000ms waiting for selector \'table\'"\n}'
		assert sba.unwrap_result_json(pretty) == "Wait timed out after 30000ms waiting for selector 'table'"


class TestUnwrapResultJson:
	def test_unwraps_string_result(self):
		assert sba.unwrap_result_json('{"result":"Wait timed out after 30000ms"}') == "Wait timed out after 30000ms"

	def test_leaves_plain_body_untouched(self):
		assert sba.unwrap_result_json("Clicked element e5 on https://example.com") == "Clicked element e5 on https://example.com"

	def test_leaves_non_result_json_untouched(self):
		body = '{"type":"aborted","message":"Tool execution interrupted"}'
		assert sba.unwrap_result_json(body) == body

	def test_leaves_dict_result_untouched(self):
		body = '{"result":{"rows":[1,2]}}'
		assert sba.unwrap_result_json(body) == body


class TestSilentParamMismatch:
	def test_stale_tab_vs_index_rule_retired(self):
		assert sba.detect_silent_param_mismatch("close_tab", {"tab": "t4"}) is None
		assert sba.detect_silent_param_mismatch("switch_tab", {"tab": 0}) is None

	def test_tab_index_still_flagged(self):
		msg = sba.detect_silent_param_mismatch("close_tab", {"tab_index": 2})
		assert msg is not None and "tab_index" in msg


class TestKnownTools:
	def test_new_tools_listed(self):
		for tool in ("extract", "wait_for", "wait_for_human", "downloads", "network_requests", "console_logs"):
			assert tool in sba.KNOWN_TOOLS


class TestAgyOverflow:
	def test_expand_overflow_reads_saved_file(self, tmp_path, monkeypatch):
		monkeypatch.setattr(sba, "BRAIN_DIR", tmp_path)
		out_file = tmp_path / "steps" / "24" / "output.txt"
		out_file.parent.mkdir(parents=True)
		out_file.write_text("S" * 15591, encoding="utf-8")
		stub = f"The output was large and was saved to: file://{out_file}"
		body, overflowed = sba.expand_agy_overflow(stub)
		assert overflowed is True
		assert len(body) == 15591

	def test_expand_overflow_truncated_variant_with_trailing_prose(self, tmp_path, monkeypatch):
		monkeypatch.setattr(sba, "BRAIN_DIR", tmp_path)
		out_file = tmp_path / "steps" / "10" / "output.txt"
		out_file.parent.mkdir(parents=True)
		out_file.write_text("full content here", encoding="utf-8")
		stub = (
			f"The tool's output was truncated due to being too long. "
			f"You can find the full output in a file at file://{out_file}."
			"\n\nHere is a preview of the output:"
		)
		body, overflowed = sba.expand_agy_overflow(stub)
		assert overflowed is True
		assert body == "full content here"

	def test_overflow_path_outside_brain_dir_rejected(self, tmp_path, monkeypatch):
		monkeypatch.setattr(sba, "BRAIN_DIR", tmp_path / "brain")
		(tmp_path / "brain").mkdir()
		out_file = tmp_path / "outside" / "secret.txt"
		out_file.parent.mkdir(parents=True)
		out_file.write_text("should not be read", encoding="utf-8")
		stub = f"The output was large and was saved to: file://{out_file}"
		body, overflowed = sba.expand_agy_overflow(stub)
		assert overflowed is False
		assert body == stub

	def test_empty_overflow_file_keeps_stub(self, tmp_path, monkeypatch):
		monkeypatch.setattr(sba, "BRAIN_DIR", tmp_path)
		out_file = tmp_path / "steps" / "1" / "output.txt"
		out_file.parent.mkdir(parents=True)
		out_file.write_text("", encoding="utf-8")
		stub = f"The output was large and was saved to: file://{out_file}"
		body, overflowed = sba.expand_agy_overflow(stub)
		assert overflowed is False
		assert body == stub

	def test_missing_file_keeps_stub(self, tmp_path, monkeypatch):
		monkeypatch.setattr(sba, "BRAIN_DIR", tmp_path)
		stub = f"The output was large and was saved to: file://{tmp_path}/missing/output.txt"
		body, overflowed = sba.expand_agy_overflow(stub)
		assert overflowed is False
		assert body == stub

	def test_plain_body_untouched(self):
		body, overflowed = sba.expand_agy_overflow("Clicked element e5 on https://example.com")
		assert overflowed is False
		assert body == "Clicked element e5 on https://example.com"


class TestNestedCharAttribution:
	def _collector(self) -> sba.AuditCollector:
		return sba.AuditCollector(since=None, includes=[], excludes=[], slow_threshold=20.0, max_samples=2)

	def test_single_nested_call_gets_full_output(self):
		c = self._collector()
		sess = make_sess_state()
		body = "R" * 1000
		item = make_execute_item("c1", [("navigate", "completed", {"url": "https://example.com"})], body)
		c._record_nested_calls("s1", "t", "execute", 'await tools["stealth-browser"].navigate({});', item, None, None, sess)
		assert sess["calls"] == 1
		assert sess["chars"] == len(body)
		assert c.call_chars["navigate"] == [len(body)]
		assert sess["shared_execute_outputs"] == 0

	def test_multi_nested_call_counts_execute_output_once(self):
		c = self._collector()
		sess = make_sess_state()
		body = "R" * 1001
		item = make_execute_item(
			"c2",
			[
				("navigate", "completed", {"url": "https://example.com"}),
				("get_content", "completed", {"selector": "body"}),
			],
			body,
		)
		c._record_nested_calls("s1", "t", "execute", 'await tools["stealth-browser"].navigate({});', item, None, None, sess)
		assert sess["calls"] == 2
		assert sess["chars"] == len(body)
		assert sum(c.call_chars["navigate"]) + sum(c.call_chars["get_content"]) == len(body)
		assert max(abs(x - len(body) // 2) for x in c.call_chars["navigate"] + c.call_chars["get_content"]) <= 1
		assert sess["shared_execute_outputs"] == 1


class TestNestedErrorAttribution:
	def _collector(self) -> sba.AuditCollector:
		return sba.AuditCollector(since=None, includes=[], excludes=[], slow_threshold=20.0, max_samples=4)

	def test_wrapped_error_attributed_once_to_last_call(self):
		c = self._collector()
		sess = make_sess_state()
		wrapped = '{"result":"Wait timed out after 30000ms waiting for selector \'table\'"}'
		item = make_execute_item(
			"c3",
			[
				("navigate", "completed", {"url": "https://example.com"}),
				("wait_for", "completed", {"selector": "table"}),
			],
			wrapped,
		)
		c._record_nested_calls("s1", "t", "execute", 'await tools["stealth-browser"].navigate({});', item, None, None, sess)
		assert c.error_counts["wait_timeout"] == 1
		assert c.tool_errors["wait_for"]["wait_timeout"] == 1
		assert sum(c.tool_errors["navigate"].values()) == 0
		assert sess["errors"] == 1

	def test_wrapped_click_error_single_call(self):
		c = self._collector()
		sess = make_sess_state()
		wrapped = '{"result":"Error clicking element \'#radix-_r_5_\': Locator.click: Timeout 10000ms exceeded."}'
		item = make_execute_item("c4", [("click", "completed", {"selector": "#radix-_r_5_"})], wrapped)
		c._record_nested_calls("s1", "t", "execute", 'await tools["stealth-browser"].navigate({});', item, None, None, sess)
		assert c.error_counts["click_error"] == 1

	def test_execute_level_error_not_spread_to_earlier_calls(self):
		c = self._collector()
		sess = make_sess_state()
		item = make_execute_item(
			"c5",
			[
				("navigate", "completed", {"url": "https://example.com"}),
				("snapshot", "completed", {}),
			],
			"ok output",
			status="error",
		)
		item["state"]["error"] = "execute timed out"
		c._record_nested_calls("s1", "t", "execute", 'await tools["stealth-browser"].navigate({});', item, None, None, sess)
		assert sum(c.tool_errors["navigate"].values()) == 0
		assert sum(c.tool_errors["snapshot"].values()) == 1

	def test_earlier_errored_call_not_doubled_on_last(self):
		c = self._collector()
		sess = make_sess_state()
		item = make_execute_item(
			"c7",
			[
				("click", "error", {"selector": "#x"}),
				("get_content", "completed", {"selector": "body"}),
			],
			'{"result":"Content of body ..."}',
			error="execute failed: click step returned error",
		)
		c._record_nested_calls("s1", "t", "execute", 'await tools["stealth-browser"].click({});', item, None, None, sess)
		assert sess["errors"] == 1
		assert sum(c.tool_errors["click"].values()) == 1
		assert sum(c.tool_errors["get_content"].values()) == 0
		assert c.error_counts.get("other_error", 0) == 1

	def test_per_call_status_error_respected(self):
		c = self._collector()
		sess = make_sess_state()
		item = make_execute_item(
			"c6",
			[
				("navigate", "completed", {"url": "https://example.com"}),
				("click", "error", {"selector": "#x"}),
				("snapshot", "completed", {}),
			],
			"ok output",
		)
		c._record_nested_calls("s1", "t", "execute", 'await tools["stealth-browser"].navigate({});', item, None, None, sess)
		assert sum(c.tool_errors["click"].values()) == 1
		assert sum(c.tool_errors["navigate"].values()) == 0
		assert sum(c.tool_errors["snapshot"].values()) == 0


class TestComputeDiff:
	def _baseline(self, legacy: bool) -> dict:
		snapshot = {
			"generated_at": "2026-11-20T00:00:00+00:00",
			"filters": {"since": None},
			"summary": {
				"sessions": 2,
				"total_calls": 100,
				"schema_reads_per_session": 2.0,
				"schema_reads_in_browser_sessions": 4,
				"mcp_timeouts_3m": 0,
				"slow_non_timeout_calls": 0,
				"validation_errors_total": 0,
				"silent_param_mismatches_total": 0,
			},
			"tools": {},
			"evaluate_js": {"total": 0, "intents": {}},
		}
		if not legacy:
			snapshot["summary"]["schema_reads_per_agy_session"] = 4.0
			snapshot["summary"]["sessions_by_source"] = {"agy": 1, "opencode": 1}
		else:
			snapshot["summary"]["sessions_by_source"] = {"agy": 1, "opencode": 1}
		return snapshot

	def test_agy_rate_from_explicit_baseline(self):
		diff = sba.compute_diff(self._baseline(legacy=False), self._baseline(legacy=False))
		row = next(k for k in diff["kpis"] if k["metric"] == "Schema reads / AGY session")
		assert row["before"] == 4.0 and row["after"] == 4.0 and row["delta"] == 0.0

	def test_agy_rate_derived_from_legacy_baseline(self):
		legacy = self._baseline(legacy=True)
		del legacy["summary"]["schema_reads_per_session"]
		diff = sba.compute_diff(legacy, self._baseline(legacy=False))
		row = next(k for k in diff["kpis"] if k["metric"] == "Schema reads / AGY session")
		assert row["before"] == 4.0

	def test_schema_read_regression_flagged(self):
		current = self._baseline(legacy=False)
		current["summary"]["schema_reads_per_agy_session"] = 8.0
		diff = sba.compute_diff(self._baseline(legacy=False), current)
		row = next(k for k in diff["kpis"] if k["metric"] == "Schema reads / AGY session")
		assert row["delta"] == 4.0 and row["status"] == "regressed"

	def test_schema_read_improvement_flagged(self):
		current = self._baseline(legacy=False)
		current["summary"]["schema_reads_per_agy_session"] = 1.0
		diff = sba.compute_diff(self._baseline(legacy=False), current)
		row = next(k for k in diff["kpis"] if k["metric"] == "Schema reads / AGY session")
		assert row["delta"] == -3.0 and row["status"] == "improved"


class TestInputCharTracking:
	def test_record_call_tracks_input_chars(self):
		c = sba.AuditCollector(since=None, includes=[], excludes=[], slow_threshold=20.0, max_samples=2)
		sess = make_sess_state()
		raw_args = {"expression": "document.title"}
		c._record_call(
			source="opencode",
			sid="s1",
			title="t",
			tool="evaluate_js",
			raw_args=raw_args,
			body="ok",
			explicit_error=False,
			duration_s=0.5,
			sess_state=sess,
			nested=True,
		)
		expected = len(json.dumps(raw_args))
		assert sess["input_chars"] == expected
		assert c.call_input_chars["evaluate_js"] == [expected]


@pytest.fixture()
def agy_env(tmp_path, monkeypatch):
	monkeypatch.setattr(sba, "BRAIN_DIR", tmp_path)
	monkeypatch.setattr(sba, "SUMMARY_DB", tmp_path / "missing.db")
	return tmp_path


def _write_agy_session(root: Path, cid: str, compact_output: str, full_output: str, overflow_file: Path | None = None, schema_reads: int = 0) -> None:
	log_dir = root / cid / ".system_generated" / "logs"
	log_dir.mkdir(parents=True)
	if overflow_file is not None:
		overflow_file.parent.mkdir(parents=True, exist_ok=True)
		overflow_file.write_text(full_output, encoding="utf-8")
		full_output = f"The output was large and was saved to: file://{overflow_file}."
	args = {"ServerName": "stealth-browser", "ToolName": "snapshot", "Arguments": {"max_elements": 80}}
	tool_calls = [
		{"name": "read_file", "args": {"Path": "/mcp/stealth-browser/navigate.json"}, "created_at": "2026-11-20T09:59:00Z"}
		for _ in range(schema_reads)
	]
	tool_calls.append({"name": "call_mcp_tool", "args": args, "created_at": "2026-11-20T10:00:00Z"})
	schema_generic = [
		json.dumps({"type": "GENERIC", "content": 'Created At: 2026-11-20T09:59:05Z\n{"name":"navigate"} schema body'})
		for _ in range(schema_reads)
	]
	full_lines = [
		json.dumps({"tool_calls": tool_calls}),
		*schema_generic,
		json.dumps({"type": "GENERIC", "content": f"Created At: 2026-11-20T10:00:05Z\nCompleted At: 2026-11-20T10:00:06Z\n{full_output}"}),
		json.dumps({"type": "PLANNER_RESPONSE", "content": "done"}),
	]
	(log_dir / "transcript_full.jsonl").write_text("\n".join(full_lines), encoding="utf-8")
	compact_lines = [
		json.dumps({"tool_calls": tool_calls}),
		*schema_generic,
		json.dumps({"type": "GENERIC", "content": f"Created At: 2026-11-20T10:00:05Z\nCompleted At: 2026-11-20T10:00:06Z\n{compact_output}"}),
		json.dumps({"type": "PLANNER_RESPONSE", "content": "done"}),
	]
	(log_dir / "transcript.jsonl").write_text("\n".join(compact_lines), encoding="utf-8")


class TestCollectAgy:
	def test_prefers_transcript_full_and_expands_overflow(self, agy_env):
		overflow = agy_env / "overflow.txt"
		full_output = "F" * 15591
		compact_output = "C" * 4000
		_write_agy_session(agy_env, "cid-full-1111", compact_output, full_output, overflow_file=overflow)

		collector = sba.AuditCollector(since=None, includes=["cid-full-1111"], excludes=[], slow_threshold=20.0, max_samples=2)
		collector.collect_agy()
		assert collector.tool_counts["snapshot"] == 1
		assert collector.sessions[0]["chars"] == len(full_output)
		assert collector.sessions[0]["overflows"] == 1
		assert collector.agy_overflow_expansions == 1
		assert collector.build_snapshot(None, "all")["summary"]["agy_output_overflows"] == 1

	def test_falls_back_to_compact_transcript(self, agy_env):
		compact_output = "C" * 4000
		full_output = "F" * 9000
		_write_agy_session(agy_env, "cid-compact-22", compact_output, full_output)
		(agy_env / "cid-compact-22" / ".system_generated" / "logs" / "transcript_full.jsonl").unlink()

		collector = sba.AuditCollector(since=None, includes=["cid-compact-22"], excludes=[], slow_threshold=20.0, max_samples=2)
		collector.collect_agy()
		assert collector.sessions[0]["chars"] == len(compact_output)
		assert collector.sessions[0]["overflows"] == 0

	def test_schema_read_chars_counted(self, agy_env):
		log_dir = agy_env / "cid-schema-33" / ".system_generated" / "logs"
		log_dir.mkdir(parents=True)
		schema_body = '{"name":"navigate","inputSchema":{}}' + "x" * 500
		navigate_out = "Navigated to https://example.com"
		lines = [
			json.dumps({"tool_calls": [
				{"name": "read_file", "args": {"Path": "/mcp/stealth-browser/navigate.json"}, "created_at": "2026-11-20T10:00:00Z"},
				{"name": "call_mcp_tool", "args": {"ServerName": "stealth-browser", "ToolName": "navigate", "Arguments": {"url": "https://example.com"}}, "created_at": "2026-11-20T10:00:01Z"},
			]}),
			json.dumps({"type": "GENERIC", "content": f"Created At: 2026-11-20T10:00:05Z\n{schema_body}"}),
			json.dumps({"type": "GENERIC", "content": f"Created At: 2026-11-20T10:00:06Z\n{navigate_out}"}),
			json.dumps({"type": "PLANNER_RESPONSE", "content": "done"}),
		]
		(log_dir / "transcript.jsonl").write_text("\n".join(lines), encoding="utf-8")

		collector = sba.AuditCollector(since=None, includes=["cid-schema-33"], excludes=[], slow_threshold=20.0, max_samples=2)
		collector.collect_agy()
		assert collector.sessions[0]["schema_reads"] == 1
		assert collector.sessions[0]["schema_chars"] == len(schema_body)
		assert collector.tool_counts["navigate"] == 1
		snap = collector.build_snapshot(None, "all")
		assert snap["summary"]["schema_read_chars"] == len(schema_body)


class TestSnapshotSummary:
	def test_schema_reads_per_agy_session_uses_agy_denominator(self, agy_env):
		_write_agy_session(agy_env, "cid-agy-4444", "out", "out", schema_reads=4)
		collector = sba.AuditCollector(since=None, includes=["cid-agy-4444"], excludes=[], slow_threshold=20.0, max_samples=2)
		collector.collect_agy()

		oc_sess = make_sess_state()
		oc_sess["calls"] = 1
		oc_sess["chars"] = 10
		oc_sess["tools"]["click"] = 1
		oc_sess["date"] = "2026-11-20"
		collector._finalize_session("opencode", "ses_oc_5555", "t", oc_sess, "")

		snap = collector.build_snapshot(None, "all")
		assert snap["summary"]["sessions"] == 2
		assert snap["summary"]["sessions_by_source"] == {"agy": 1, "opencode": 1}
		assert snap["summary"]["schema_reads_total"] == 4
		assert snap["summary"]["schema_reads_per_session"] == 2.0
		assert snap["summary"]["schema_reads_per_agy_session"] == 4.0

	def test_schema_reads_per_agy_session_excludes_opencode_reads(self, agy_env):
		_write_agy_session(agy_env, "cid-agy-6666", "out", "out", schema_reads=2)
		collector = sba.AuditCollector(since=None, includes=["cid-agy-6666"], excludes=[], slow_threshold=20.0, max_samples=2)
		collector.collect_agy()

		oc_sess = make_sess_state()
		oc_sess["calls"] = 1
		oc_sess["chars"] = 10
		oc_sess["schema_reads"] = 3
		oc_sess["schema_chars"] = 300
		oc_sess["tools"]["click"] = 1
		oc_sess["date"] = "2026-11-20"
		collector._finalize_session("opencode", "ses_oc_7777", "t", oc_sess, "")

		snap = collector.build_snapshot(None, "all")
		assert snap["summary"]["schema_reads_total"] == 5
		assert snap["summary"]["schema_reads_per_session"] == 2.5
		assert snap["summary"]["schema_reads_per_agy_session"] == 2.0
