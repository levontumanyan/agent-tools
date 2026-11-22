import asyncio
import importlib.machinery
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_stealth_browser_module():
	script_path = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser"
	loader = importlib.machinery.SourceFileLoader("stealth_browser_mod", str(script_path))
	spec = importlib.util.spec_from_loader(loader.name, loader)
	mod = importlib.util.module_from_spec(spec)
	loader.exec_module(mod)
	return mod


sb = _load_stealth_browser_module()


class FakeLocator:
	def __init__(self, count: int = 1, visible: bool = True, visible_by_idx: dict[int, bool] | None = None):
		self._count = count
		self._visible = visible
		self._visible_by_idx = visible_by_idx or {}
		self.click = AsyncMock()
		self.fill = AsyncMock()
		self.type = AsyncMock()
		self.press = AsyncMock()
		self.select_option = AsyncMock()
		self.wait_for = AsyncMock()
		self.screenshot = AsyncMock()
		self.nth_children: dict[int, FakeLocator] = {}

	@property
	def first(self):
		return self

	def nth(self, idx: int):
		if idx not in self.nth_children:
			vis = self._visible_by_idx.get(idx, self._visible)
			self.nth_children[idx] = FakeLocator(count=1, visible=vis)
		return self.nth_children[idx]

	async def count(self) -> int:
		return self._count

	async def is_visible(self) -> bool:
		return self._visible


class FakeFrame:
	def __init__(self, locators: dict[str, FakeLocator] | None = None, roles: dict[tuple[str, str], FakeLocator] | None = None, texts: dict[str, FakeLocator] | None = None):
		self._locators = locators or {}
		self._roles = roles or {}
		self._texts = texts or {}
		self.locator_calls: list[str] = []

	def locator(self, selector: str) -> FakeLocator:
		self.locator_calls.append(selector)
		if selector not in self._locators:
			self._locators[selector] = FakeLocator(count=0)
		return self._locators[selector]

	def get_by_role(self, role: str, name: str = "") -> FakeLocator:
		return self._roles.get((role, name), FakeLocator(count=0))

	def get_by_text(self, text: str) -> FakeLocator:
		return self._texts.get(text, FakeLocator(count=0))


class FakePage(FakeFrame):
	def __init__(self, url: str = "https://example.test/app", title: str = "Example", frames: list[FakeFrame] | None = None, **kwargs):
		super().__init__(**kwargs)
		self.url = url
		self._title = title
		self.main_frame = self
		self.frames = [self] + (frames or [])
		self.evaluate = AsyncMock(return_value=[])
		self.screenshot = AsyncMock()
		self.keyboard = MagicMock()
		self.keyboard.press = AsyncMock()

	async def title(self) -> str:
		return self._title


@pytest.fixture
def patch_page(monkeypatch):
	def _install(page: FakePage):
		monkeypatch.setattr(sb.session, "resolve_page", AsyncMock(return_value=page))
		return page
	return _install


def test_normalize_ref_and_selector():
	assert sb._normalize_ref("e5") == "e5"
	assert sb._normalize_ref("@e5") == "e5"
	assert sb._normalize_ref("  @e12  ") == "e12"
	assert sb._normalize_ref("@") == ""
	assert sb._normalize_ref("   ") == ""
	assert sb._ref_to_selector("e5") == '[data-sb-ref="e5"]'
	assert sb._ref_to_selector('a"b\\c') == '[data-sb-ref="a\\"b\\\\c"]'


