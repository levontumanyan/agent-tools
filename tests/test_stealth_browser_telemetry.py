import asyncio
import base64
import importlib.machinery
import importlib.util
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional
import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser"
_loader = importlib.machinery.SourceFileLoader("stealth_browser", str(_SCRIPT_PATH))
_spec = importlib.util.spec_from_loader("stealth_browser", _loader)
assert _spec is not None
sb = importlib.util.module_from_spec(_spec)
_loader.exec_module(sb)


class FakePage:
	def __init__(self, url: str = "https://example.com/dashboard"):
		self.url = url
		self._closed = False
		self._listeners: dict[str, list[Callable[..., Any]]] = {}
		self.evaluate_calls: list[tuple[str, Any]] = []
		self.evaluate_handler: Optional[Callable[[str, Any], Any]] = None

	def is_closed(self) -> bool:
		return self._closed

	def on(self, event: str, callback: Callable[..., Any]) -> None:
		self._listeners.setdefault(event, []).append(callback)

	def emit(self, event: str, payload: Any = None) -> None:
		for cb in list(self._listeners.get(event, [])):
			cb(payload)

	def close_now(self) -> None:
		self._closed = True
		self.emit("close", self)

	async def evaluate(self, script: str, arg: Any = None) -> Any:
		self.evaluate_calls.append((script, arg))
		if self.evaluate_handler is None:
			raise AssertionError("No evaluate_handler configured")
		res = self.evaluate_handler(script, arg)
		if asyncio.iscoroutine(res):
			return await res
		return res


class FakeDownload:
	def __init__(
		self,
		url: str,
		suggested_filename: str,
		path_value: Any = None,
		path_exc: Optional[Exception] = None,
		failure_value: Optional[str] = None,
		failure_exc: Optional[Exception] = None,
		delay: float = 0.0,
	):
		self.url = url
		self.suggested_filename = suggested_filename
		self._path_value = path_value
		self._path_exc = path_exc
		self._failure_value = failure_value
		self._failure_exc = failure_exc
		self._delay = delay

	async def failure(self) -> Optional[str]:
		if self._delay:
			await asyncio.sleep(self._delay)
		if self._failure_exc is not None:
			raise self._failure_exc
		return self._failure_value

	async def path(self) -> Any:
		if self._path_exc is not None:
			raise self._path_exc
		return self._path_value


class FakeConsoleMessage:
	def __init__(self, msg_type: str, text: str, location: Optional[dict[str, Any]] = None):
		self.type = msg_type
		self.text = text
		self.location = location or {}


class FakeRequest:
	def __init__(
		self,
		url: str,
		method: str = "GET",
		resource_type: str = "fetch",
		timing: Optional[dict[str, Any]] = None,
		failure: Any = None,
	):
		self.url = url
		self.method = method
		self.resource_type = resource_type
		self.timing = timing if timing is not None else {}
		self.failure = failure


class FakeResponse:
	def __init__(
		self,
		url: str,
		status: int = 200,
		method: str = "GET",
		resource_type: str = "fetch",
		headers: Optional[dict[str, str]] = None,
		timing: Optional[dict[str, Any]] = None,
	):
		self.url = url
		self.status = status
		self.headers = headers or {}
		self.request = FakeRequest(
			url=url,
			method=method,
			resource_type=resource_type,
			timing=timing,
		)


def _run(coro):
	return asyncio.run(coro)


