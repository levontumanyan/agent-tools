import asyncio
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _load_stealth_browser():
	script_path = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser"
	loader = SourceFileLoader("stealth_browser_under_test", str(script_path))
	spec = spec_from_loader("stealth_browser_under_test", loader)
	module = module_from_spec(spec)
	loader.exec_module(module)
	return module


sb = _load_stealth_browser()


class FakeLocator:
	def __init__(self, page, selector: str):
		self._page = page
		self._selector = selector

	@property
	def first(self):
		return self

	async def is_visible(self) -> bool:
		return self._selector in self._page._visible_selectors


class FakeResponse:
	def __init__(self, status: int = 200):
		self.status = status


class FakePage:
	def __init__(self, url: str = "about:blank", title: str = "Untitled", context=None):
		self.url = url
		self._title = title
		self._closed = False
		self._listeners: dict[str, list] = {}
		self._visible_selectors: set[str] = set()
		self.brought_to_front = 0
		self._context = context

	def is_closed(self) -> bool:
		return self._closed

	def on(self, event: str, callback) -> None:
		self._listeners.setdefault(event, []).append(callback)

	def emit(self, event: str) -> None:
		for cb in list(self._listeners.get(event, [])):
			cb(self)

	async def close(self) -> None:
		self._closed = True
		if self._context is not None and self in self._context.pages:
			self._context.pages.remove(self)
		self.emit("close")

	async def title(self) -> str:
		return self._title

	async def bring_to_front(self) -> None:
		self.brought_to_front += 1

	async def goto(self, url: str, timeout: int = 30000, wait_until: str = "domcontentloaded"):
		self.url = url
		return FakeResponse(200)

	def locator(self, selector: str) -> FakeLocator:
		return FakeLocator(self, selector)


class FakeContext:
	def __init__(self, pages: list[FakePage] | None = None):
		self.pages: list[FakePage] = []
		for p in pages or []:
			p._context = self
			self.pages.append(p)

	def is_closed(self) -> bool:
		return False

	async def new_page(self) -> FakePage:
		page = FakePage(url="about:blank", title="New Tab", context=self)
		self.pages.append(page)
		return page


class FakeBrowser:
	def __init__(self, connected: bool = True):
		self._connected = connected

	def is_connected(self) -> bool:
		return self._connected


def _make_session(pages: list[FakePage], headless: bool = False):
	mgr = sb.BrowserSessionManager("http://127.0.0.1:9222")
	ctx = FakeContext(pages)
	mgr._playwright = object()
	mgr._browser = FakeBrowser(connected=True)
	mgr._context = ctx
	mgr.headless = headless
	if pages:
		mgr.set_active_page(pages[0])
	return mgr, ctx


@pytest.fixture
def isolated_session(monkeypatch):
	def _setup(pages: list[FakePage], headless: bool = False):
		mgr, ctx = _make_session(pages, headless=headless)
		monkeypatch.setattr(sb, "session", mgr)
		return mgr, ctx

	return _setup


def test_stable_tab_ids_survive_closure_without_index_shift():
	async def _run():
		p1 = FakePage("https://a.example", "Tab A")
		p2 = FakePage("https://b.example", "Tab B")
		p3 = FakePage("https://c.example", "Tab C")
		mgr, ctx = _make_session([p1, p2, p3])

		pages = await mgr.get_pages()
		ids = [mgr.get_tab_id(p) for p in pages]
		assert ids == ["t1", "t2", "t3"]

		assert await mgr.resolve_page("t1") is p1
		assert await mgr.resolve_page("t2") is p2
		assert await mgr.resolve_page(" T3 ") is p3

		await p1.close()

		assert p1 not in mgr._page_to_id
		assert "t1" not in mgr._id_to_page

		assert await mgr.resolve_page("t2") is p2
		assert await mgr.resolve_page("t3") is p3
		assert await mgr.resolve_page(0) is p2
		assert await mgr.resolve_page(1) is p3

		p4 = await ctx.new_page()
		p4.url = "https://d.example"
		await mgr.get_pages()
		assert mgr.get_tab_id(p4) == "t4"

	asyncio.run(_run())


def test_closed_and_missing_tab_id_errors():
	async def _run():
		p1 = FakePage("https://a.example", "Tab A")
		p2 = FakePage("https://b.example", "Tab B")
		mgr, _ = _make_session([p1, p2])
		await mgr.get_pages()

		await p1.close()
		with pytest.raises(ValueError, match="Tab 't1' not found or was closed"):
			await mgr.resolve_page("t1")

		p2._closed = True
		with pytest.raises(ValueError, match="Tab 't2' not found or was closed"):
			await mgr.resolve_page("t2")
		assert "t2" not in mgr._id_to_page
		assert p2 not in mgr._page_to_id

		with pytest.raises(ValueError, match="Tab 't99' not found or was closed"):
			await mgr.resolve_page("t99")

	asyncio.run(_run())