def test_snapshot_passes_flags_and_formats_refs_and_hrefs(patch_page):
	long_url = "https://bank.example.com/statements/" + "a" * 140
	page = FakePage(url="https://bank.example.com/dashboard")
	sample_items = {
		"totalMatched": 3,
		"items": [
			{
				"index": 0,
				"ref": "e0",
				"tag": "button",
				"selector": "#login-btn",
				"text": "Sign In",
				"href": "",
				"attrs": "#login-btn type=submit",
			},
			{
				"index": 1,
				"ref": "e1",
				"tag": "a",
				"selector": '[data-sb-ref="e1"]',
				"text": "Download | Statement",
				"href": long_url,
				"attrs": "[iframe]",
			},
			{
				"index": 2,
				"ref": "e2",
				"tag": "button",
				"selector": '[data-sb-ref="e2"]',
				"text": "Shadow Save",
				"href": "",
				"attrs": "[shadow]",
			},
		],
	}
	page.evaluate = AsyncMock(return_value=sample_items)
	patch_page(page)

	out = asyncio.run(
		sb.snapshot(selector="#main", max_elements=50, tab=0, include_shadow=False, include_iframes=True)
	)

	page.evaluate.assert_awaited_once()
	js_arg, payload = page.evaluate.call_args.args
	assert "shadowRoot" in js_arg
	assert "contentDocument" in js_arg
	assert "data-sb-ref" in js_arg
	assert "querySelectorAll" in js_arg
	assert payload == {
		"targetSelector": "#main",
		"maxElements": 50,
		"includeShadow": False,
		"includeIframes": True,
		"includeHrefs": False,
		"filter": "",
		"viewportOnly": False,
	}

	assert "[e0] <button> #login-btn \"Sign In\" (type=submit)" in out
	assert "#login-btn (type=submit)" not in out or "#login-btn #login-btn" not in out
	assert '[data-sb-ref="e1"]' not in out
	assert "href=" not in out
	assert '[e1] <a> "Download | Statement" ([iframe])' in out
	assert '[e2] <button> "Shadow Save" ([shadow])' in out

	out_hrefs = asyncio.run(sb.snapshot(include_hrefs=True))
	assert "href=https://bank.example.com/statements/" in out_hrefs
	assert "..." in out_hrefs
	assert long_url not in out_hrefs


def test_click_by_ref_and_at_ref_and_force(patch_page):
	loc = FakeLocator(count=1)
	page = FakePage(locators={'[data-sb-ref="e12"]': loc})
	patch_page(page)

	res1 = asyncio.run(sb.click(ref="e12"))
	res2 = asyncio.run(sb.click(ref="@e12", force=True, timeout_ms=2500))

	assert "Clicked element matching ref 'e12'" in res1
	assert "(force)" not in res1
	assert "Clicked element matching ref 'e12' (force)" in res2
	assert loc.click.await_count == 2
	assert loc.click.call_args_list[0].kwargs == {"timeout": 5000}
	assert loc.click.call_args_list[1].kwargs == {"timeout": 2500, "force": True}


def test_click_ref_inside_iframe_and_selector_ref(patch_page):
	iframe_loc = FakeLocator(count=1)
	iframe = FakeFrame(locators={'[data-sb-ref="e7"]': iframe_loc})
	page = FakePage(frames=[iframe])
	patch_page(page)

	res1 = asyncio.run(sb.click(ref="@e7"))
	res2 = asyncio.run(sb.click(selector='[data-sb-ref="e7"]'))

	assert "Clicked element matching ref 'e7'" in res1
	assert "Clicked element matching '[data-sb-ref=\"e7\"]'" in res2
	assert iframe_loc.click.await_count == 2


def test_click_ref_js_fallback_when_unmatched_and_not_on_matched_non_force(patch_page):
	unmatched_loc = FakeLocator(count=0)
	unmatched_loc.click = AsyncMock(side_effect=RuntimeError("not found"))
	page = FakePage(locators={'[data-sb-ref="e9"]': unmatched_loc})
	page.evaluate = AsyncMock(return_value=True)
	patch_page(page)

	res = asyncio.run(sb.click(ref="e9"))
	assert "Clicked element matching ref 'e9'" in res
	page.evaluate.assert_awaited_once()
	assert page.evaluate.call_args.args[1] == {"refId": "e9"}

	matched_loc = FakeLocator(count=1)
	matched_loc.click = AsyncMock(side_effect=RuntimeError("intercepted by overlay"))
	page2 = FakePage(locators={'[data-sb-ref="e9"]': matched_loc})
	page2.evaluate = AsyncMock(return_value=True)
	patch_page(page2)

	res_fail = asyncio.run(sb.click(ref="e9", force=False))
	assert "Error clicking element ref 'e9': intercepted by overlay" in res_fail
	page2.evaluate.assert_not_awaited()


