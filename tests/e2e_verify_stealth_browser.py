#!/usr/bin/env python3
"""Real end-to-end MCP stdio + live headless Chromium test harness for stealth-browser."""

import asyncio
import http.server
import os
import re
import shutil
import socketserver
import sys
import tempfile
import threading
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PDF_BYTES = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"

FIXTURE_HTML = """<!doctype html>
<html>
<head>
	<title>E2E Test Portal</title>
	<style>
		body { font-family: sans-serif; height: 2200px; }
		.dup-btn { padding: 8px 12px; margin: 4px; }
		#overlay-wrap { position: relative; display: inline-block; }
		#overlay-cover {
			position: absolute; inset: 0; background: rgba(0,0,0,0.2); z-index: 10;
		}
	</style>
</head>
<body>
	<h1>Portal Home</h1>
	<a id="stmt-link" href="/statement.pdf" download="test-statement.pdf">Download Statement PDF</a>
	<a href="/account/details">Account Details</a>
	<div>
		<button class="dup-btn" onclick="document.body.dataset.clicked='first'">First Action</button>
		<button class="dup-btn" onclick="document.body.dataset.clicked='second'">Second Action</button>
	</div>
	<div id="overlay-wrap">
		<button id="covered-btn" onclick="document.body.dataset.covered='yes'">Covered Button</button>
		<div id="overlay-cover"></div>
	</div>
	<input id="search-box" type="text" placeholder="Type here" />
	<button id="alert-btn" onclick="alert('Session warning!'); document.body.dataset.afterAlert='yes';">Trigger Alert</button>
	<button id="delayed-btn" onclick="setTimeout(() => {
		const d = document.createElement('div');
		d.id = 'late-card';
		d.textContent = 'Flight YUL to LIM 25000 pts';
		document.body.appendChild(d);
	}, 400)">Load Delayed</button>
	<div id="shadow-host"></div>
	<div id="results">
		<div class="result-card" data-id="A1"><a class="card-link" href="/account/details">Card Alpha</a><span class="card-price">US$10.99</span></div>
		<div class="result-card" data-id="B2"><a class="card-link" href="/statement.pdf">Card Beta</a><span class="card-price">US$20.50</span></div>
		<div class="result-card" data-id="C3"><a class="card-link" href="/account/details">Card Gamma</a></div>
	</div>
	<iframe id="inner-frame" src="/iframe" width="300" height="80"></iframe>
	<embed id="pdf-embed" type="application/pdf" width="200" height="50" />
	<script>
		const host = document.getElementById('shadow-host');
		const sr = host.attachShadow({ mode: 'open' });
		sr.innerHTML = '<button id="shadow-btn">Shadow Confirm</button>';
		sr.getElementById('shadow-btn').addEventListener('click', () => { document.body.dataset.shadow = 'yes'; });

		const blob = new Blob(['%PDF-1.4\\n%blob-pdf-test\\n%%EOF\\n'], { type: 'application/pdf' });
		window.__blobUrl = URL.createObjectURL(blob);
		document.getElementById('pdf-embed').src = window.__blobUrl;
		document.body.dataset.blob = window.__blobUrl;

		window.__NEXT_DATA__ = { page: '/portal', props: { pageProps: { user: 'levon', tier: 'gold' } } };
		window.store = { getState: () => ({ portfolio: { cash: 12345, currency: 'CAD' } }) };
		window.__CUSTOM_PAGE_GLOBAL__ = { secretToken: 'main-world-ok' };

		console.log('portal-boot-ok');
		console.warn('portal-minor-warn');
		console.error('portal-test-error');
		fetch('/api/portfolio').catch(() => {});
		fetch('/api/missing-404').catch(() => {});
	</script>
</body>
</html>
"""

IFRAME_HTML = """<!doctype html>
<html><body>
	<button id="frame-btn" onclick="window.parent.document.body.dataset.frame = 'yes'">Iframe Submit</button>
</body></html>
"""

PAGE2_HTML = """<!doctype html>
<html><head><title>Dashboard Page</title></head>
<body><h1>Welcome Dashboard</h1><div id="dash-ready">Signed In OK</div></body></html>
"""


