import asyncio
import datetime
import fcntl
import importlib.machinery
import importlib.util
import json
import threading
import time
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser"


def _load_stealth_browser_module():
	loader = importlib.machinery.SourceFileLoader("stealth_browser_mod", str(SCRIPT_PATH))
	spec = importlib.util.spec_from_loader("stealth_browser_mod", loader)
	mod = importlib.util.module_from_spec(spec)
	loader.exec_module(mod)
	return mod


@pytest.fixture(scope="module")
def sb():
	return _load_stealth_browser_module()


@pytest.fixture(autouse=True)
def reset_state(sb, monkeypatch):
	sb._adblock_engine = None
	sb._adblock_initialized = False
	sb._adblock_load_task = None
	sb.session._playwright = None
	sb.session._browser = None
	sb.session._context = None
	sb.session._active_page = None
	sb.session._idle_task = None
	sb.session.headless = True
	sb.keep_alive_mgr._tasks.clear()
	sb.keep_alive_mgr._configs.clear()
	yield
	sb.session._playwright = None
	sb.session._browser = None
	sb.session._context = None
	sb.session._active_page = None
	sb.session._idle_task = None


class FakeLocator:
	def __init__(self, wait_for_impl=None):
		self.first = self
		self._wait_for_impl = wait_for_impl
		self.calls = []

	async def wait_for(self, **kwargs):
		self.calls.append(kwargs)
		if self._wait_for_impl is not None:
			return await self._wait_for_impl(**kwargs)
		return None


class FakePage:
	def __init__(self, url="https://example.com", title="Example", closed=False):
		self.url = url
		self._title = title
		self._closed = closed
		self._listeners = {}
		self._locators = {}
		self.goto_impl = None
		self.title_impl = None
		self.close_impl = None
		self.evaluate_impl = None
		self.evaluate_calls = []
		self.bring_to_front_impl = None
		self.wait_for_load_state_impl = None

	def is_closed(self):
		return self._closed

	def on(self, event, callback):
		self._listeners.setdefault(event, []).append(callback)

	async def emit(self, event, arg=None):
		for cb in list(self._listeners.get(event, [])):
			res = cb(arg)
			if asyncio.iscoroutine(res):
				await res

	def locator(self, selector):
		return self._locators.setdefault(selector, FakeLocator())

	async def goto(self, url, **kwargs):
		if self.goto_impl is not None:
			return await self.goto_impl(url, **kwargs)
		self.url = url
		resp = MagicMock()
		resp.status = 200
		return resp

	async def title(self):
		if self.title_impl is not None:
			return await self.title_impl()
		return self._title

	async def close(self):
		if self.close_impl is not None:
			return await self.close_impl()
		self._closed = True
		await self.emit("close")

	async def evaluate(self, expression, arg=None, *, isolated_context=True):
		self.evaluate_calls.append((expression, arg, isolated_context))
		if self.evaluate_impl is not None:
			return await self.evaluate_impl(expression, arg)
		return None

	async def bring_to_front(self):
		if self.bring_to_front_impl is not None:
			return await self.bring_to_front_impl()
		return None

	async def wait_for_load_state(self, state="domcontentloaded", timeout=5000):
		if self.wait_for_load_state_impl is not None:
			return await self.wait_for_load_state_impl(state, timeout)
		return None


class FakeDialog:
	def __init__(self, dialog_type="alert", message="hello"):
		self.type = dialog_type
		self.message = message
		self.accepted = False
		self.dismissed = False

	async def accept(self):
		self.accepted = True

	async def dismiss(self):
		self.dismissed = True


class FakeRoute:
	def __init__(self):
		self.continued = 0
		self.aborted = 0

	async def continue_(self):
		self.continued += 1

	async def abort(self):
		self.aborted += 1


class FakeRequest:
	def __init__(self, url="https://example.com/app.js", resource_type="script", frame=None, frame_error=None):
		self.url = url
		self.resource_type = resource_type
		self._frame = frame
		self._frame_error = frame_error

	@property
	def frame(self):
		if self._frame_error is not None:
			raise self._frame_error
		return self._frame


