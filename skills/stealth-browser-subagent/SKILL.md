---
name: stealth-browser-subagent
description: Delegate multi-step, portal-heavy, or scraping browser tasks to an isolated subagent using stealth-browser with stable tab ownership (new_tab -> tab="tN" -> close_tab), keeping raw DOM/HTML/snapshot payloads out of the parent context.
user_invocable: true
---

# Stealth-Browser Subagent Delegation

Isolate multi-step portal navigation, paginated scraping, multi-screen forms, and statement downloads in a dedicated subagent so verbose `snapshot`, `get_content`, `extract`, `screenshot`, and `fetch` outputs stay out of parent context.

## Parent Delegation

Launch a subagent via `invoke_subagent` (`TypeName: "self"`, `Role: "Browser Subagent"`) with **model tiering**:
- Default to `Model: "flash"` for routine navigation, portal checks, form fills, downloads, and scraping.
- Reserve `Model: "inherit"` for complex reasoning or ambiguous multi-step decisions.

Give the subagent a self-contained brief specifying:
- Target URL(s) and exact data, actions, or file downloads required.
- Required return format (compact JSON, Markdown table, or saved file paths — no raw DOM/HTML dumps).
- Tab-isolation contract: open an owned tab, pin every call to its `tab_id`, leave sibling tabs untouched, and close the owned tab before replying.
- Human-handoff rule: invoke `wait_for_human` on any login, 2FA, or CAPTCHA gate.

## Subagent Execution Workflow

1. **Read the schema cheat-sheet once**:
   - Read `~/.gemini/antigravity-cli/mcp/stealth-browser/instructions.md` once instead of reading individual tool `.json` schemas.
2. **Open and pin an owned tab**:
   - Call `new_tab(url="<target>", block_media=True)` (omit `block_media` when charts, images, or visual verification are needed).
   - Record the returned `tab_id=tN` and pass `tab="tN"` on every subsequent `stealth-browser` call. Never switch to or modify other open tabs.
3. **Stay headless and hand off gates cleanly**:
   - Keep Chromium headless by default; call `set_headless(headless=False)` only when explicitly asked.
   - If login, 2FA, or CAPTCHA blocks progress, call `wait_for_human(reason="<action needed>", url_contains="<post-auth path>", tab="tN")` (or `selector=...` / `url_not_contains=...`). It switches to headed mode with Apple Passwords, notifies the user, and resumes once the condition matches.
4. **Prefer structured, compact, low-roundtrip tools**:
   - `extract(container_selector=..., fields={...}, tab="tN")` for repeated cards, listings, or table rows.
   - `state(tab="tN")` for Next.js, Nuxt, Redux, React Fiber, Vue, Apollo, or React Query in-memory stores.
   - `snapshot(tab="tN")` (with optional `filter="..."` and/or `viewport_only=True` to narrow interactive refs `e0`, `e1`), followed by `batch(actions=[...], tab="tN")` for multi-step clicks/fills.
   - `get_content(tab="tN")` (with optional `filter="..."` and/or `offset=...` for filtered or paginated text reads instead of dumping full pages).
   - `fetch(url=..., save_path=..., tab="tN")` for authenticated JSON APIs or binary/PDF/blob downloads directly to disk.
   - `evaluate_js(expression=..., tab="tN")` for targeted DOM reads; pass `main_world=True` only for custom page-world globals not covered by `state()`.
   - `wait_for(selector=..., text=..., url_contains=..., tab="tN")` instead of JS polling loops.
5. **Clean up and report concisely**:
   - Call `close_tab(tab="tN")` when finished (skip only if the user explicitly asked to keep the tab open).
   - Return only the distilled structured data, action confirmation, and any saved file paths.
