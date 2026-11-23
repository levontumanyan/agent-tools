# Stealth Browser Subagent & OpenCode Guide

# Context Isolation with Dedicated Browser Subagents

Heavy multi-step portal workflows (banking dashboards, paginated scrapes, multi-screen forms) produce large `snapshot`, `get_content`, and `fetch` outputs that bloat the parent agent's context window. Delegate these runs to a dedicated subagent that owns a single stable `tab_id` and returns only the distilled result.

## Stable Tab Ownership Workflow

Every tab opened in `stealth-browser` receives a monotonic stable ID (`t1`, `t2`, ...) shown in `status` (`[0 | t3] Title - URL`) and returned by `new_tab` (`tab_id=t3`). Unlike positional indices (`0`, `1`, ...), stable IDs never shift when sibling tabs close, preventing `Invalid tab index` races across parallel subagents.

1. Open an owned tab and record its `tab_id`:
   - `new_tab(url="https://portal.example.com", block_media=True)` -> returns `... (tab_id=t4)`.
2. Pin every subsequent call to that stable ID (`tab="t4"`):
   - `snapshot(filter=..., viewport_only=True, tab="t4")`, `extract(container_selector=..., fields={...}, tab="t4")`, `state(tab="t4")`, `batch(actions=[...], tab="t4")`, `fetch(url="/api/data", tab="t4")`, `get_content(filter=..., offset=..., tab="t4")`.
3. Hand off interactive login, 2FA, or CAPTCHA cleanly when needed:
   - `wait_for_human(reason="Approve 2FA prompt", url_contains="/dashboard", tab="t4")` switches headless Chromium to headed mode (with Apple Passwords enabled), sends a macOS notification, and resumes automatically once the condition matches.
4. Clean up the owned tab before returning a concise summary to the parent:
   - Call `close_tab(tab="t4")` directly so background sessions do not accumulate.

## Subagent Brief Template

Launch via `invoke_subagent` with `Model: "flash"` for routine navigation, portal checks, form fills, and scraping (reserving `Model: "inherit"` for complex reasoning). Give the browser subagent:
- Target URL and exact fields or files to extract.
- Instruction to read `~/.gemini/antigravity-cli/mcp/stealth-browser/instructions.md` once instead of individual tool `.json` schemas.
- Instruction to call `new_tab(...)`, pin all calls to the returned `tab_id`, and avoid touching other open tabs.
- Instruction to call `wait_for_human(...)` instead of guessing if a login, 2FA, or CAPTCHA gate appears.
- Output schema (compact JSON or bullet summary) so raw DOM/HTML stays out of the parent context.

# OpenCode MCP Setup

Add `stealth-browser` via the CLI:

```sh
opencode mcp add --global stealth-browser -- uv run --script /Users/<username>/repos/agent-tools/bin/stealth-browser
```

Or edit `~/.config/opencode/opencode.jsonc` (or `~/.config/opencode/opencode.json`) directly. OpenCode v2 registers servers under `mcp.servers.<name>` with `type: "local"` and an array `command` (top-level `mcp.<name>` is deprecated in `https://opencode.ai/config.json`):

```json
{
	"$schema": "https://opencode.ai/config.json",
	"mcp": {
		"servers": {
			"stealth-browser": {
				"type": "local",
				"command": [
					"uv",
					"run",
					"--script",
					"/Users/<username>/repos/agent-tools/bin/stealth-browser"
				],
				"environment": {
					"STEALTH_BROWSER_HEADLESS": "true"
				}
			}
		}
	}
}
```

## Notes

- Replace `/Users/<username>/repos/agent-tools/bin/stealth-browser` with the absolute path to your local checkout (avoid `~` in JSON).
- If OpenCode is launched from a GUI without your shell `PATH`, replace `"uv"` with its absolute path (for example `/opt/homebrew/bin/uv` or `/Users/<username>/.local/bin/uv`).
- Servers under `mcp.servers` are enabled by default (set `"disabled": true` to disable; `"enabled"` is only used in the deprecated top-level `mcp.<name>` format).
- Optional environment overrides under `environment`:
  - `STEALTH_BROWSER_CDP_PORT`: CDP port (default `9222`).
  - `STEALTH_BROWSER_IDLE_TIMEOUT`: Idle driver teardown in seconds (default `300`).
  - `STEALTH_BROWSER_PROFILE_DIR`: Chromium profile path (default `~/.agent-chromium-profile`).
- Verify config loading with `opencode debug config`, then restart OpenCode and check `/mcp` to confirm `stealth-browser` is connected.