def test_download_tracker_lifecycle_and_idempotent_attach(tmp_path):
	async def _scenario():
		tracker = sb.DownloadTracker(maxlen=10, downloads_dir=str(tmp_path))
		page = FakePage()
		tracker.attach(page)
		tracker.attach(page)
		assert len(page._listeners.get("download", [])) == 1

		pdf_file = tmp_path / "statement.pdf"
		pdf_bytes = b"%PDF-1.4\nhello statement\n%%EOF"
		pdf_file.write_bytes(pdf_bytes)

		dl = FakeDownload(
			url="https://bank.example.com/statements/2026-11.pdf",
			suggested_filename="statement.pdf",
			path_value=pdf_file,
			delay=0.02,
		)
		page.emit("download", dl)

		in_progress = tracker.list_entries()
		assert len(in_progress) == 1
		assert in_progress[0]["status"] == "in_progress"
		assert in_progress[0]["id"] == 1
		assert in_progress[0]["suggested_filename"] == "statement.pdf"
		assert in_progress[0]["completed_at"] is None

		await tracker.flush()
		done = tracker.list_entries()
		assert done[0]["status"] == "completed"
		assert done[0]["save_path"] == str(pdf_file)
		assert done[0]["size_bytes"] == len(pdf_bytes)
		assert done[0]["completed_at"] is not None
		assert done[0]["error"] is None

	_run(_scenario())


def test_download_tracker_failure_and_native_fallback(tmp_path):
	async def _scenario():
		tracker = sb.DownloadTracker(maxlen=10, downloads_dir=str(tmp_path))
		page = FakePage()
		tracker.attach(page)

		failed_dl = FakeDownload(
			url="https://bank.example.com/broken.pdf",
			suggested_filename="broken.pdf",
			failure_value="canceled",
		)
		page.emit("download", failed_dl)

		native_file = tmp_path / "report (1).pdf"
		native_file.write_bytes(b"%PDF-1.7 native content")
		native_dl = FakeDownload(
			url="https://bank.example.com/report.pdf",
			suggested_filename="report.pdf",
			path_exc=RuntimeError("Path is not available when connecting remotely"),
		)
		page.emit("download", native_dl)

		missing_dl = FakeDownload(
			url="https://bank.example.com/missing.pdf",
			suggested_filename="missing.pdf",
			path_exc=RuntimeError("disk full"),
		)
		page.emit("download", missing_dl)

		await tracker.flush()
		entries = {e["suggested_filename"]: e for e in tracker.list_entries(limit=10)}

		assert entries["broken.pdf"]["status"] == "failed"
		assert entries["broken.pdf"]["error"] == "canceled"

		assert entries["report.pdf"]["status"] == "completed"
		assert entries["report.pdf"]["save_path"] == str(native_file.resolve())
		assert entries["report.pdf"]["size_bytes"] == len(b"%PDF-1.7 native content")

		assert entries["missing.pdf"]["status"] == "failed"
		assert "disk full" in (entries["missing.pdf"]["error"] or "")

	_run(_scenario())


def test_download_tracker_ring_buffer_and_tool_output(tmp_path, monkeypatch):
	async def _scenario():
		tracker = sb.DownloadTracker(maxlen=3, downloads_dir=str(tmp_path))
		monkeypatch.setattr(sb, "download_tracker", tracker)

		empty_msg = await sb.downloads(limit=10, include_dir=False)
		assert "No tracked browser downloads yet" in empty_msg

		page = FakePage()
		tracker.attach(page)
		for i in range(5):
			f = tmp_path / f"doc_{i}.pdf"
			f.write_bytes(b"x" * (100 + i))
			page.emit(
				"download",
				FakeDownload(
					url=f"https://example.com/doc_{i}.pdf",
					suggested_filename=f"doc_{i}.pdf",
					path_value=f,
				),
			)
		await tracker.flush()

		entries = tracker.list_entries(limit=10)
		assert [e["id"] for e in entries] == [5, 4, 3]

		hidden = tmp_path / ".DS_Store"
		hidden.write_bytes(b"ignore")
		older = tmp_path / "older.csv"
		older.write_bytes(b"a,b\n1,2\n")
		os.utime(older, (time.time() - 3600, time.time() - 3600))
		newest = tmp_path / "newest.pdf"
		newest.write_bytes(b"%PDF-1.4 newest")

		out = await sb.downloads(limit=2, include_dir=True)
		assert "showing 2 of 3" in out
		assert "[#5]" in out
		assert "[#4]" in out
		assert "[#3]" not in out
		assert "Recent files in" in out
		assert "newest.pdf" in out
		assert ".DS_Store" not in out

	_run(_scenario())