def test_click_by_text_prefers_role_and_visible_match(patch_page):
	btn_loc = FakeLocator(count=1)
	text_loc = FakeLocator(count=1)
	page = FakePage(
		roles={("button", "Continue"): btn_loc},
		texts={"Continue": text_loc},
	)
	patch_page(page)

	res = asyncio.run(sb.click(text="Continue", force=True))
	assert "Clicked element matching text 'Continue' (force)" in res
	btn_loc.click.assert_awaited_once_with(timeout=5000, force=True)
	text_loc.click.assert_not_awaited()

	multi_text = FakeLocator(count=2, visible_by_idx={0: False, 1: True})
	page2 = FakePage(texts={"Accept": multi_text})
	patch_page(page2)

	res2 = asyncio.run(sb.click(text="Accept"))
	assert "Clicked element matching text 'Accept'" in res2
	multi_text.nth(1).click.assert_awaited_once_with(timeout=5000)
	multi_text.nth(0).click.assert_not_awaited()


def test_click_and_type_validation_and_backwards_compat(patch_page):
	btn = FakeLocator(count=1)
	inp = FakeLocator(count=1)
	ref_inp = FakeLocator(count=1)
	iframe = FakeFrame(locators={'[data-sb-ref="e4"]': ref_inp})
	page = FakePage(locators={"#submit": btn, "#email": inp}, frames=[iframe])
	patch_page(page)

	assert "provide at least one" in asyncio.run(sb.click())
	assert "provide at least one" in asyncio.run(sb.click(ref="@"))
	assert "provide either" in asyncio.run(sb.type(text="abc"))
	assert "provide either" in asyncio.run(sb.type(ref="   ", text="abc"))

	assert "Clicked element matching '#submit'" in asyncio.run(sb.click("#submit"))
	btn.click.assert_awaited_once_with(timeout=5000)

	res_type_sel = asyncio.run(sb.type("#email", "user@test.com", clear_first=True, press_enter=True))
	assert "Typed text into '#email' and pressed Enter" in res_type_sel
	inp.fill.assert_awaited_once_with("user@test.com", timeout=5000)
	inp.press.assert_awaited_once_with("Enter")

	res_type_ref = asyncio.run(sb.type(ref="@e4", text="hello", clear_first=False, press_enter=False))
	assert "Typed text into ref 'e4'" in res_type_ref
	ref_inp.type.assert_awaited_once_with("hello", timeout=5000)