class FakePlaywrightTimeoutError(Exception):
	pass


FakePlaywrightTimeoutError.__name__ = "TimeoutError"


def test_fastmcp_instructions_cheatsheet(sb):
	instructions = sb.mcp.instructions
	lines = [line for line in instructions.splitlines() if line.strip()]
	assert 10 <= len(lines) <= 18
	assert "Stay headless by default" in instructions
	assert "set_headless(headless=False)" in instructions
	for token in (
		"evaluate_js(expression=",
		"script=",
		"main_world=",
		"wait_for(",
		"batch(",
		"fetch(",
		"navigate(",
		"snapshot(",
		"click(",
		"switch_tab(tab=",
		"close_tab(tab=",
	):
		assert token in instructions, f"Missing {token} in instructions"


def test_adblock_warmup_nonblocking_and_offloaded(sb, monkeypatch):
	main_tid = threading.get_ident()
	worker_tids = []
	calls = 0

	fake_engine = MagicMock()
	fake_engine.check_network_urls.return_value = MagicMock(matched=True)

	def slow_build():
		nonlocal calls
		calls += 1
		worker_tids.append(threading.get_ident())
		time.sleep(0.15)
		return fake_engine

	monkeypatch.setattr(sb, "_load_or_build_engine", slow_build)

	async def scenario():
		frame = MagicMock()
		frame.url = "https://example.com"
		frame.page = FakePage()
		route1 = FakeRoute()
		route2 = FakeRoute()
		req = FakeRequest(url="https://tracker.example/pixel.js", frame=frame)

		t0 = time.perf_counter()
		await sb._network_route_handler(route1, req)
		await sb._network_route_handler(route2, req)
		elapsed = time.perf_counter() - t0

		assert elapsed < 0.08
		assert route1.continued == 1
		assert route2.continued == 1
		assert sb._adblock_load_task is not None

		await sb._adblock_load_task
		assert calls == 1
		assert worker_tids == [worker_tids[0]]
		assert worker_tids[0] != main_tid
		assert sb._adblock_initialized is True

		route3 = FakeRoute()
		await sb._network_route_handler(route3, req)
		assert route3.aborted == 1

	asyncio.run(scenario())


def test_network_route_handler_service_worker_passthrough(sb):
	async def scenario():
		route = FakeRoute()
		req = FakeRequest(
			url="https://example.com/sw-fetch",
			frame_error=RuntimeError("Service Worker requests do not have an associated frame"),
		)
		await sb._network_route_handler(route, req)
		assert route.continued == 1
		assert route.aborted == 0

	asyncio.run(scenario())


def test_detect_cdp_headless_offloaded_to_thread(sb, monkeypatch):
	main_tid = threading.get_ident()
	detect_tids = []

	def fake_detect():
		detect_tids.append(threading.get_ident())
		time.sleep(0.05)
		return False

	fake_ctx = MagicMock()
	fake_ctx.route = AsyncMock()
	fake_ctx.pages = []
	fake_browser = MagicMock()
	fake_browser.contexts = [fake_ctx]
	fake_browser.new_browser_cdp_session = AsyncMock(side_effect=RuntimeError("skip"))
	fake_pw = MagicMock()
	fake_pw.chromium.connect_over_cdp = AsyncMock(return_value=fake_browser)

	sb.session._playwright = fake_pw
	monkeypatch.setattr(sb.session, "_detect_cdp_headless", fake_detect)
	monkeypatch.setattr(sb, "_adblock_initialized", True)

	async def scenario():
		ctx = await sb.session._connect_cdp()
		assert ctx is fake_ctx
		assert sb.session.headless is False
		assert detect_tids and detect_tids[0] != main_tid

	asyncio.run(scenario())


