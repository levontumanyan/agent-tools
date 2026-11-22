import asyncio
import importlib.machinery
import importlib.util
from pathlib import Path
from typing import Any, Callable, Optional

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "stealth-browser"


def _load_stealth_browser_module():
	loader = importlib.machinery.SourceFileLoader("stealth_browser_extract_mod", str(SCRIPT_PATH))
	spec = importlib.util.spec_from_loader("stealth_browser_extract_mod", loader)
	mod = importlib.util.module_from_spec(spec)
	loader.exec_module(mod)
	return mod


sb = _load_stealth_browser_module()


class FakePage:
	def __init__(self, url: str = "https://example.com/results"):
		self.url = url
		self._closed = False
		self.evaluate_handler: Optional[Callable[[str, Any], Any]] = None
		self.evaluate_calls: list[tuple[str, Any]] = []

	def is_closed(self) -> bool:
		return self._closed

	async def evaluate(self, script: str, arg: Any = None) -> Any:
		self.evaluate_calls.append((script, arg))
		if self.evaluate_handler is None:
			raise AssertionError("No evaluate_handler configured")
		res = self.evaluate_handler(script, arg)
		if asyncio.iscoroutine(res):
			return await res
		return res


def _run(coro):
	return asyncio.run(coro)


def test_normalize_extract_fields_shorthand_forms():
	norm = sb._normalize_extract_fields({
		"plain_text": "text",
		"sub_text": ".title",
		"mode_text": "text:.title",
		"attr_container": "@href",
		"attr_sub": "@href a.link",
		"html_sub": "html:.thumb",
		"inner_sub": "inner_html:.body",
	})
	assert norm == {
		"plain_text": {"mode": "text", "selector": "", "attr": ""},
		"sub_text": {"mode": "text", "selector": ".title", "attr": ""},
		"mode_text": {"mode": "text", "selector": ".title", "attr": ""},
		"attr_container": {"mode": "attr", "selector": "", "attr": "href"},
		"attr_sub": {"mode": "attr", "selector": "a.link", "attr": "href"},
		"html_sub": {"mode": "html", "selector": ".thumb", "attr": ""},
		"inner_sub": {"mode": "inner_html", "selector": ".body", "attr": ""},
	}


def test_normalize_extract_fields_object_form_and_rejects_invalid():
	norm = sb._normalize_extract_fields({
		"price": {"selector": ".price", "mode": "text"},
		"link": {"mode": "attr", "attr": "href", "selector": "a"},
	})
	assert norm["price"] == {"mode": "text", "selector": ".price", "attr": ""}
	assert norm["link"] == {"mode": "attr", "selector": "a", "attr": "href"}

	assert sb._normalize_extract_fields({}) is None
	assert sb._normalize_extract_fields(None) is None
	assert sb._normalize_extract_fields({"bad": {"mode": "banana"}}) is None
	assert sb._normalize_extract_fields({"bad": {"mode": "attr"}}) is None
	assert sb._normalize_extract_fields({"bad": 42}) is None
	assert sb._normalize_extract_fields({"bad": "   "}) is None
	assert sb._normalize_extract_fields({"": "text"}) is None
	assert sb._normalize_extract_fields({f"f{i}": "text" for i in range(sb._EXTRACT_MAX_FIELDS + 1)}) is None


def test_normalize_extract_fields_does_not_split_css_colon_selectors():
	norm = sb._normalize_extract_fields({"link": "a[href^='https']"})
	assert norm["link"] == {"mode": "text", "selector": "a[href^='https']", "attr": ""}


def test_extract_tool_formats_rows_and_null_tolerant_fields(monkeypatch):
	page = FakePage()

	def handler(script, arg):
		assert script == sb._EXTRACT_JS
		assert arg["containerSelector"] == ".result-card"
		assert arg["fields"]["title"] == {"mode": "text", "selector": ".card-link", "attr": ""}
		assert arg["fields"]["link"] == {"mode": "attr", "selector": ".card-link", "attr": "href"}
		assert arg["limit"] == 20
		return {
			"url": page.url,
			"title": "Results",
			"total_matched": 3,
			"returned": 2,
			"rows": [
				{"_index": 0, "title": "Card Alpha", "link": "/a", "price": "US$10.99"},
				{"_index": 1, "title": "Card Beta", "link": "/b", "price": None},
			],
		}

	page.evaluate_handler = handler
	monkeypatch.setattr(sb.session, "resolve_page", _make_resolver(page))

	out = _run(sb.extract(
		container_selector=".result-card",
		fields={"title": "text:.card-link", "link": "@href .card-link", "price": ".card-price"},
	))
	assert "Extracted 2 row(s) from '.result-card'" in out
	assert '"total_matched": 3' in out
	assert '"price": "US$10.99"' in out
	assert '"price": null' in out
	assert '"title": "Card Beta"' in out