def test_batch_supports_ref_force_and_backwards_compat(patch_page):
	loc_e1 = FakeLocator(count=1)
	loc_e2 = FakeLocator(count=1)
	loc_e3 = FakeLocator(count=1)
	loc_e4 = FakeLocator(count=1)
	loc_e5 = FakeLocator(count=1)
	loc_css = FakeLocator(count=1)
	page = FakePage(
		locators={
			'[data-sb-ref="e1"]': loc_e1,
			'[data-sb-ref="e2"]': loc_e2,
			'[data-sb-ref="e3"]': loc_e3,
			'[data-sb-ref="e4"]': loc_e4,
			'[data-sb-ref="e5"]': loc_e5,
			"#legacy": loc_css,
		}
	)
	patch_page(page)

	out = asyncio.run(
		sb.batch(
			[
				{"action": "click", "ref": "@e1", "force": True, "timeout_ms": 2000},
				{"action": "fill", "ref": "e2", "text": "alice", "force": True},
				{"action": "type", "ref": "e3", "text": "bob", "press_enter": True, "force": True},
				{"action": "select", "ref": "e4", "value": "CA", "force": True},
				{"action": "wait_for", "ref": "e5", "state": "visible", "timeout_ms": 1500},
				{"action": "click", "selector": "#legacy"},
				{"action": "click"},
			]
		)
	)

	assert "Batch completed (7 steps" in out
	assert "[0] click ref 'e1' (force): OK" in out
	assert "[1] fill ref 'e2': OK" in out
	assert "[2] type ref 'e3' (with Enter): OK" in out
	assert "[3] select ref 'e4' option 'CA': OK" in out
	assert "[4] wait_for ref 'e5' (visible): OK" in out
	assert "[5] click '#legacy': OK" in out
	assert "[6] click: SKIPPED" in out

	loc_e1.click.assert_awaited_once_with(timeout=2000, force=True)
	loc_e2.fill.assert_awaited_once_with("alice", timeout=4000, force=True)
	loc_e3.click.assert_awaited_once_with(timeout=4000, force=True)
	loc_e3.type.assert_awaited_once_with("bob", timeout=4000)
	loc_e3.press.assert_awaited_once_with("Enter")
	loc_e4.select_option.assert_awaited_once_with("CA", timeout=4000, force=True)
	loc_e5.wait_for.assert_awaited_once_with(state="visible", timeout=1500)
	loc_css.click.assert_awaited_once_with(timeout=4000)


def test_screenshot_full_page_selector_ref(patch_page):
	chart_loc = FakeLocator(count=1)
	ref_loc = FakeLocator(count=1)
	iframe = FakeFrame(locators={'[data-sb-ref="e6"]': ref_loc})
	page = FakePage(locators={"#chart": chart_loc}, frames=[iframe])
	patch_page(page)

	res_full = asyncio.run(sb.screenshot(save_path="/tmp/full.png", full_page=True))
	assert "Mode: full_page" in res_full
	page.screenshot.assert_awaited_once_with(path="/tmp/full.png", full_page=True)

	res_sel = asyncio.run(sb.screenshot(save_path="/tmp/chart.png", selector="#chart"))
	assert "Element: #chart" in res_sel
	chart_loc.screenshot.assert_awaited_once_with(path="/tmp/chart.png")

	res_ref = asyncio.run(sb.screenshot(save_path="/tmp/ref.png", ref="@e6"))
	assert "Element: ref e6" in res_ref
	ref_loc.screenshot.assert_awaited_once_with(path="/tmp/ref.png")


def test_screenshot_annotate_auto_snapshots_and_always_cleans_up(patch_page):
	calls: list[str] = []

	async def fake_eval(script, arg=None):
		if script == sb._JS_ANNOTATE_OVERLAY:
			calls.append("annotate")
			return 0 if calls.count("annotate") == 1 else 3
		if script == sb._SNAPSHOT_JS:
			calls.append("snapshot")
			return [{"index": 0, "ref": "e0", "tag": "button", "selector": "#ok", "text": "OK", "href": "", "attrs": ""}]
		if script == sb._JS_REMOVE_OVERLAY:
			calls.append("remove")
			return None
		return None

	page = FakePage()
	page.evaluate = AsyncMock(side_effect=fake_eval)
	patch_page(page)

	res = asyncio.run(sb.screenshot(save_path="/tmp/annotated.png", annotate=True, full_page=True))
	assert "Annotated: 3 ref(s)" in res
	assert calls == ["annotate", "snapshot", "annotate", "remove"]
	page.screenshot.assert_awaited_once_with(path="/tmp/annotated.png", full_page=True)

	calls.clear()
	page.screenshot = AsyncMock(side_effect=RuntimeError("disk full"))
	res_err = asyncio.run(sb.screenshot(save_path="/tmp/fail.png", annotate=True))
	assert "Error taking screenshot: disk full" in res_err
	assert calls[-1] == "remove"