def test_launch_detached_offloads_ext_and_cdp_probe(sb, monkeypatch, tmp_path):
	main_tid = threading.get_ident()
	ext_tids = []
	probe_tids = []

	monkeypatch.setattr(sb, "PROFILE_DIR", str(tmp_path / "profile"))
	monkeypatch.setattr(sb, "CACHE_DIR", str(tmp_path / "cache"))
	monkeypatch.setattr(sb, "_apple_passwords_ext_cache", None)
	monkeypatch.setattr(sb, "BROWSER_EXECUTABLE", "/usr/bin/true")

	def fake_resolve_ext():
		ext_tids.append(threading.get_ident())
		return "/tmp/fake-ext"

	def fake_probe():
		probe_tids.append(threading.get_ident())
		return True

	fake_proc = MagicMock()
	fake_proc.poll.return_value = None
	launched_cmd = []

	def fake_popen(cmd, **kwargs):
		launched_cmd.extend(cmd)
		return fake_proc

	monkeypatch.setattr(sb, "_resolve_apple_passwords_ext_locked", fake_resolve_ext)
	monkeypatch.setattr(sb.session, "_probe_cdp_ready", fake_probe)
	monkeypatch.setattr(sb.subprocess, "Popen", fake_popen)

	async def scenario():
		await sb.session._launch_detached_chromium()
		assert ext_tids and ext_tids[0] != main_tid
		assert probe_tids and probe_tids[0] != main_tid
		assert "--load-extension=/tmp/fake-ext" in launched_cmd

	asyncio.run(scenario())


def test_acquire_file_lock_times_out_when_contended(sb, tmp_path):
	lock_path = tmp_path / "contended.lock"
	with open(lock_path, "w", encoding="utf-8") as holder:
		fcntl.flock(holder, fcntl.LOCK_EX)
		try:
			with open(lock_path, "w", encoding="utf-8") as waiter:
				with pytest.raises(TimeoutError):
					sb._acquire_file_lock(waiter, timeout_s=0.12)
		finally:
			fcntl.flock(holder, fcntl.LOCK_UN)


def test_connect_cdp_outer_timeout(sb, monkeypatch):
	monkeypatch.setattr(sb, "CDP_CONNECT_TIMEOUT_S", 0.05)

	async def hang(*args, **kwargs):
		await asyncio.sleep(5)

	fake_pw = MagicMock()
	fake_pw.chromium.connect_over_cdp = hang
	sb.session._playwright = fake_pw

	async def scenario():
		t0 = time.perf_counter()
		ctx = await sb.session._connect_cdp()
		assert ctx is None
		assert (time.perf_counter() - t0) < 0.5

	asyncio.run(scenario())


def test_get_pages_outer_timeout(sb, monkeypatch):
	monkeypatch.setattr(sb, "GET_CONTEXT_TIMEOUT_S", 0.05)

	async def hang():
		await asyncio.sleep(5)

	monkeypatch.setattr(sb.session, "get_context", hang)

	async def scenario():
		with pytest.raises(asyncio.TimeoutError):
			await sb.session.get_pages()

	asyncio.run(scenario())


def test_navigate_outer_timeout_and_title_fallback(sb, monkeypatch):
	monkeypatch.setattr(sb, "GOTO_OUTER_BUFFER_S", 0.05)
	monkeypatch.setattr(sb, "PAGE_TITLE_TIMEOUT_S", 0.05)

	async def scenario():
		page = FakePage()

		async def hang_goto(*args, **kwargs):
			await asyncio.sleep(5)

		page.goto_impl = hang_goto
		monkeypatch.setattr(sb.session, "get_context", AsyncMock(return_value=MagicMock()))
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

		res = await sb.navigate(url="https://example.com", timeout_ms=50)
		assert "Navigation error: Timed out" in res

		page2 = FakePage(url="https://example.com")

		async def hang_title():
			await asyncio.sleep(5)

		page2.title_impl = hang_title
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page2))
		monkeypatch.setattr(sb.session, "get_pages", AsyncMock(return_value=[page2]))

		res2 = await sb.navigate(url="https://example.com", timeout_ms=1000)
		assert "Navigated tab [0]" in res2
		assert "Title: '(Unavailable)'" in res2

		page3 = FakePage()

		async def pw_timeout_goto(*args, **kwargs):
			raise FakePlaywrightTimeoutError("Timeout 100ms exceeded")

		page3.goto_impl = pw_timeout_goto
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page3))
		res3 = await sb.navigate(url="https://example.com", timeout_ms=100)
		assert "Navigation error: Timed out after 100ms" in res3

	asyncio.run(scenario())