class FixtureHandler(http.server.BaseHTTPRequestHandler):
	def log_message(self, fmt, *args):
		pass

	def do_GET(self):
		if self.path == "/" or self.path.startswith("/?"):
			self.send_response(200)
			self.send_header("Content-Type", "text/html; charset=utf-8")
			self.end_headers()
			self.wfile.write(FIXTURE_HTML.encode())
		elif self.path == "/iframe":
			self.send_response(200)
			self.send_header("Content-Type", "text/html; charset=utf-8")
			self.end_headers()
			self.wfile.write(IFRAME_HTML.encode())
		elif self.path == "/dashboard":
			self.send_response(200)
			self.send_header("Content-Type", "text/html; charset=utf-8")
			self.end_headers()
			self.wfile.write(PAGE2_HTML.encode())
		elif self.path == "/statement.pdf":
			self.send_response(200)
			self.send_header("Content-Type", "application/pdf")
			self.send_header("Content-Disposition", 'attachment; filename="test-statement.pdf"')
			self.send_header("Content-Length", str(len(PDF_BYTES)))
			self.end_headers()
			self.wfile.write(PDF_BYTES)
		elif self.path == "/api/portfolio":
			body = b'{"account":"TFSA","balance":42000}'
			self.send_response(200)
			self.send_header("Content-Type", "application/json")
			self.send_header("Content-Length", str(len(body)))
			self.end_headers()
			self.wfile.write(body)
		elif self.path == "/api/missing-404":
			body = b'{"error":"not found"}'
			self.send_response(404)
			self.send_header("Content-Type", "application/json")
			self.end_headers()
			self.wfile.write(body)
		else:
			self.send_response(404)
			self.end_headers()


def start_fixture_server():
	socketserver.ThreadingTCPServer.daemon_threads = True
	socketserver.ThreadingTCPServer.allow_reuse_address = True
	httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FixtureHandler)
	port = httpd.server_address[1]
	t = threading.Thread(target=httpd.serve_forever, daemon=True)
	t.start()
	return httpd, f"http://127.0.0.1:{port}"


def extract_text(res) -> str:
	parts = []
	for item in getattr(res, "content", []) or []:
		txt = getattr(item, "text", None)
		if txt is not None:
			parts.append(txt)
	return "\n".join(parts)


