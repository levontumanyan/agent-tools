---
name: stealth-browser-audit
description: Audit local AGY transcripts and OpenCode databases for stealth-browser usage, errors, slow/hung calls, context bloat, and evaluate_js workarounds, then correlate findings against ~/repos/agent-tools/bin/stealth-browser to produce a prioritized improvement plan or before/after scorecard.
user_invocable: true
---

# Stealth-Browser Usage Audit

Use `stealth-browser-audit` (in `~/repos/agent-tools/bin/stealth-browser-audit`) to mine real browser sessions and turn empirical pain points into concrete upgrades for `~/repos/agent-tools/bin/stealth-browser`.

## Workflow

1. **Run the audit CLI** (pass `--exclude <current-conversation-id>` so this session does not pollute metrics; run with `BypassSandbox: true` to read `~/.gemini/antigravity-cli/brain/` and `~/.local/share/opencode/`):
   ```bash
   stealth-browser-audit --exclude <conversation-id>
   ```
   - Scoped window (e.g., post-upgrade check): `stealth-browser-audit --since 14d --exclude <conversation-id>`
   - One specific session (repeatable, prefix-matched; works for AGY and opencode sessions — nested `shell`/`execute` browser calls are attributed): `stealth-browser-audit --session <sid-prefix>`; a matched session with 0 attributed calls is reported distinctly from an unknown ID
   - Save a baseline before making changes: `stealth-browser-audit --exclude <conversation-id> --save-baseline ~/.cache/stealth-browser/audit-baseline.json`
   - Compare against a baseline: `stealth-browser-audit --since 14d --exclude <conversation-id> --diff ~/.cache/stealth-browser/audit-baseline.json`
   - Inspect raw metrics programmatically: `stealth-browser-audit --exclude <conversation-id> --json`

2. **Check baseline delta first (if `--diff` was run)**:
   - Report the before/after scorecard: `evaluate_js` share, overall & per-tool error rates (`click`, `status`, `navigate`), 3m MCP timeouts / 1k calls, slow non-timeout calls / 1k calls, validation errors / 1k calls, schema JSON reads/session, and median calls & output chars/session.
   - Flag any regressed KPIs immediately.

3. **Correlate top failure modes and workarounds directly against `~/repos/agent-tools/bin/stealth-browser`**:
   - Read the relevant tool implementations in `~/repos/agent-tools/bin/stealth-browser` (do not guess from memory).
   - Map each major signal to its exact code path:
     - **High `evaluate_js` intents** (`js_click_workaround`, `extract_text_targeted`, `extract_links`, `shadow_or_iframe`, `wait_or_poll_hack`, `download_or_pdf_hack`, `console_perf_network`) -> check whether a missing parameter, locator gap, or dedicated tool eliminates repeated JS snippets.
     - **Per-tool error root causes** (`click` overlay/hidden/locator timeout, `status` 3m hang / unresponsive tab / disconnect, `navigate` `net::ERR_*` or timeout) -> trace timeouts, CDP calls, and retry/fallback behavior in `BrowserSessionManager` and tool handlers.
     - **Pydantic validation errors** (e.g., `script` vs `expression`, `tab`/`tab_index` vs `index`) -> check tool signatures, parameter aliases, and docstrings/instructions.
     - **Context bloat & wasted roundtrips** (high chars/session, schema JSON `read_file` count, `screenshot` + `read_file`, underused `batch`/`state`/`set_media`) -> check output truncation, response verbosity, and MCP `instructions`.

4. **Output a prioritized, evidence-backed improvement list**:
   - Group into **P0 (Reliability / Hangs)**, **P1 (High-Frequency Workarounds & Error Rates)**, and **P2 (Context Efficiency & Ergonomics)**.
   - For every item include:
     - Exact metric & sample evidence from the audit (counts, %, affected sessions/domains).
     - Exact file + line/function in `~/repos/agent-tools/bin/stealth-browser`.
     - Concrete proposed change and the audit KPI it should move on the next `--diff` run.
   - Offer to save a fresh baseline (`--save-baseline`) before implementing changes if none exists.