def test_navigate_service_worker_recovery(sb, monkeypatch):
	async def scenario():
		page = FakePage(url="https://pwa.example/home", title="PWA Home")
		load_state_called = []

		async def sw_error_goto(url, **kwargs):
			raise RuntimeError("Service Worker requests do not have an associated frame")

		async def fake_wait_load(state, timeout):
			load_state_called.append(state)

		page.goto_impl = sw_error_goto
		page.wait_for_load_state_impl = fake_wait_load

		monkeypatch.setattr(sb.session, "get_context", AsyncMock(return_value=MagicMock()))
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))
		monkeypatch.setattr(sb.session, "get_pages", AsyncMock(return_value=[page]))

		res = await sb.navigate(url="https://pwa.example/home")
		assert "Navigated tab [0]" in res
		assert "loaded (service worker)" in res
		assert "PWA Home" in res
		assert load_state_called == ["domcontentloaded"]

	asyncio.run(scenario())


def test_close_browser_bounds_hung_cdp_and_force_kills_in_thread(sb, monkeypatch):
	monkeypatch.setattr(sb, "BROWSER_CLOSE_TIMEOUT_S", 0.05)
	monkeypatch.setattr(sb, "PLAYWRIGHT_STOP_TIMEOUT_S", 0.05)
	main_tid = threading.get_ident()
	kill_tids = []
	close_sync_called = []

	async def hang(*args, **kwargs):
		await asyncio.sleep(5)

	fake_cdp = MagicMock()
	fake_cdp.send = hang
	fake_browser = MagicMock()
	fake_browser.is_connected.return_value = True
	fake_browser.new_browser_cdp_session = AsyncMock(return_value=fake_cdp)
	fake_browser.close = AsyncMock()
	fake_ctx = MagicMock()
	fake_ctx.close = AsyncMock()
	fake_pw = MagicMock()
	fake_pw.stop = hang

	sb.session._browser = fake_browser
	sb.session._context = fake_ctx
	sb.session._playwright = fake_pw

	monkeypatch.setattr(sb.session, "close_sync", lambda: close_sync_called.append(True))
	monkeypatch.setattr(sb, "_save_persisted_headless", lambda _: None)
	monkeypatch.setattr(sb, "_force_kill_browser_processes", lambda: kill_tids.append(threading.get_ident()))

	async def scenario():
		t0 = time.perf_counter()
		res = await sb.close_browser(force_kill=True)
		elapsed = time.perf_counter() - t0
		assert "Browser completely closed" in res
		assert elapsed < 0.6
		assert fake_ctx.close.await_count == 0
		assert fake_browser.close.await_count == 0
		assert close_sync_called
		assert kill_tids and kill_tids[0] != main_tid

	asyncio.run(scenario())


def test_close_tab_timeout_and_param_aliases(sb, monkeypatch):
	monkeypatch.setattr(sb, "PAGE_CLOSE_TIMEOUT_S", 0.05)

	async def scenario():
		p0 = FakePage(url="https://a.example")
		p1 = FakePage(url="https://b.example")

		async def hang_close():
			await asyncio.sleep(5)

		p1.close_impl = hang_close
		monkeypatch.setattr(sb.session, "get_pages", AsyncMock(return_value=[p0, p1]))

		res_timeout = await sb.close_tab(tab=1)
		assert "Error closing tab [1]: Timed out" in res_timeout

		p1.close_impl = None
		get_pages_mock = AsyncMock(side_effect=[[p0, p1], [p0], [p0, p1], [p0]])
		monkeypatch.setattr(sb.session, "get_pages", get_pages_mock)

		res_tab = await sb.close_tab(tab=1)
		assert "Closed tab [1] (https://b.example)" in res_tab

		p1._closed = False
		res_index = await sb.close_tab(index=1)
		assert "Closed tab [1] (https://b.example)" in res_index

		close_browser_mock = AsyncMock(return_value="closed all")
		monkeypatch.setattr(sb, "close_browser", close_browser_mock)
		assert await sb.close_tab(tab=-99) == "closed all"
		assert await sb.close_tab(index=-99) == "closed all"

	asyncio.run(scenario())