def test_fetch_save_path_binary_pdf_and_blob(tmp_path, monkeypatch):
	async def _scenario():
		page = FakePage("https://easyweb.td.com/statements")
		pdf_payload = b"%PDF-1.4\n" + bytes(range(256)) * 200 + b"\n%%EOF"
		encoded = base64.b64encode(pdf_payload).decode("ascii")

		def _eval_handler(_script, arg):
			assert arg["saveBinary"] is True
			return {
				"ok": True,
				"status": 200,
				"statusText": "OK",
				"url": arg["url"],
				"duration": 42,
				"headers": {"content-type": "application/pdf"},
				"base64": encoded,
				"sizeBytes": len(pdf_payload),
			}

		page.evaluate_handler = _eval_handler

		async def _resolve(tab=-1):
			return page

		monkeypatch.setattr(sb.session, "resolve_page", _resolve)

		out_file = tmp_path / "nested" / "td" / "2026-11.pdf"
		res = await sb.fetch(
			url="blob:https://easyweb.td.com/7b1c2d3e-4f5a",
			save_path=str(out_file),
		)

		assert out_file.is_file()
		assert out_file.read_bytes() == pdf_payload
		assert "HTTP 200 OK" in res
		assert "[SAVED]" in res
		assert "application/pdf" in res
		assert str(len(pdf_payload)) in res
		assert str(out_file.resolve()) in res
		assert encoded[:32] not in res

	_run(_scenario())


def test_fetch_save_path_http_error_does_not_write_file(tmp_path, monkeypatch):
	async def _scenario():
		page = FakePage()

		def _eval_handler(_script, arg):
			assert arg["saveBinary"] is True
			return {
				"ok": False,
				"status": 403,
				"statusText": "Forbidden",
				"url": arg["url"],
				"duration": 18,
				"headers": {"Content-Type": "text/html; charset=utf-8"},
				"errorPreview": "<html>Access Denied</html>",
			}

		page.evaluate_handler = _eval_handler

		async def _resolve(tab=-1):
			return page

		monkeypatch.setattr(sb.session, "resolve_page", _resolve)

		out_file = tmp_path / "should_not_exist.pdf"
		res = await sb.fetch(url="https://bank.example.com/secret.pdf", save_path=str(out_file))

		assert not out_file.exists()
		assert "403 Forbidden" in res
		assert "file not saved" in res
		assert "Access Denied" in res

	_run(_scenario())


def test_fetch_standard_json_behavior_preserved(monkeypatch):
	async def _scenario():
		page = FakePage()

		def _eval_handler(_script, arg):
			assert arg["saveBinary"] is False
			return {
				"ok": True,
				"status": 200,
				"statusText": "OK",
				"url": "https://example.com/api/me",
				"duration": 12,
				"headers": {"content-type": "application/json"},
				"isJson": True,
				"data": {"user": "levon"},
			}

		page.evaluate_handler = _eval_handler

		async def _resolve(tab=-1):
			return page

		monkeypatch.setattr(sb.session, "resolve_page", _resolve)

		res = await sb.fetch(url="/api/me")
		assert "[JSON]" in res
		assert '"user": "levon"' in res

	_run(_scenario())