def _make_resolver(page):
	async def _resolve(tab=-1):
		return page
	return _resolve


def test_extract_tool_no_matches(monkeypatch):
	page = FakePage()

	def handler(script, arg):
		return {"url": page.url, "title": "Results", "total_matched": 0, "returned": 0, "rows": []}

	page.evaluate_handler = handler
	monkeypatch.setattr(sb.session, "resolve_page", _make_resolver(page))

	out = _run(sb.extract(container_selector=".nothing", fields={"t": "text"}))
	assert out.startswith("No elements matched '.nothing'")
	assert "total_matched=0" in out


def test_extract_tool_max_length_truncation(monkeypatch):
	page = FakePage()

	def handler(script, arg):
		return {
			"url": page.url,
			"title": "Big",
			"total_matched": 1,
			"returned": 1,
			"rows": [{"_index": 0, "blob": "x" * 5000}],
		}

	page.evaluate_handler = handler
	monkeypatch.setattr(sb.session, "resolve_page", _make_resolver(page))

	out = _run(sb.extract(container_selector=".card", fields={"blob": "text"}, max_length=300))
	assert "[Truncated:" in out
	assert out.count("x") < 400


def test_extract_tool_limit_clamped_and_scoping_flags(monkeypatch):
	page = FakePage()
	captured = {}

	def handler(script, arg):
		captured.update(arg)
		return {"url": page.url, "title": "T", "total_matched": 1, "returned": 1,
			"rows": [{"_index": 0, "t": "ok"}]}

	page.evaluate_handler = handler
	monkeypatch.setattr(sb.session, "resolve_page", _make_resolver(page))

	_run(sb.extract(container_selector=".card", fields={"t": "text"}, limit=9999,
		include_shadow=False, include_iframes=False))
	assert captured["limit"] == sb._EXTRACT_MAX_LIMIT
	assert captured["includeShadow"] is False
	assert captured["includeIframes"] is False


def test_extract_tool_validation_errors(monkeypatch):
	page = FakePage()
	monkeypatch.setattr(sb.session, "resolve_page", _make_resolver(page))

	bad_fields = _run(sb.extract(container_selector=".card", fields={}))
	assert bad_fields.startswith("Error extracting rows:")
	assert "fields" in bad_fields

	bad_mode = _run(sb.extract(container_selector=".card", fields={"x": {"mode": "nope"}}))
	assert bad_mode.startswith("Error extracting rows:")

	bad_sel = _run(sb.extract(container_selector="", fields={"x": "text"}))
	assert "container_selector" in bad_sel


def test_extract_tool_evaluate_failure_and_timeout(monkeypatch):
	page = FakePage()

	def boom(script, arg):
		raise RuntimeError("Execution context was destroyed")

	page.evaluate_handler = boom
	monkeypatch.setattr(sb.session, "resolve_page", _make_resolver(page))

	out = _run(sb.extract(container_selector=".card", fields={"t": "text"}))
	assert "Error extracting rows: Execution context was destroyed" in out

	page.evaluate_handler = lambda script, arg: {
		"url": page.url, "title": "T", "total_matched": 1, "returned": 1,
		"rows": [{"_index": 0, "t": "ok"}],
	}
	monkeypatch.setattr(sb.asyncio, "wait_for", _fake_wait_for_timeout)

	out_timeout = _run(sb.extract(container_selector=".card", fields={"t": "text"}))
	assert "Timed out after 15000ms" in out_timeout


async def _fake_wait_for_timeout(coro, timeout=None):
	await coro
	raise asyncio.TimeoutError()


def test_extract_tool_unexpected_result_shape(monkeypatch):
	page = FakePage()
	page.evaluate_handler = lambda script, arg_val: "not-a-dict"
	monkeypatch.setattr(sb.session, "resolve_page", _make_resolver(page))

	out = _run(sb.extract(container_selector=".card", fields={"t": "text"}))
	assert "unexpected result from page (str)" in out