def test_restart_browser_outer_timeout(sb, monkeypatch):
	monkeypatch.setattr(sb, "RESTART_BROWSER_TIMEOUT_S", 0.08)

	async def hang_inner(**kwargs):
		await asyncio.sleep(5)

	monkeypatch.setattr(sb, "_restart_browser_inner", hang_inner)

	async def scenario():
		t0 = time.perf_counter()
		res = await sb.restart_browser()
		assert "Error restarting browser: Timed out" in res
		assert (time.perf_counter() - t0) < 0.5

	asyncio.run(scenario())


def test_dialog_auto_handler_records_and_handles_types(sb):
	async def scenario():
		page = FakePage(url="https://bank.example/transfer")
		sb.session._register_page_listeners(page)
		sb.session._register_page_listeners(page)
		assert len(page._listeners["dialog"]) == 1

		d_alert = FakeDialog("alert", "Session expiring")
		d_confirm = FakeDialog("confirm", "Are you sure?")
		d_prompt = FakeDialog("prompt", "Enter code")
		d_unload = FakeDialog("beforeunload", "Leave site?")

		for d in (d_alert, d_confirm, d_prompt, d_unload):
			await page.emit("dialog", d)

		assert d_alert.dismissed and not d_alert.accepted
		assert d_confirm.dismissed and not d_confirm.accepted
		assert d_prompt.dismissed and not d_prompt.accepted
		assert d_unload.accepted and not d_unload.dismissed

		history = page._dialog_history
		assert isinstance(history, deque)
		assert len(history) == 4
		assert [entry["type"] for entry in history] == ["alert", "confirm", "prompt", "beforeunload"]
		assert history[0]["message"] == "Session expiring"
		assert history[0]["url"] == "https://bank.example/transfer"
		assert "timestamp" in history[0]

		for i in range(sb.MAX_DIALOG_HISTORY + 15):
			await page.emit("dialog", FakeDialog("alert", f"msg-{i}"))
		assert len(history) == sb.MAX_DIALOG_HISTORY
		assert history[-1]["message"] == f"msg-{sb.MAX_DIALOG_HISTORY + 14}"

	asyncio.run(scenario())


def test_get_pages_registers_listeners_on_all_tabs(sb, monkeypatch):
	async def scenario():
		p0 = FakePage(url="https://one.example")
		p1 = FakePage(url="https://two.example")
		ctx = MagicMock()
		ctx.pages = [p0, p1]
		monkeypatch.setattr(sb.session, "get_context", AsyncMock(return_value=ctx))

		pages = await sb.session.get_pages()
		assert pages == [p0, p1]
		assert "dialog" in p0._listeners
		assert "dialog" in p1._listeners

	asyncio.run(scenario())


def test_wait_for_validation_and_conditions(sb, monkeypatch):
	async def scenario():
		assert "specify at least one" in await sb.wait_for()
		assert "invalid state" in await sb.wait_for(selector="#x", state="bogus")
		assert "timeout_ms must be > 0" in await sb.wait_for(selector="#x", timeout_ms=0)

		page = FakePage(url="https://app.example/loading")
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

		async def flip_url():
			await asyncio.sleep(0.04)
			page.url = "https://app.example/dashboard"

		eval_calls = 0

		async def fake_eval(expr, arg):
			nonlocal eval_calls
			eval_calls += 1
			if eval_calls == 1:
				raise RuntimeError("Execution context was destroyed")
			return eval_calls >= 3 and arg == "Total Balance"

		page.evaluate_impl = fake_eval

		task = asyncio.create_task(flip_url())
		res = await sb.wait_for(
			url_contains="/dashboard",
			selector=".portfolio",
			text="Total Balance",
			state="attached",
			timeout_ms=2000,
		)
		await task
		assert "Wait condition met" in res
		assert "url_contains='/dashboard'" in res
		assert "selector='.portfolio' (attached)" in res
		assert "text='Total Balance'" in res
		assert page._locators[".portfolio"].calls[0]["state"] == "attached"

	asyncio.run(scenario())