def test_network_requests_filtering_clearing_and_tab_isolation(monkeypatch):
	async def _scenario():
		tracker = sb.TelemetryTracker(maxlen=200)
		monkeypatch.setattr(sb, "telemetry_tracker", tracker)

		page0 = FakePage("https://app.example.com/tab0")
		page1 = FakePage("https://app.example.com/tab1")
		tracker.attach(page0)
		tracker.attach(page0)
		tracker.attach(page1)
		assert len(page0._listeners.get("response", [])) == 1

		page0.emit(
			"response",
			FakeResponse(
				url="https://app.example.com/api/accounts",
				status=200,
				method="GET",
				resource_type="fetch",
				headers={"content-type": "application/json; charset=utf-8", "content-length": "2048"},
				timing={"responseStart": 15, "responseEnd": 38.6},
			),
		)
		page0.emit(
			"response",
			FakeResponse(
				url="https://app.example.com/api/statement.pdf",
				status=200,
				method="POST",
				resource_type="xhr",
				headers={"content-type": "application/pdf", "content-length": "65536"},
				timing={"responseStart": 25, "responseEnd": -1},
			),
		)
		page0.emit(
			"response",
			FakeResponse(
				url="https://app.example.com/api/missing",
				status=404,
				method="GET",
				resource_type="fetch",
				headers={"content-type": "application/json"},
			),
		)
		page0.emit(
			"requestfailed",
			FakeRequest(
				url="https://app.example.com/api/offline",
				method="POST",
				resource_type="xhr",
				failure="net::ERR_CONNECTION_REFUSED",
			),
		)
		page1.emit(
			"response",
			FakeResponse(
				url="https://other.example.com/script.js",
				status=200,
				method="GET",
				resource_type="script",
				headers={"content-type": "application/javascript"},
			),
		)

		pages = [page0, page1]

		async def _resolve(tab=-1):
			return pages[0] if tab < 0 else pages[tab]

		monkeypatch.setattr(sb.session, "resolve_page", _resolve)

		pdf_out = await sb.network_requests(content_type="pdf", tab=0)
		assert "statement.pdf" in pdf_out
		assert "64.0 KB" in pdf_out
		assert "25ms" in pdf_out
		assert "/api/accounts" not in pdf_out

		err_out = await sb.network_requests(status_min=400, tab=0)
		assert "404" in err_out
		assert "/api/missing" in err_out
		assert "/api/accounts" not in err_out
		assert "ERR_CONNECTION_REFUSED" not in err_out

		xhr_fetch = await sb.network_requests(resource_type="xhr,fetch", url_filter="/api/", tab=0)
		assert "/api/accounts" in xhr_fetch
		assert "39ms" in xhr_fetch
		assert "FAILED(net::ERR_CONNECTION_REFUSED)" in xhr_fetch
		assert "other.example.com" not in xhr_fetch

		tab1_out = await sb.network_requests(tab=1)
		assert "other.example.com/script.js" in tab1_out
		assert "/api/accounts" not in tab1_out

		page1.emit(
			"requestfailed",
			FakeRequest(
				url="https://other.example.com/aborted",
				method="GET",
				resource_type="fetch",
				failure={"errorText": "net::ERR_ABORTED"},
			),
		)
		tab1_failed = await sb.network_requests(tab=1)
		assert "FAILED(net::ERR_ABORTED)" in tab1_failed

		cleared_out = await sb.network_requests(limit=2, clear=True, tab=0)
		assert "[buffer cleared]" in cleared_out
		assert "showing 2 of 4" in cleared_out
		assert "/api/missing" in cleared_out
		assert "/api/offline" in cleared_out

		after_clear = await sb.network_requests(tab=0)
		assert "No matching network requests" in after_clear
		assert "(0 total captured)" in after_clear

		page1.close_now()
		assert page1 not in tracker._network

	_run(_scenario())


