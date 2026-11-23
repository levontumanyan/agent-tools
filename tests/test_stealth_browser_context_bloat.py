import asyncio
import importlib.machinery
import importlib.util
import json
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser"


def _load_sb():
	loader = importlib.machinery.SourceFileLoader("stealth_browser_bloat_mod", str(SCRIPT_PATH))
	spec = importlib.util.spec_from_loader(loader.name, loader)
	mod = importlib.util.module_from_spec(spec)
	loader.exec_module(mod)
	return mod


@pytest.fixture(scope="module")
def sb():
	return _load_sb()


class FakeLocator:
	def __init__(self, count: int = 1, text: str = ""):
		self._count = count
		self._text = text
		self.first = self
		self.click = AsyncMock()
		self.fill = AsyncMock()
		self.type = AsyncMock()
		self.press = AsyncMock()

	async def count(self) -> int:
		return self._count

	async def inner_text(self) -> str:
		return self._text


class FakePage:
	def __init__(self, url: str = "https://portal.example/page", locator_map=None):
		self.url = url
		self._closed = False
		self.main_frame = self
		self.frames = [self]
		self._locators = locator_map or {}
		self.evaluate = AsyncMock(return_value="")
		self.keyboard = MagicMock()
		self.keyboard.press = AsyncMock()
		self._dialog_history = deque(maxlen=50)

	def is_closed(self) -> bool:
		return self._closed

	def on(self, event: str, cb) -> None:
		pass

	def locator(self, selector: str) -> FakeLocator:
		return self._locators.get(selector, FakeLocator(count=1))


def test_instructions_cover_all_registered_tools_and_key_params(sb):
	tools = asyncio.run(sb.mcp.list_tools())
	tool_names = {t.name for t in tools}
	instr = sb.mcp.instructions

	for name in tool_names:
		assert f"{name}(" in instr, f"Tool '{name}' missing from FastMCP instructions"

	for token in (
		"wait_for_human(",
		"downloads(",
		"network_requests(",
		"console_logs(",
		"include_hrefs=",
		"viewport_only=",
		"filter=",
		"offset=",
		"save_path=",
		"annotate=",
		"force=",
		"ref=",
	):
		assert token in instr, f"Missing '{token}' in instructions"

	total_schema_bytes = sum(len(json.dumps(t.model_dump())) for t in tools)
	assert total_schema_bytes < 24000, f"Schemas still bloated: {total_schema_bytes}B"


def test_snapshot_compact_cap_and_total_matched(sb, monkeypatch):
	items = [
		{
			"index": i,
			"ref": f"e{i}",
			"tag": "a",
			"selector": f'[data-sb-ref="e{i}"]',
			"text": f"Account link number {i} with some descriptive label",
			"href": f"/account/item/{i}",
			"attrs": "",
		}
		for i in range(60)
	]
	page = FakePage()
	page.evaluate = AsyncMock(return_value={"totalMatched": 95, "items": items})
	monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

	out = asyncio.run(sb.snapshot(max_elements=60, max_length=1200))
	assert len(out) <= 1300
	assert "showing " in out and "of 95 items" in out
	assert "narrow with selector=" in out
	assert "[data-sb-ref=" not in out
	assert "href=" not in out

	out_filtered = asyncio.run(sb.snapshot(filter="statement", viewport_only=True, include_hrefs=True))
	_, payload = page.evaluate.call_args.args
	assert payload["filter"] == "statement"
	assert payload["viewportOnly"] is True
	assert payload["includeHrefs"] is True
	assert "href=/account/item/0" in out_filtered

	page_long_url = FakePage(url="https://portal.example/auth?" + "p=" + "z" * 600)
	page_long_url.evaluate = AsyncMock(return_value={"totalMatched": 800, "totalCapped": True, "items": items})
	monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page_long_url))
	out_capped = asyncio.run(sb.snapshot(max_length=1200))
	assert "of 800+ items" in out_capped
	assert len(out_capped) <= 1250
	assert "z" * 200 not in out_capped