def test_resolve_page_numeric_strings_and_backwards_compat():
	async def _run():
		p1 = FakePage("https://a.example", "Tab A")
		p2 = FakePage("https://b.example", "Tab B")
		mgr, _ = _make_session([p1, p2])
		mgr.set_active_page(p2)

		assert await mgr.resolve_page(-1) is p2
		assert await mgr.resolve_page("-1") is p2
		assert await mgr.resolve_page(0) is p1
		assert await mgr.resolve_page("0") is p1
		assert await mgr.resolve_page("1") is p2

		with pytest.raises(ValueError, match="Invalid tab index 5"):
			await mgr.resolve_page(5)
		with pytest.raises(ValueError, match="Invalid tab identifier"):
			await mgr.resolve_page("not-a-tab")

	asyncio.run(_run())


def test_session_close_clears_tab_registry_and_keeps_monotonic_ids():
	async def _run():
		p1 = FakePage("https://a.example", "Tab A")
		mgr, _ = _make_session([p1])
		assert mgr.get_tab_id(p1) == "t1"

		await mgr.close()
		assert mgr._page_to_id == {}
		assert mgr._id_to_page == {}

		p2 = FakePage("https://b.example", "Tab B")
		ctx = FakeContext([p2])
		mgr._playwright = object()
		mgr._browser = FakeBrowser(connected=True)
		mgr._context = ctx
		assert mgr.get_tab_id(p2) == "t2"

	asyncio.run(_run())


def test_status_displays_stable_tab_ids(isolated_session):
	async def _run():
		p1 = FakePage("https://one.example", "One")
		p2 = FakePage("https://two.example", "Two")
		mgr, _ = isolated_session([p1, p2], headless=False)
		mgr.set_active_page(p2)

		out = await sb.status()
		assert "[0 | t1] One - https://one.example" in out
		assert "[1 | t2] Two - https://two.example (ACTIVE in this session)" in out

		await p1.close()
		out_after = await sb.status()
		assert "[0 | t2] Two - https://two.example (ACTIVE in this session)" in out_after
		assert "t1" not in out_after

	asyncio.run(_run())


def test_new_tab_returns_stable_tab_id(isolated_session):
	async def _run():
		p1 = FakePage("https://existing.example", "Existing")
		mgr, ctx = isolated_session([p1], headless=True)
		await mgr.get_pages()

		out = await sb.new_tab("https://portal.example/login")
		assert "tab_id=t2" in out
		assert len(ctx.pages) == 2
		assert mgr.get_tab_id(ctx.pages[1]) == "t2"

	asyncio.run(_run())


def test_wait_for_human_url_contains_and_osascript_notify(isolated_session, monkeypatch):
	async def _run():
		p1 = FakePage("https://app.example/login", "Sign In")
		isolated_session([p1], headless=False)

		popen_calls = []
		fake_proc = MagicMock()
		fake_proc.poll.return_value = 0

		def _fake_popen(cmd, **kwargs):
			popen_calls.append((cmd, kwargs))
			return fake_proc

		monkeypatch.setattr(sb.subprocess, "Popen", _fake_popen)

		async def _complete_login():
			await asyncio.sleep(0.03)
			p1.url = "https://app.example/dashboard"
			p1._title = "Dashboard"

		driver = asyncio.create_task(_complete_login())
		res = await sb.wait_for_human(
			reason='Finish "2FA" login',
			url_contains="/dashboard",
			timeout_s=2,
			poll_interval_s=0.01,
			notify=True,
			tab="t1",
		)
		await driver

		assert "Human handoff completed" in res
		assert "url_contains='/dashboard'" in res
		assert "[tab_id=t1]" in res
		assert "Title: 'Dashboard'" in res
		assert "URL: https://app.example/dashboard" in res
		assert p1.brought_to_front == 1

		assert len(popen_calls) == 1
		cmd, _ = popen_calls[0]
		assert cmd[0] == "osascript"
		assert cmd[1] == "-e"
		assert 'Finish \\"2FA\\" login' in cmd[2]
		assert 'with title "stealth-browser"' in cmd[2]

	asyncio.run(_run())


def test_wait_for_human_url_not_contains(isolated_session, monkeypatch):
	async def _run():
		p1 = FakePage("https://sso.example/challenge?step=2fa", "2FA")
		isolated_session([p1], headless=False)
		popen_mock = MagicMock()
		monkeypatch.setattr(sb.subprocess, "Popen", popen_mock)

		async def _finish():
			await asyncio.sleep(0.03)
			p1.url = "https://sso.example/home"
			p1._title = "Home"

		driver = asyncio.create_task(_finish())
		res = await sb.wait_for_human(
			url_not_contains="/challenge",
			timeout_s=2,
			poll_interval_s=0.01,
			notify=False,
		)
		await driver

		assert "Human handoff completed" in res
		assert "url_not_contains='/challenge'" in res
		assert "URL: https://sso.example/home" in res
		popen_mock.assert_not_called()

	asyncio.run(_run())