def test_wait_for_timeouts_and_closed_tab(sb, monkeypatch):
	async def scenario():
		page = FakePage(url="https://app.example/still-here")
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

		res_url = await sb.wait_for(url_contains="/never", timeout_ms=80)
		assert "Wait timed out after 80ms waiting for url containing '/never'" in res_url

		async def pw_timeout(**kwargs):
			raise FakePlaywrightTimeoutError("Timeout 80ms exceeded")

		page._locators["#missing"] = FakeLocator(wait_for_impl=pw_timeout)
		res_sel = await sb.wait_for(selector="#missing", timeout_ms=80)
		assert "Wait timed out after 80ms waiting for selector '#missing' (visible)" in res_sel

		page.evaluate_impl = AsyncMock(return_value=False)
		res_txt = await sb.wait_for(text="Never Appears", timeout_ms=80)
		assert "Wait timed out after 80ms waiting for visible text 'Never Appears'" in res_txt

		closed_page = FakePage(url="https://app.example/closed", closed=True)
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=closed_page))
		res_closed = await sb.wait_for(url_contains="/other", timeout_ms=500)
		assert "tab closed while waiting" in res_closed

	asyncio.run(scenario())


def test_evaluate_js_alias_json_and_truncation(sb, monkeypatch):
	async def scenario():
		page = FakePage()
		received = []

		async def fake_eval(expr, arg=None):
			received.append(expr)
			if expr == "obj":
				return {"ok": True, "when": datetime.date(2026, 11, 21), "items": [1, 2]}
			if expr == "big":
				return "x" * 500
			return 42

		page.evaluate_impl = fake_eval
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

		err = await sb.evaluate_js()
		assert "must be non-empty" in err
		assert received == []

		res_expr = await sb.evaluate_js(expression="1+1")
		assert res_expr == "Result: 42"

		res_script = await sb.evaluate_js(script="2+2")
		assert res_script == "Result: 42"
		assert received == ["1+1", "2+2"]

		res_json = await sb.evaluate_js(expression="obj")
		assert res_json.startswith("Result: ")
		parsed = json.loads(res_json[len("Result: "):])
		assert parsed == {"ok": True, "when": "2026-11-21", "items": [1, 2]}

		res_trunc = await sb.evaluate_js(expression="big", max_length=100)
		assert "... [Truncated: 500 total characters]" in res_trunc
		assert len(res_trunc) < 200

	asyncio.run(scenario())


def test_switch_tab_aliases_and_validation(sb, monkeypatch):
	async def scenario():
		p0 = FakePage(url="https://zero.example", title="Zero")
		p1 = FakePage(url="https://one.example", title="One")
		monkeypatch.setattr(sb.session, "get_pages", AsyncMock(return_value=[p0, p1]))

		assert "provide a 'tab' (or 'index') value" in await sb.switch_tab()
		assert "Switched to tab [1]: 'One'" in await sb.switch_tab(tab=1)
		assert "Switched to tab [0]: 'Zero'" in await sb.switch_tab(index=0)
		assert "Switched to tab [1]: 'One'" in await sb.switch_tab(1)
		assert "Invalid tab index 5" in await sb.switch_tab(tab=5)

	asyncio.run(scenario())


def test_mcp_tool_schemas_accept_expected_params(sb):
	async def scenario():
		tools = {t.name: t for t in await sb.mcp.list_tools()}
		assert "wait_for" in tools
		assert set(tools["wait_for"].inputSchema["properties"].keys()) >= {
			"selector", "text", "url_contains", "state", "timeout_ms", "tab",
		}
		assert {"expression", "script", "max_length", "tab", "timeout_ms", "main_world"} <= set(
			tools["evaluate_js"].inputSchema["properties"].keys()
		)
		assert {"tab", "index"} <= set(tools["switch_tab"].inputSchema["properties"].keys())
		assert {"tab", "index"} <= set(tools["close_tab"].inputSchema["properties"].keys())
		assert set(tools["extract"].inputSchema["properties"].keys()) >= {
			"container_selector", "fields", "limit", "include_shadow", "include_iframes", "tab", "max_length",
		}