def test_snapshot_deduplicates_selector_and_omits_bare_tag(sb):
	row_id = sb._format_snapshot_row(
		{"ref": "e0", "tag": "button", "selector": "#save", "text": "Save", "attrs": "#save type=submit"},
		0,
	)
	assert row_id == '[e0] <button> #save "Save" (type=submit)'

	row_bare = sb._format_snapshot_row(
		{"ref": "e1", "tag": "button", "selector": "button", "text": "Only"},
		1,
	)
	assert row_bare == '[e1] <button> "Only"'


def test_get_content_clean_whitespace_offset_tail_and_filter(sb, monkeypatch):
	messy = "Header   Line\n\n\n\nPrice:     $42.00\nNotes:   quiet room\nFooter:   end of page"
	page = FakePage(locator_map={"body": FakeLocator(count=1, text=messy)})
	page.evaluate = AsyncMock(return_value=messy)
	monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

	assert "cloneNode" not in sb._GET_CONTENT_CLEAN_JS
	assert "getComputedStyle" in sb._GET_CONTENT_CLEAN_JS

	out = asyncio.run(sb.get_content(clean=True))
	assert "   " not in out
	assert "\n\n\n" not in out
	assert "Price: $42.00" in out

	tail = asyncio.run(sb.get_content(offset=-19, max_length=4000))
	assert tail.startswith("[Showing chars ")
	assert "Footer: end of page" in tail
	assert "Header Line" not in tail

	paged = asyncio.run(sb.get_content(offset=0, max_length=20))
	assert "pass offset=20 for next chunk" in paged

	filtered = asyncio.run(sb.get_content(filter=r"\$42"))
	assert "Price: $42.00" in filtered
	assert "Notes: quiet room" in filtered
	assert "Footer: end of page" not in filtered

	no_match = asyncio.run(sb.get_content(filter="nonexistent-token"))
	assert "No lines matched filter" in no_match

	past_eof = asyncio.run(sb.get_content(offset=99999))
	assert "past end of content" in past_eof


def test_compact_json_and_bounds_across_tools(sb, monkeypatch):
	page = FakePage()
	monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

	page.evaluate = AsyncMock(return_value={
		"ok": True,
		"status": 200,
		"statusText": "OK",
		"url": "https://portal.example/api",
		"duration": 10,
		"headers": {},
		"isJson": True,
		"data": {"items": ["x" * 500 for _ in range(30)]},
	})
	fetch_out = asyncio.run(sb.fetch(url="/api"))
	assert "[Truncated:" in fetch_out
	assert len(fetch_out) < 8500
	assert ',"' in fetch_out or '":[' in fetch_out

	page.evaluate = AsyncMock(return_value=[
		{"source": "StoreA", "keys": ["a"], "data": {"a": "y" * 6000}},
		{"source": "StoreB", "keys": ["b"], "data": {"b": "z" * 6000}},
	])
	state_out = asyncio.run(sb.state())
	assert "[Truncated:" in state_out
	assert len(state_out) < 8500

	page.evaluate = AsyncMock(return_value="q" * 12000)
	eval_out = asyncio.run(sb.evaluate_js(expression="big()"))
	assert "[Truncated: 12000 total characters]" in eval_out
	assert len(eval_out) < 8500

	page.evaluate = AsyncMock(return_value="b" * 5000)
	batch_out = asyncio.run(sb.batch([{"action": "evaluate", "expression": "big()"}]))
	assert "[Truncated: 5000 total characters]" in batch_out
	assert len(batch_out) < 2500