def test_console_logs_filtering_truncation_and_clearing(monkeypatch):
	async def _scenario():
		tracker = sb.TelemetryTracker(maxlen=5)
		monkeypatch.setattr(sb, "telemetry_tracker", tracker)

		page = FakePage("https://app.example.com/console")
		tracker.attach(page)

		page.emit("console", FakeConsoleMessage("log", "boot ok"))
		page.emit("console", FakeConsoleMessage("warn", "deprecated api", {"url": "app.js", "lineNumber": 42}))
		page.emit("console", FakeConsoleMessage("error", "E" * 700))
		page.emit("pageerror", RuntimeError("Uncaught TypeError: boom"))

		async def _resolve(tab=-1):
			return page

		monkeypatch.setattr(sb.session, "resolve_page", _resolve)

		warn_out = await sb.console_logs(level="warn")
		assert "[warning]" in warn_out
		assert "app.js:42" in warn_out
		assert "boot ok" not in warn_out

		err_out = await sb.console_logs(level="error,pageerror")
		assert "[error]" in err_out
		assert "... [truncated]" in err_out
		assert "[pageerror]" in err_out
		assert "Uncaught TypeError: boom" in err_out
		assert "deprecated api" not in err_out

		cleared = await sb.console_logs(limit=2, clear=True)
		assert "[buffer cleared]" in cleared
		assert "showing 2 of 4" in cleared

		after_clear = await sb.console_logs()
		assert "No matching console logs" in after_clear
		assert "(0 total captured)" in after_clear

		for i in range(8):
			page.emit("console", FakeConsoleMessage("log", f"msg-{i}"))
		capped, total = tracker.get_console(page)
		assert total == 5
		assert [c["text"] for c in capped] == ["msg-3", "msg-4", "msg-5", "msg-6", "msg-7"]

	_run(_scenario())


def test_session_manager_hooks_attach_trackers_on_existing_and_active_pages(monkeypatch):
	async def _scenario():
		dl_tracker = sb.DownloadTracker()
		tel_tracker = sb.TelemetryTracker()
		monkeypatch.setattr(sb, "download_tracker", dl_tracker)
		monkeypatch.setattr(sb, "telemetry_tracker", tel_tracker)

		mgr = sb.BrowserSessionManager("http://127.0.0.1:9999")
		p1 = FakePage("https://example.com/1")
		p2 = FakePage("https://example.com/2")

		class FakeContext:
			def __init__(self, pages):
				self.pages = pages

		async def _fake_get_context():
			return FakeContext([p1, p2])

		monkeypatch.setattr(mgr, "get_context", _fake_get_context)

		pages = await mgr.get_pages()
		assert len(pages) == 2
		for p in pages:
			assert getattr(p, "_download_tracker_attached", False) is True
			assert getattr(p, "_telemetry_tracker_attached", False) is True

		p3 = FakePage("https://example.com/3")
		mgr._active_page = p3
		resolved = await mgr.resolve_page(-1)
		assert resolved is p3
		assert getattr(p3, "_download_tracker_attached", False) is True
		assert getattr(p3, "_telemetry_tracker_attached", False) is True

	_run(_scenario())


class FakeCdpSession:
	def __init__(self, enable_fails: bool = False, enable_delay: float = 0.0, enable_exc: Any = None):
		self.enable_fails = enable_fails
		self.enable_delay = enable_delay
		self.enable_exc = enable_exc
		self.detached = 0
		self.sent: list[str] = []
		self.handlers: dict[str, list] = {}

	async def send(self, method: str, params: Any = None) -> Any:
		self.sent.append(method)
		if method == "Runtime.enable":
			if self.enable_exc is not None:
				raise self.enable_exc
			if self.enable_delay:
				await asyncio.sleep(self.enable_delay)
			if self.enable_fails:
				raise RuntimeError("Runtime.enable rejected")
		return {}

	def on(self, event: str, cb) -> None:
		self.handlers.setdefault(event, []).append(cb)

	async def detach(self) -> None:
		self.detached += 1


class FakeCdpContext:
	def __init__(self, sessions: list[FakeCdpSession]):
		self._sessions = list(sessions)
		self.created: list[FakeCdpSession] = []

	async def new_cdp_session(self, page: Any) -> FakeCdpSession:
		session = self._sessions.pop(0)
		self.created.append(session)
		return session