async def run_suite(script_path: str, suite: str, cdp_port: int):
	httpd, base_url = start_fixture_server()
	tmp_dir = tempfile.mkdtemp(prefix=f"sb-e2e-{suite}-")
	prof_dir = os.path.join(tmp_dir, "profile")
	dl_dir = os.path.join(tmp_dir, "downloads")
	os.makedirs(prof_dir, exist_ok=True)
	os.makedirs(dl_dir, exist_ok=True)

	env = os.environ.copy()
	env.update({
		"STEALTH_BROWSER_CDP_PORT": str(cdp_port),
		"STEALTH_BROWSER_PROFILE_DIR": prof_dir,
		"STEALTH_BROWSER_DOWNLOADS_DIR": dl_dir,
		"STEALTH_BROWSER_HEADLESS": "true",
		"STEALTH_BROWSER_IDLE_TIMEOUT": "120",
	})

	server_params = StdioServerParameters(
		command="uv",
		args=["run", "--script", script_path],
		env=env,
	)

	failures = []

	def check(label: str, cond: bool, detail: str = ""):
		if cond:
			print(f"  [PASS] {label}")
		else:
			print(f"  [FAIL] {label}: {detail}")
			failures.append(f"{label}: {detail}")

	try:
		async with stdio_client(server_params) as (read, write):
			async with ClientSession(read, write) as sess:
				init_res = await sess.initialize()
				tools_res = await sess.list_tools()
				tool_names = {t.name for t in tools_res.tools}
				print(f"[{suite}] Connected MCP ({len(tool_names)} tools): {sorted(tool_names)}")

				async def call(name: str, args: dict = None) -> str:
					r = await sess.call_tool(name, args or {})
					return extract_text(r)

				# Baseline navigation check (all suites)
				nav = await call("navigate", {"url": base_url + "/"})
				check("navigate to fixture", "HTTP 200" in nav and "E2E Test Portal" in nav, nav)

				if suite in ("core", "all"):
					instr = getattr(init_res, "instructions", "") or ""
					check("instructions cheat-sheet present", "evaluate_js" in instr and "wait_for" in instr, instr[:200])
					check("wait_for tool registered", "wait_for" in tool_names, str(tool_names))

					# script alias + JSON serialization in evaluate_js
					ev_alias = await call("evaluate_js", {"script": "({ok: true, nums: [1, 2, 3]})"})
					check("evaluate_js script alias + JSON", '"ok": true' in ev_alias, ev_alias)

					# Truncation guard on huge string
					ev_big = await call("evaluate_js", {"expression": "'x'.repeat(50000)", "max_length": 500})
					check("evaluate_js max_length truncation", "Truncated" in ev_big or "truncated" in ev_big.lower(), ev_big[:200])

					st_res = await call("state", {"framework": "auto"})
					check(
						"state() reads page-world __NEXT_DATA__ and window.store",
						"Next.js (__NEXT_DATA__)" in st_res
						and '"user": "levon"' in st_res
						and "Redux (window.store)" in st_res
						and '"cash": 12345' in st_res,
						st_res[:500],
					)
					ev_iso = await call("evaluate_js", {"expression": "window.__CUSTOM_PAGE_GLOBAL__?.secretToken ?? 'isolated'"})
					check("evaluate_js defaults to isolated world", "isolated" in ev_iso and "main-world-ok" not in ev_iso, ev_iso)
					ev_main = await call("evaluate_js", {
						"expression": "window.__CUSTOM_PAGE_GLOBAL__?.secretToken ?? 'isolated'",
						"main_world": True,
					})
					check("evaluate_js(main_world=True) reads page globals", "main-world-ok" in ev_main, ev_main)
					ev_batch = await call("batch", {"actions": [
						{"action": "evaluate", "expression": "window.__CUSTOM_PAGE_GLOBAL__?.secretToken ?? 'isolated'", "main_world": True},
					]})
					check("batch evaluate(main_world=True) reads page globals", "main-world-ok" in ev_batch, ev_batch)

					# Dialog auto-handler (must NOT hang!)
					dlg_click = await call("click", {"selector": "#alert-btn"})
					after_alert = await call("evaluate_js", {"expression": "document.body.dataset.afterAlert || 'no'"})
					check("dialog auto-handled without hang", "Clicked" in dlg_click and "yes" in after_alert, f"{dlg_click} | {after_alert}")

					# Dialog history surfaced in status()
					st = await call("status", {})
					check("status surfaces dialog history", "Recent dialogs" in st and "Session warning!" in st, st)

					# Standalone wait_for
					await call("click", {"selector": "#delayed-btn"})
					wf = await call("wait_for", {"selector": "#late-card", "text": "25000 pts", "timeout_ms": 5000})
					check("standalone wait_for selector+text", "late-card" in wf or "25000 pts" in wf or "met" in wf.lower() or "matched" in wf.lower() or "wait" in wf.lower(), wf)
					check("wait_for no error", "error" not in wf.lower() and "timed out" not in wf.lower(), wf)

					# switch_tab / close_tab with tab= param alias
					await call("new_tab", {"url": base_url + "/dashboard"})
					sw = await call("switch_tab", {"tab": 0})
					check("switch_tab accepts tab= alias", "Switched to tab [0]" in sw, sw)
					cl = await call("close_tab", {"tab": 1})
					check("close_tab accepts tab= alias", "Closed tab [1]" in cl, cl)

					# Unknown params must fail loudly (strict argument validation)
					bad = await call("switch_tab", {"tab": 0, "typo_param": 1})
					check("unknown param rejected loudly", "Extra inputs" in bad or "extra" in bad.lower(), bad[:200])

				if suite in ("interact", "all"):
					snap = await call("snapshot", {})
					check("snapshot includes href", "/account/details" in snap and "/statement.pdf" in snap, snap[:600])
					check("snapshot includes shadow DOM btn", "Shadow Confirm" in snap, snap)
					check("snapshot includes iframe btn", "Iframe Submit" in snap, snap)
					check("snapshot assigns eN refs", bool(re.search(r"\be\d+\b", snap)), snap[:600])

					# extract: structured repeated-card rows with null-tolerant fields
					extr = await call("extract", {
						"container_selector": ".result-card",
						"fields": {
							"title": "text:.card-link",
							"link": "@href .card-link",
							"price": "text:.card-price",
							"id": "@data-id",
						},
					})
					check("extract returns structured rows",
						'"title": "Card Alpha"' in extr and '"price": "US$10.99"' in extr and '"total_matched": 3' in extr,
						extr[:500])
					check("extract null-tolerant missing fields",
						'"price": null' in extr and '"link": "/account/details"' in extr and '"id": "C3"' in extr,
						extr)

					# Find ref for "Second Action", "Shadow Confirm", "Iframe Submit", and input
					def find_ref(label_sub):
						for line in snap.splitlines():
							if label_sub in line:
								m = re.search(r"\b(e\d+)\b", line)
								if m:
									return m.group(1)
						return ""

					ref_second = find_ref("Second Action")
					ref_shadow = find_ref("Shadow Confirm")
					ref_iframe = find_ref("Iframe Submit")
					ref_input = find_ref("search-box") or find_ref("Type here")
					check("found refs for duplicate/shadow/iframe", all([ref_second, ref_shadow, ref_iframe]), f"second={ref_second}, shadow={ref_shadow}, iframe={ref_iframe}")

					if ref_second:
						c2 = await call("click", {"ref": f"@{ref_second}"})
						v2 = await call("evaluate_js", {"expression": "document.body.dataset.clicked || 'none'"})
						check("click(@ref) hits exact 2nd duplicate btn", "second" in v2, f"{c2} | {v2}")

					if ref_shadow:
						cs = await call("click", {"ref": ref_shadow})
						vs = await call("evaluate_js", {"expression": "document.body.dataset.shadow || 'no'"})
						check("click(ref) pierces Shadow DOM", "yes" in vs, f"{cs} | {vs}")

					if ref_iframe:
						cf = await call("click", {"ref": ref_iframe})
						vf = await call("evaluate_js", {"expression": "document.body.dataset.frame || 'no'"})
						check("click(ref) pierces same-origin iframe", "yes" in vf, f"{cf} | {vf}")

					# click(force=True) through overlay
					cov = await call("click", {"selector": "#covered-btn", "force": True})
					vcov = await call("evaluate_js", {"expression": "document.body.dataset.covered || 'no'"})
					check("click(force=True) bypasses overlay", "yes" in vcov, f"{cov} | {vcov}")

					# click(text=...)
					ct = await call("click", {"text": "First Action"})
					vt = await call("evaluate_js", {"expression": "document.body.dataset.clicked || 'none'"})
					check("click(text=...) clicks matching element", "first" in vt, f"{ct} | {vt}")

					# batch with ref + force
					if ref_input:
						br = await call("batch", {"actions": [
							{"action": "fill", "ref": ref_input, "text": "hello-batch"},
							{"action": "click", "selector": "#covered-btn", "force": True},
						]})
						bv = await call("evaluate_js", {"expression": "document.getElementById('search-box').value"})
						check("batch(ref + force)", "hello-batch" in bv and "failed" not in br.lower(), f"{br} | {bv}")

					# screenshot full_page, selector, annotate
					ss_full = os.path.join(tmp_dir, "full.png")
					ss_el = os.path.join(tmp_dir, "el.png")
					ss_ann = os.path.join(tmp_dir, "ann.png")
					r_full = await call("screenshot", {"save_path": ss_full, "full_page": True})
					r_el = await call("screenshot", {"save_path": ss_el, "selector": "#covered-btn"})
					r_ann = await call("screenshot", {"save_path": ss_ann, "annotate": True})
					check("screenshot full_page", os.path.exists(ss_full) and os.path.getsize(ss_full) > 1000, r_full)
					check("screenshot selector", os.path.exists(ss_el) and os.path.getsize(ss_el) > 100, r_el)
					check("screenshot annotate + cleanup", os.path.exists(ss_ann) and os.path.getsize(ss_ann) > 1000, r_ann)
					# Verify annotation overlay was removed cleanly
					leftover = await call("evaluate_js", {"expression": "document.querySelectorAll('#__sb_annotation_overlay__, [data-sb-annotate], .sb-annotate-overlay').length"})
					check("screenshot annotate cleans up overlay", "0" in leftover, leftover)

				if suite in ("telemetry", "all"):
					check("downloads/network_requests/console_logs registered",
						{"downloads", "network_requests", "console_logs"}.issubset(tool_names),
						str(tool_names))

					# Reload so listeners capture boot console & network cleanly
					await call("navigate", {"url": base_url + "/"})
					await asyncio.sleep(0.5)

					clogs = await call("console_logs", {})
					check("console_logs captures log/warn/error", "portal-boot-ok" in clogs and "portal-test-error" in clogs, clogs)
					clogs_err = await call("console_logs", {"level": "error"})
					check("console_logs level=error filter", "portal-test-error" in clogs_err and "portal-boot-ok" not in clogs_err, clogs_err)

					nreqs = await call("network_requests", {})
					check("network_requests captures API + 404", "/api/portfolio" in nreqs and "/api/missing-404" in nreqs, nreqs)
					nreqs_404 = await call("network_requests", {"status_min": 400})
					check("network_requests status_min=400 filter", "/api/missing-404" in nreqs_404 and "/api/portfolio" not in nreqs_404, nreqs_404)

					# Direct binary PDF save via fetch(save_path=...)
					pdf_out = os.path.join(tmp_dir, "saved-api.pdf")
					fr_pdf = await call("fetch", {"url": "/statement.pdf", "save_path": pdf_out})
					check("fetch(save_path) saves PDF bytes",
						os.path.exists(pdf_out) and open(pdf_out, "rb").read() == PDF_BYTES,
						f"{fr_pdf} | exists={os.path.exists(pdf_out)}")

					# Direct blob: URL save via fetch(save_path=...)
					blob_url_out = await call("evaluate_js", {"expression": "document.body.dataset.blob"})
					m_blob = re.search(r"blob:[^\s'\"]+", blob_url_out)
					if m_blob:
						blob_pdf = os.path.join(tmp_dir, "saved-blob.pdf")
						fr_blob = await call("fetch", {"url": m_blob.group(0), "save_path": blob_pdf})
						check("fetch(save_path) saves blob: PDF",
							os.path.exists(blob_pdf) and b"%blob-pdf-test" in open(blob_pdf, "rb").read(),
							fr_blob)
					else:
						check("blob URL extracted", False, blob_url_out)

					# Trigger real browser download via click on <a download>
					await call("click", {"selector": "#stmt-link"})
					await asyncio.sleep(1.0)
					dl_res = await call("downloads", {"include_dir": True})
					check("downloads() tracks download / dir", "test-statement.pdf" in dl_res, dl_res)

				if suite in ("tabs", "all"):
					check("wait_for_human registered", "wait_for_human" in tool_names, str(tool_names))

					st1 = await call("status", {})
					m_t1 = re.search(r"\[0 \| (t\d+)\]", st1)
					check("status displays stable tab_id [0 | tN]", bool(m_t1), st1)

					nt2 = await call("new_tab", {"url": base_url + "/dashboard"})
					m_t2 = re.search(r"tab_id=(t\d+)", nt2)
					check("new_tab returns tab_id=tN", bool(m_t2), nt2)

					if m_t1 and m_t2:
						tid2 = m_t2.group(1)
						# Close tab 0 — tab 1 shifts from index 1 -> index 0, but tid2 MUST still resolve!
						await call("close_tab", {"index": 0})
						gc = await call("get_content", {"tab": tid2})
						check("stable tab_id survives earlier tab close", "Welcome Dashboard" in gc, gc)

						# Closed tab_id gives clear error
						gc_dead = await call("get_content", {"tab": m_t1.group(1)})
						check("closed tab_id returns clear error", "not found" in gc_dead.lower() or "closed" in gc_dead.lower(), gc_dead)

					# wait_for_human (already satisfied condition so it returns immediately without waiting!)
					# Use current tab in headed=false -> note: wait_for_human switches headless->headed unless already headed,
					# so let's verify condition-already-met or check wait_for_human without opening window?
					# Actually let's test wait_for_human with notify=False and url_contains="/dashboard" (verify fast return)
					# Note: it will restart headed briefly in isolated profile, then close_browser cleans up!
					wfh = await call("wait_for_human", {
						"reason": "E2E automated check",
						"url_contains": "/dashboard",
						"timeout_s": 10,
						"poll_interval_s": 0.3,
						"notify": False,
					})
					check("wait_for_human resolves when condition met", "/dashboard" in wfh and "timed out" not in wfh.lower(), wfh)

				await call("close_browser", {"force_kill": True})
	finally:
		httpd.shutdown()
		shutil.rmtree(tmp_dir, ignore_errors=True)

	if failures:
		print(f"\n[{suite}] FAILED ({len(failures)} failures):")
		for f in failures:
			print(f"  - {f}")
		return 1
	print(f"\n[{suite}] ALL E2E CHECKS PASSED!")
	return 0


if __name__ == "__main__":
	script_path = sys.argv[1]
	suite = sys.argv[2]
	port = int(sys.argv[3])
	sys.exit(asyncio.run(run_suite(script_path, suite, port)))