def test_mcp_tool_schemas_forbid_extra_params(sb):
	async def scenario():
		tools = {t.name: t for t in await sb.mcp.list_tools()}
		for name in ("navigate", "click", "switch_tab", "close_tab", "evaluate_js", "extract"):
			assert tools[name].inputSchema.get("additionalProperties") is False, name

		for name, bad_args in (
			("navigate", {"url": "https://x.example", "typo": 1}),
			("switch_tab", {"tab": 0, "tab_index": 0}),
		):
			try:
				await sb.mcp._tool_manager.call_tool(name, bad_args, convert_result=False)
				raise AssertionError(f"{name} accepted unknown params {bad_args}")
			except Exception as exc:
				assert "extra_forbidden" in str(exc) or "Extra inputs" in str(exc), f"{name}: {exc}"

	asyncio.run(scenario())


def test_mcp_tool_call_unknown_param_error_names_offender(sb):
	async def scenario():
		try:
			await sb.mcp._tool_manager.call_tool("close_tab", {"tab_index": 2}, convert_result=False)
			raise AssertionError("expected validation error")
		except Exception as exc:
			assert "tab_index" in str(exc), str(exc)

	asyncio.run(scenario())


def test_network_route_handler_document_policy(sb, monkeypatch):
	class TrackingEngine:
		def __init__(self, matched: bool):
			self.matched = matched
			self.calls = []

		def check_network_urls(self, url, frame_url, res_type):
			self.calls.append((url, frame_url, res_type))
			result = MagicMock()
			result.matched = self.matched
			return result

	async def scenario():
		engine = TrackingEngine(matched=True)
		monkeypatch.setattr(sb, "get_adblock_engine", lambda: engine)

		subframe = MagicMock()
		subframe.url = "https://old.example/widget"
		subframe.parent_frame = MagicMock()
		subframe.page = FakePage()
		main_frame = MagicMock()
		main_frame.url = "https://site.example"
		main_frame.parent_frame = None
		main_frame.page = FakePage()
		fresh_frame = MagicMock()
		fresh_frame.url = "about:blank"
		fresh_frame.parent_frame = MagicMock()
		fresh_frame.page = FakePage()

		route = FakeRoute()
		req = FakeRequest(url="https://ads.example/iframe.html", resource_type="document", frame=subframe)
		await sb._network_route_handler(route, req)
		assert route.aborted == 1
		assert route.continued == 0
		assert engine.calls[-1] == ("https://ads.example/iframe.html", "https://old.example/widget", "document")

		route = FakeRoute()
		req = FakeRequest(url="https://site.example/page2", resource_type="document", frame=main_frame)
		await sb._network_route_handler(route, req)
		assert route.continued == 1
		assert route.aborted == 0

		route = FakeRoute()
		req = FakeRequest(url="https://site.example/first", resource_type="document", frame=fresh_frame)
		await sb._network_route_handler(route, req)
		assert route.continued == 1
		assert route.aborted == 0

		uncommitted_subframe = MagicMock()
		uncommitted_subframe.url = "about:blank"
		uncommitted_subframe.parent_frame = MagicMock()
		uncommitted_subframe.page = FakePage()
		route = FakeRoute()
		req = FakeRequest(url="https://ads.example/late.html", resource_type="document", frame=uncommitted_subframe)
		await sb._network_route_handler(route, req)
		assert route.continued == 1
		assert route.aborted == 0

		engine_ok = TrackingEngine(matched=False)
		monkeypatch.setattr(sb, "get_adblock_engine", lambda: engine_ok)
		route = FakeRoute()
		req = FakeRequest(url="https://ok.example/frame.html", resource_type="document", frame=subframe)
		await sb._network_route_handler(route, req)
		assert route.continued == 1
		assert route.aborted == 0
		assert engine_ok.calls[-1][2] == "document"

	asyncio.run(scenario())