def _cdp_page(page: FakePage, context: FakeCdpContext) -> FakePage:
	page.context = context
	return page


def test_console_capture_enable_failure_returns_false_no_registration(monkeypatch):
	async def _scenario():
		tracker = sb.TelemetryTracker()
		bad = FakeCdpSession(enable_fails=True)
		bad2 = FakeCdpSession(enable_fails=True)
		ctx = FakeCdpContext([bad, bad2])
		page = _cdp_page(FakePage("https://app.example/console"), ctx)

		assert await tracker.ensure_console_capture(page) is False
		assert tracker._cdp_sessions == {}
		assert bad.detached == 1

		assert await tracker.ensure_console_capture(page) is False
		assert len(ctx.created) == 2

	_run(_scenario())


def test_console_capture_enable_success_registers_and_captures(monkeypatch):
	async def _scenario():
		tracker = sb.TelemetryTracker()
		good = FakeCdpSession()
		ctx = FakeCdpContext([good])
		page = _cdp_page(FakePage("https://app.example/console"), ctx)
		tracker.attach(page)

		assert await tracker.ensure_console_capture(page) is True
		assert tracker._cdp_sessions[page] is good
		assert "Runtime.enable" in good.sent

		assert await tracker.ensure_console_capture(page) is True
		assert len(ctx.created) == 1

		for cb in good.handlers["Runtime.consoleAPICalled"]:
			cb({"type": "error", "args": [{"value": "boom"}], "stackTrace": [{"url": "app.js", "lineNumber": 7}]})
		page.emit("console", FakeConsoleMessage("log", "browser log"))
		entries, total = tracker.get_console(page)
		assert total == 2
		assert entries[0]["level"] == "error"
		assert entries[0]["text"] == "boom"
		assert entries[0]["location"] == "app.js:7"
		assert entries[1]["level"] == "log"
		assert entries[1]["text"] == "browser log"

	_run(_scenario())


def test_console_capture_enable_timeouterror_does_not_wedge(monkeypatch):
	async def _scenario():
		tracker = sb.TelemetryTracker()
		slow = FakeCdpSession(enable_exc=asyncio.TimeoutError())
		ctx = FakeCdpContext([slow, FakeCdpSession()])
		page = _cdp_page(FakePage("https://app.example/console"), ctx)

		assert await tracker.ensure_console_capture(page) is False
		assert tracker._cdp_sessions == {}

		assert await tracker.ensure_console_capture(page) is True

	_run(_scenario())


def test_console_capture_crash_and_close_drop_session(monkeypatch):
	async def _scenario():
		tracker = sb.TelemetryTracker()
		good = FakeCdpSession()
		ctx = FakeCdpContext([good, FakeCdpSession()])
		page = _cdp_page(FakePage("https://app.example/console"), ctx)

		assert await tracker.ensure_console_capture(page) is True
		assert page in tracker._cdp_sessions

		page.emit("crash")
		await asyncio.sleep(0)
		assert page not in tracker._cdp_sessions
		assert good.detached == 1

		assert await tracker.ensure_console_capture(page) is True
		assert page in tracker._cdp_sessions
		reattached = tracker._cdp_sessions[page]

		page.close_now()
		await asyncio.sleep(0)
		assert page not in tracker._cdp_sessions
		assert reattached.detached == 1

	_run(_scenario())


def test_console_capture_close_keeps_buffers_popped_and_no_cross_tab_leak(monkeypatch):
	async def _scenario():
		tracker = sb.TelemetryTracker()
		page = FakePage("https://app.example/console")
		tracker.attach(page)
		page.emit("console", FakeConsoleMessage("log", "pre-crash history"))
		assert tracker.get_console(page)[1] == 1

		page.emit("crash")
		assert tracker.get_console(page)[1] == 1

		page.close_now()
		assert tracker.get_console(page) == ([], 0)
		assert tracker._console == {}
		assert tracker._network == {}

	_run(_scenario())