def test_telemetry_and_downloads_bound_urls_and_output(sb, monkeypatch):
	tracker = sb.TelemetryTracker(maxlen=200)
	monkeypatch.setattr(sb, "telemetry_tracker", tracker)
	page = FakePage()
	monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

	long_url = "https://cdn.example.com/oauth/callback?" + "token=" + "a" * 300
	for i in range(40):
		tracker._network.setdefault(page, deque(maxlen=200)).append({
			"timestamp": "2026-11-22T12:00:00",
			"status": 200,
			"failure": "",
			"method": "GET",
			"resource_type": "fetch",
			"content_type": "application/json",
			"size_bytes": 512,
			"duration_ms": 15,
			"url": f"{long_url}&i={i}",
		})
	net_out = asyncio.run(sb.network_requests(max_length=1500))
	assert long_url not in net_out
	assert "[Truncated at 1500 chars" in net_out
	assert net_out.count("showing ") == 1
	assert len(net_out) <= 1600

	for i in range(40):
		tracker._console.setdefault(page, deque(maxlen=200)).append({
			"timestamp": "2026-11-22T12:00:00",
			"level": "error",
			"location": long_url,
			"text": f"err-{i} " + "m" * 100,
		})
	monkeypatch.setattr(tracker, "ensure_console_capture", AsyncMock(return_value=True))
	con_out = asyncio.run(sb.console_logs(max_length=1200))
	assert long_url not in con_out
	assert "[Truncated at 1200 chars" in con_out
	assert con_out.count("showing ") == 1
	assert len(con_out) <= 1300

	dl_tracker = sb.DownloadTracker(maxlen=10)
	dl_tracker._entries.append({
		"id": 1,
		"status": "completed",
		"suggested_filename": "stmt.pdf",
		"size_bytes": 1024,
		"save_path": "/tmp/stmt.pdf",
		"url": long_url,
		"started_at": "2026-11-22T12:00:00",
		"completed_at": "2026-11-22T12:00:01",
		"error": None,
	})
	monkeypatch.setattr(sb, "download_tracker", dl_tracker)
	dl_out = asyncio.run(sb.downloads())
	assert long_url not in dl_out
	assert "..." in dl_out


def test_format_playwright_error_strips_call_log_bloat(sb):
	bloated = RuntimeError(
		"Locator.click: Timeout 5000ms exceeded.\n"
		"Call log:\n"
		"  - waiting for locator('#pending')\n"
		"    - locator resolved to <button id=\"pending\" class=\"axp-btn-very-long\">Pending</button>\n"
		"  - attempting click action\n"
		"    2 × waiting for element to be visible, enabled and stable\n"
		"    - <div id=\"modal-mask\" class=\"overlay-backdrop extra-class\" data-blob=\"" + "x" * 2000 + "\"></div> intercepts pointer events\n"
		"  - retrying click action\n"
		"    - waiting 100ms\n"
	)
	formatted = sb._format_playwright_error(bloated)
	assert len(formatted) <= 300
	assert "Call log:" not in formatted
	assert "<div#modal-mask.overlay-backdrop> intercepts pointer events" in formatted
	assert "try force=True" in formatted

	not_vis = RuntimeError(
		"Locator.click: Timeout 5000ms exceeded.\n"
		"Call log:\n"
		"  - waiting for locator('#hidden')\n"
		"    - element is not visible\n"
	)
	formatted_nv = sb._format_playwright_error(not_vis)
	assert "element is not visible" in formatted_nv
	assert "Call log:" not in formatted_nv

	plain = RuntimeError("intercepted by overlay")
	assert sb._format_playwright_error(plain) == "intercepted by overlay"


def test_action_delta_hints_for_navigation_and_dialogs(sb, monkeypatch):
	loc = FakeLocator(count=1)
	page = FakePage(url="https://portal.example/step1", locator_map={"#next": loc})

	async def _click_nav(**kwargs):
		page.url = "https://portal.example/step2"
		page._dialog_history.append({"type": "alert", "message": "Saved successfully!"})

	loc.click = AsyncMock(side_effect=_click_nav)
	monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

	res = asyncio.run(sb.click(selector="#next"))
	assert "navigated -> https://portal.example/step2" in res
	assert "dialog[alert]: Saved successfully!" in res

	loc.click = AsyncMock()
	res_same = asyncio.run(sb.click(selector="#next"))
	assert "navigated ->" not in res_same
	assert "dialog[" not in res_same