def test_wait_for_human_selector_visible(isolated_session, monkeypatch):
	async def _run():
		p1 = FakePage("https://bank.example/portal", "Portal")
		isolated_session([p1], headless=False)
		monkeypatch.setattr(sb.subprocess, "Popen", MagicMock(side_effect=FileNotFoundError("no osascript")))

		async def _reveal():
			await asyncio.sleep(0.03)
			p1._visible_selectors.add("#account-summary")

		driver = asyncio.create_task(_reveal())
		res = await sb.wait_for_human(
			url_contains="/never-matches",
			selector="#account-summary",
			timeout_s=2,
			poll_interval_s=0.01,
			notify=True,
		)
		await driver

		assert "Human handoff completed" in res
		assert "selector='#account-summary' visible" in res
		assert "[tab_id=t1]" in res

	asyncio.run(_run())


def test_wait_for_human_default_url_change(isolated_session, monkeypatch):
	async def _run():
		p1 = FakePage("https://captcha.example/verify", "Verify")
		isolated_session([p1], headless=False)
		monkeypatch.setattr(sb.subprocess, "Popen", MagicMock())

		async def _redirect():
			await asyncio.sleep(0.03)
			p1.url = "https://captcha.example/verified"
			p1._title = "Verified"

		driver = asyncio.create_task(_redirect())
		res = await sb.wait_for_human(timeout_s=2, poll_interval_s=0.01, notify=False)
		await driver

		assert "Human handoff completed" in res
		assert "URL changed from 'https://captcha.example/verify'" in res
		assert "URL: https://captcha.example/verified" in res

	asyncio.run(_run())


def test_wait_for_human_timeout(isolated_session, monkeypatch):
	async def _run():
		p1 = FakePage("https://app.example/login", "Login")
		isolated_session([p1], headless=False)
		monkeypatch.setattr(sb.subprocess, "Popen", MagicMock())

		res = await sb.wait_for_human(
			reason="Solve CAPTCHA",
			url_contains="/dashboard",
			timeout_s=0.05,
			poll_interval_s=0.01,
			notify=False,
		)

		assert "Timed out after" in res
		assert "Solve CAPTCHA" in res
		assert "[tab_id=t1]" in res
		assert "Title: 'Login'" in res
		assert "URL: https://app.example/login" in res

	asyncio.run(_run())


def test_wait_for_human_switches_headless_to_headed_and_reresolves_tab(isolated_session, monkeypatch):
	async def _run():
		p1 = FakePage("https://news.example", "News")
		p2 = FakePage("https://bank.example/2fa", "Bank 2FA")
		mgr, _ = isolated_session([p1, p2], headless=True)
		await mgr.get_pages()
		assert mgr.get_tab_id(p2) == "t2"

		restart_calls = []
		reopened_p1 = FakePage("https://news.example", "News")
		reopened_p2 = FakePage("https://bank.example/2fa", "Bank 2FA")

		async def _fake_restart_browser(headless=None, url=None):
			restart_calls.append((headless, url))
			await mgr.close()
			mgr.headless = bool(headless)
			mgr._playwright = object()
			mgr._browser = FakeBrowser(connected=True)
			mgr._context = FakeContext([reopened_p1, reopened_p2])
			mgr.set_active_page(reopened_p1)
			return "Browser restarted successfully in Headed mode on tab [0]"

		monkeypatch.setattr(sb, "restart_browser", _fake_restart_browser)
		monkeypatch.setattr(sb.subprocess, "Popen", MagicMock())

		async def _finish_2fa():
			await asyncio.sleep(0.03)
			reopened_p2.url = "https://bank.example/accounts"
			reopened_p2._title = "Accounts"

		driver = asyncio.create_task(_finish_2fa())
		res = await sb.wait_for_human(
			reason="Approve bank 2FA",
			url_contains="/accounts",
			timeout_s=2,
			poll_interval_s=0.01,
			notify=False,
			tab="t2",
		)
		await driver

		assert restart_calls == [(False, None)]
		assert mgr.headless is False
		assert reopened_p2.brought_to_front == 1
		assert mgr._active_page is reopened_p2
		new_id = mgr.get_tab_id(reopened_p2)
		assert new_id != "t2"
		assert "Human handoff completed" in res
		assert "(switched to headed mode)" in res
		assert f"[tab_id={new_id}]" in res
		assert "Title: 'Accounts'" in res
		assert "URL: https://bank.example/accounts" in res

	asyncio.run(_run())


def test_wait_for_human_handles_tab_closed_mid_wait(isolated_session, monkeypatch):
	async def _run():
		p1 = FakePage("https://app.example/login", "Login")
		isolated_session([p1], headless=False)
		monkeypatch.setattr(sb.subprocess, "Popen", MagicMock())

		async def _close_tab():
			await asyncio.sleep(0.02)
			await p1.close()

		driver = asyncio.create_task(_close_tab())
		res = await sb.wait_for_human(
			url_contains="/done",
			timeout_s=2,
			poll_interval_s=0.01,
			notify=False,
		)
		await driver

		assert "tab t1 was closed" in res

	asyncio.run(_run())