def test_network_route_handler_document_policy_parent_frame_absent(sb, monkeypatch):
	class TrackingEngine:
		def check_network_urls(self, url, frame_url, res_type):
			result = MagicMock()
			result.matched = True
			return result

	async def scenario():
		engine = TrackingEngine()
		monkeypatch.setattr(sb, "get_adblock_engine", lambda: engine)
		frame = MagicMock(spec=[])
		frame.url = "https://old.example"
		frame.page = FakePage()
		route = FakeRoute()
		req = FakeRequest(url="https://x.example/doc.html", resource_type="document", frame=frame)
		await sb._network_route_handler(route, req)
		assert route.continued == 1
		assert route.aborted == 0

	asyncio.run(scenario())


def test_status_surfaces_recent_dialog_history(sb, monkeypatch):
	async def scenario():
		p1 = FakePage(url="https://app.example/settings", title="Settings")
		p2 = FakePage(url="https://app.example/list", title="List")
		pages = [p1, p2]
		tid1 = sb.session.get_tab_id(p1)
		sb.session._active_page = p2
		monkeypatch.setattr(sb.session, "get_pages", AsyncMock(return_value=pages))

		p1._dialog_history = deque([
			{"type": "alert", "message": "Session expired", "url": p1.url,
				"timestamp": "2026-11-22T10:00:00+00:00"},
			{"type": "confirm", "message": "Delete item?", "url": p1.url,
				"timestamp": "2026-11-22T10:05:00+00:00"},
		], maxlen=sb.MAX_DIALOG_HISTORY)

		out = await sb.status()
		assert "Recent dialogs" in out
		assert f"[{tid1}] confirm: Delete item?" in out
		assert f"[{tid1}] alert: Session expired" in out
		assert "auto-dismissed" in out

		p1._dialog_history.clear()
		out_clean = await sb.status()
		assert "Recent dialogs" not in out_clean

	asyncio.run(scenario())


def test_state_evaluates_in_main_world_and_formats_stores(sb, monkeypatch):
	async def scenario():
		page = FakePage(url="https://app.example/dashboard")

		async def fake_eval(expr, arg=None):
			assert arg == {"targetFramework": "auto", "selector": ""}
			return [
				{
					"source": "Next.js (__NEXT_DATA__)",
					"keys": ["page", "props"],
					"data": {"page": "/dashboard", "props": {"user": "levon"}},
				},
				{
					"source": "Redux (window.store)",
					"keys": [],
					"data": {},
				},
			]

		page.evaluate_impl = fake_eval
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

		out = await sb.state()
		assert len(page.evaluate_calls) == 1
		assert page.evaluate_calls[0][2] is False
		assert "Next.js (__NEXT_DATA__)" in out
		assert '"user":"levon"' in out
		assert "Redux (window.store)" in out
		assert "```json\n{}\n```" in out

	asyncio.run(scenario())


def test_evaluate_js_and_batch_respect_main_world_flag(sb, monkeypatch):
	async def scenario():
		page = FakePage(url="https://app.example/home")
		page.evaluate_impl = AsyncMock(return_value="ok")
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))

		res_default = await sb.evaluate_js(expression="document.title")
		res_main = await sb.evaluate_js(expression="window.__NEXT_DATA__", main_world=True)
		assert res_default == "Result: ok"
		assert res_main == "Result: ok"
		assert page.evaluate_calls[0][2] is True
		assert page.evaluate_calls[1][2] is False

		batch_res = await sb.batch(actions=[
			{"action": "evaluate", "expression": "document.title"},
			{"action": "evaluate", "expression": "window.store.getState()", "main_world": True},
		])
		assert "Batch completed (2 steps" in batch_res
		assert page.evaluate_calls[2][2] is True
		assert page.evaluate_calls[3][2] is False

	asyncio.run(scenario())
