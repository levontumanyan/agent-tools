# agent-tools

Single-file, zero-setup CLI tools and MCP servers that give AI coding agents (**Claude Code**, **Google Antigravity**, **Cursor**, **OpenAI Codex**) direct, local access to your digital life on macOS — **WhatsApp**, **iMessage**, **Apple Calendar & Reminders**, **Apple Pay**, **Microsoft Outlook**, and **stealth browser automation**.

Every tool in `bin/` is a self-contained executable (PEP 723 `uv run --script` or compiled native helper) with auto-generated `--help`, zero global Python pollution, and instant startup.

# Why agent-tools?

- **CLI-First + Selective MCP**: Simple data lookups (`whatsapp`, `imessage`, `cal-event`, `apple-pay`, `outlook`) run as fast, stateless CLI commands that don't bloat your agent's context window with dozens of MCP tool schemas. Stateful browser sessions use `brave-mcp`.
- **100% Local & Private**: Reads directly from local macOS SQLite databases (`ChatStorage.sqlite`, `chat.db`, Wallet passes) and native `EventKit` APIs — no third-party cloud relays.
- **Zero Dependency Hell**: Powered by `uv` inline script metadata (`#!/usr/bin/env -S uv run --script`). Clone once, add `bin/` to `$PATH`, and every tool manages its own isolated environment automatically.
- **macOS Browser Hang Prevention**: `brave-mcp` solves the notorious macOS Chromium/Brave `com.brave.Browser.MachPortRendezvousServer` IPC freeze by attaching over CDP or launching an isolated Patchright stealth Chromium profile with automatic idle driver teardown.

# Included Tools

| Tool | Type | Integration | What Your Agent Can Do |
| :--- | :--- | :--- | :--- |
| [`whatsapp`](src/whatsapp.swift) | CLI | Local SQLite + AppleScript UI | List recent/unread chats, full-text search messages, read threads, list/extract attachments & documents, and stage drafts. |
| [`imessage`](bin/imessage) | CLI | macOS `~/Library/Messages/chat.db` | Search and read local iMessage / SMS conversation history and recent threads. |
| [`cal-event`](src/cal-event.swift) | CLI | macOS `EventKit` | Create, query, and manage Apple Calendar events and Apple Reminders (`--reminder`) with native iCloud sync. |
| [`outlook`](bin/outlook) | CLI | Microsoft Graph API | Read, search, draft, and send Outlook emails from the terminal. |
| [`apple-pay`](bin/apple-pay) | CLI | Local macOS Wallet SQLite | Query, filter, and audit local Apple Pay card transactions on macOS. |
| [`brave-mcp`](bin/brave-mcp) | MCP Server | Patchright + CDP | Navigate, click, type, scroll, evaluate JS, capture screenshots, and manage tabs in Brave or standalone stealth Chromium. |
| [`agy-sessions`](bin/agy-sessions) | CLI | macOS iTerm2 + Antigravity CLI | Snapshot, inspect, test, auto-restore, and gracefully cull stale (>6h) `agy` sessions in iTerm2 while keeping tabs open. |
| [`antigravity-shipper`](src/antigravity-shipper) | Daemon / CLI | Local `~/.gemini` transcripts + PostgreSQL | Zero-overhead, incremental telemetry shipper that tails Antigravity CLI agent sessions, redacts secrets, and syncs tool calls & metrics to PostgreSQL. |

# Quickstart

Clone the repository, compile native tools, and add `bin/` to your `$PATH`:

```sh
git clone https://github.com/levontumanyan/agent-tools.git ~/repos/agent-tools
make -C ~/repos/agent-tools
```

Add to `~/.zshrc` or `~/.bashrc`:

```sh
if [ -d "$HOME/repos/agent-tools/bin" ]; then
	export PATH="$HOME/repos/agent-tools/bin:$PATH"
fi
```

Every tool supports `--help` out of the box:

```sh
whatsapp --help
imessage --help
cal-event --help
outlook --help
apple-pay --help
brave-mcp --help
agy-sessions --help
antigravity-shipper --help
```

# Stealth Browser MCP (`brave-mcp`)

Launching a second Brave binary alongside an active one on macOS corrupts shared Mach port rendezvous (`com.brave.Browser.MachPortRendezvousServer`), freezing tab creation and IPC in your main browser.

`brave-mcp` avoids this completely:

1. **CDP First**: Attempts to attach to an existing browser session over `http://127.0.0.1:9222` (`BRAVE_CDP_PORT`).
2. **Standalone Stealth Fallback**: Falls back to launching a dedicated Patchright stealth Chromium instance (`~/.agent-chromium-profile`) with `AutomationControlled` disabled.
3. **Clean Lifecycle & Idle Watchdog**: Automatically shuts down the background Patchright Node driver after 5 minutes of inactivity (`BRAVE_MCP_IDLE_TIMEOUT=300`) and guarantees immediate subprocess teardown on `SIGTERM`, `SIGHUP`, or `stdin` EOF.

## MCP Configuration (`mcp_config.json`)

Add to your agent's MCP configuration (`~/.gemini/config/mcp_config.json`, `~/.claude.json`, or `.cursor/mcp.json`):

```json
{
	"mcpServers": {
		"brave-browser": {
			"command": "uv",
			"args": [
				"run",
				"--script",
				"/Users/your-username/repos/agent-tools/bin/brave-mcp"
			]
		}
	}
}
```

## Available MCP Tools

- `brave_status`: Check connection status and list all open tabs with indices.
- `brave_navigate`: Navigate the active tab or open a new tab (`new_tab=True`).
- `brave_get_content`: Extract visible text from `body` or any CSS/XPath selector.
- `brave_click` / `brave_type` / `brave_press_key` / `brave_scroll`: Interact with page elements.
- `brave_screenshot`: Capture a viewport screenshot for multimodal agent inspection.
- `brave_evaluate_js`: Execute JavaScript in the active page context.
- `brave_switch_tab` / `brave_new_tab` / `brave_close_tab`: Full multi-tab management.

# Usage Examples

```sh
# WhatsApp: check unread messages, search history, or stage a draft
whatsapp unread
whatsapp search "flight confirmation"
whatsapp read "Alex"
whatsapp draft --to "Alex" --message "On my way!"

# Calendar & Reminders: schedule an event or native Apple Reminder
cal-event add "Dentist Appointment" --start "2026-10-20 14:00"
cal-event add "Submit expense report" --reminder --due "2026-10-18 09:00"

# iMessage & Apple Pay: search messages and recent card transactions
imessage --help
apple-pay --help
```

# Agent Instructions (`AGENTS.md` / `CLAUDE.md` / `GEMINI.md`)

Paste the rules from [`AGENTS.md`](AGENTS.md) into your global agent instructions so your AI assistant automatically knows how and when to invoke each tool.

# Permissions

Grant your terminal or IDE the following under **System Settings > Privacy & Security**:
- **Full Disk Access**: `imessage`, `whatsapp`, `apple-pay`
- **Calendars & Reminders**: `cal-event`
- **Speech Recognition**: `whatsapp` (for local voice-note transcription)

