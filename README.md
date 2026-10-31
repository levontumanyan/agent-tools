# agent-tools

Single-file, zero-setup CLI tools and MCP servers that give AI coding agents (**Claude Code**, **Google Antigravity**, **Cursor**, **OpenAI Codex**) direct, local access to your digital life on macOS — **WhatsApp**, **iMessage**, **Apple Calendar & Reminders**, **Apple Pay**, **Microsoft Outlook**, **Airbnb search & scoring**, **Antigravity session recovery & telemetry**, **stealth browser automation**, and **automated reel & video downloading**.

Every tool in `bin/` is a self-contained executable (PEP 723 `uv run --script` or compiled native helper) with auto-generated `--help`, zero global Python pollution, and instant startup.

# Why agent-tools?

- **CLI-First + Selective MCP**: Simple data lookups (`whatsapp`, `imessage`, `cal-event`, `apple-pay`, `outlook`, `download-video`, `airbnb`) run as fast, stateless CLI commands that don't bloat your agent's context window with dozens of MCP tool schemas. Stateful browser sessions use `brave-mcp`.
- **100% Local & Private**: Reads directly from local macOS SQLite databases (`ChatStorage.sqlite`, `chat.db`, Wallet passes) and native `EventKit` APIs — no third-party cloud relays.
- **Zero Dependency Hell**: Powered by `uv` inline script metadata (`#!/usr/bin/env -S uv run --script`). Clone once, add `bin/` to `$PATH`, and every tool manages its own isolated environment automatically.
- **macOS Browser Hang Prevention**: `brave-mcp` solves the notorious macOS Chromium/Brave `com.brave.Browser.MachPortRendezvousServer` IPC freeze by attaching over CDP or launching an isolated Patchright stealth Chromium profile with automatic idle driver teardown.

# Included Tools

| Tool | Type | Integration | What Your Agent Can Do |
| :--- | :--- | :--- | :--- |
| [`whatsapp`](src/whatsapp.swift) | CLI | Local SQLite + AppleScript UI | List recent/unread chats, full-text search messages, read threads (by contact, phone, or @username), list/extract attachments & documents, and stage drafts. |
| [`imessage`](bin/imessage) | CLI | macOS `~/Library/Messages/chat.db` | Search and read local iMessage / SMS conversations and inspect/extract attachments (`-a` / `--attachments`). |
| [`cal-event`](src/cal-event.swift) | CLI | macOS `EventKit` | Create, query, and manage Apple Calendar events and Apple Reminders (`--reminder`) with native iCloud sync. |
| [`call-recordings`](src/call-recordings.swift) | CLI | Apple Notes SQLite + `Speech` | Access, transcribe on-device, search, and export iPhone call recordings synced via Apple Notes. |
| [`outlook`](bin/outlook) | CLI | Microsoft Graph API | Read, search, draft, and send Outlook emails from the terminal. |
| [`apple-pay`](bin/apple-pay) | CLI | Local macOS Wallet SQLite | Query, filter, and audit local Apple Pay card transactions on macOS. |
| [`brave-mcp`](bin/brave-mcp) | MCP Server | Patchright + CDP | Navigate, click, type, scroll, evaluate JS, capture screenshots, and manage tabs in Brave or standalone stealth Chromium. |
| [`agy-sessions`](bin/agy-sessions) | CLI | macOS iTerm2 + Antigravity CLI | Snapshot, inspect, test, auto-restore, and gracefully cull stale (>6h) `agy` sessions in iTerm2 while keeping tabs open. |
| [`antigravity-shipper`](src/antigravity-shipper) | Daemon / CLI | Local `~/.gemini` transcripts + PostgreSQL | Zero-overhead, incremental telemetry shipper that tails Antigravity CLI agent sessions, redacts secrets, and syncs tool calls & metrics to PostgreSQL. |
| [`airbnb`](airbnb/) | CLI | Airbnb API + Climate/Sentiment Engine | Search, score, and benchmark listings against nomad criteria (Wi-Fi, kitchen, climate/heating, noise, discounts). |
| [`download-video`](bin/download-video) | CLI | yt-dlp + gallery-dl + Apple Vision OCR | Download Instagram reels/stories and YouTube videos/shorts to Google Drive, transcode to WhatsApp-native H.264/AAC MP4, extract frame OCR/hashtags, and embed metadata. |

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
download-video --help
brave-mcp --help
agy-sessions --help
antigravity-shipper --help
airbnb --help
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

# Microsoft Outlook Setup (Azure App Registration)

The `outlook` CLI uses the Microsoft Graph API with OAuth 2.0 Device Code flow. You do not need a paid Azure subscription. A free personal Microsoft account (@outlook.com, @hotmail.com) or a work/school account is sufficient.

## Step 1: Register Application in Azure Portal
1. Open [Azure Portal App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) or the [Microsoft Entra admin center](https://entra.microsoft.com).
2. Click **New registration**.
3. Set **Name** (for example: `outlook-cli`).
4. Under **Supported account types**, select:
	* **Personal Microsoft accounts only** (for personal @outlook.com / @hotmail.com accounts), or
	* **Accounts in any organizational directory and personal Microsoft accounts** (for both personal and work/school accounts).
5. Under **Redirect URI**:
	* Select platform: **Mobile and desktop applications**.
	* Enter URI: `https://login.microsoftonline.com/common/oauth2/nativeclient`.
6. Click **Register**.

## Step 2: Enable Public Client Flows
1. In the left navigation menu, select **Authentication**.
2. Scroll down to **Advanced settings**.
3. Under **Allow public client flows**, set **Enable the following mobile and desktop flows** to **Yes**.
4. Click **Save**.

## Step 3: Add API Permissions
1. In the left navigation menu, select **API permissions**.
2. Click **Add a permission**.
3. Select **Microsoft Graph**.
4. Select **Delegated permissions** (do not select Application permissions).
5. Search for and select each of the following permissions:
	* `Mail.ReadWrite` (read, compose, move, and delete emails)
	* `Mail.Send` (send emails)
	* `User.Read` (read user profile)
	* `MailboxSettings.ReadWrite` (manage folders and inbox rules)
	* `offline_access` (receive refresh tokens for background access)
6. Click **Add permissions**.

## Step 4: Configure Local Client ID
1. In the left navigation menu, select **Overview**.
2. Copy the **Application (client) ID**. This identifier is public and safe to share.
3. Save the identifier to `~/.local/bin/.env` or export it in your shell configuration:
```sh
echo 'MSGRAPH_CLIENT_ID="<your-application-client-id>"' >> ~/.local/bin/.env
chmod 600 ~/.local/bin/.env
```
Keys can also be stored directly in the macOS Keychain (`msgraph-client-id`).

## Step 5: Authenticate CLI
1. Run the authentication command:
```sh
outlook auth
```
2. The CLI prints a login URL (`https://microsoft.com/devicelogin`) and a one-time device code.
3. Open the URL in your web browser, enter the code, and approve the permissions.
4. The CLI saves credentials to `~/.local/share/outlook/token_cache.bin` with file permissions `0600`. Tokens refresh automatically.

# Video Downloader CLI (`download-video`)

Downloads videos, Instagram Reels/stories, and YouTube videos/shorts directly into your Google Drive meme archive (`~/Library/CloudStorage/GoogleDrive-*/My Drive/media/memes`) with automated Apple Vision OCR frame indexing, WhatsApp-friendly H.264/AAC transcoding, and duplicate prevention.

## Highlights

- **Zero-Setup PEP 723 Executable**: Runs with `uv run --script` using self-contained dependencies (`pyobjc-framework-Vision`, `pyobjc-framework-Cocoa`, `gnureadline`).
- **Clipboard Auto-Detection**: Running `download-video` with no arguments automatically pulls the video URL from your macOS clipboard (`pbpaste`).
- **Dynamic Google Drive Discovery**: Automatically resolves modern macOS CloudStorage paths (`~/Library/CloudStorage/GoogleDrive-*/My Drive/media/memes`) or classic `~/Google Drive` mounts.
- **WhatsApp Playback Optimization**: Transcodes Instagram reels into H.264/AAC MP4 with a 1-frame preview offset at `t=0.5s` to eliminate black thumbnail previews on WhatsApp.
- **Apple Vision OCR & Frame Tagging**: Scans video keyframes using macOS native `VNRecognizeTextRequest` and `VNClassifyImageRequest` to auto-suggest filename slugs and hashtags.
- **Carousel & Photo Fallback**: Seamlessly falls back to `gallery-dl` if `yt-dlp` fails on Instagram photo/carousel posts.
- **Archive & Metadata Management**: Tracks downloaded items in `.yt-dlp-archive` to prevent re-downloads and embeds personal notes (`--note`) directly into container metadata.
- **Audio & Clip Cutting**: Supports audio extraction (`-a` / `--audio-only`) as MP3 and YouTube timestamp cuts (`-s` / `--section "MM:SS-MM:SS"`).

# Usage Examples

```sh
# Video Downloader: grab from clipboard or download Instagram Reels / YouTube videos to Google Drive
download-video
download-video "https://www.instagram.com/reel/Cxxxxxxx/"
download-video "https://www.instagram.com/reel/Cxxxxxxx/" -n "funny-cat" --note "sent by alex"
download-video "https://www.youtube.com/watch?v=xxxxxxx" --section "01:30-02:15"
download-video -m "funny-cat"
download-video -d "funny-cat"

# WhatsApp: check unread messages, search history, read threads, or stage a draft
whatsapp unread
whatsapp search "flight confirmation"
whatsapp read "Alex"
whatsapp read "@username"
whatsapp draft --to "@username" --message "On my way!"

# Outlook: list unread emails, search, read, and draft
outlook unread
outlook search "invoice"
outlook read <message-id>
outlook draft --to "person@example.com" --subject "Status update" --body "Task complete."

# Call Recordings: list, read, transcribe on-device, or export iPhone calls
call-recordings list
call-recordings read <id>
call-recordings transcribe <id>
call-recordings search "tax form"
call-recordings export <id> --out ~/Downloads

# Calendar & Reminders: schedule an event or native Apple Reminder
cal-event add "Dentist Appointment" --start "2026-10-20 14:00"
cal-event add "Submit expense report" --reminder --due "2026-10-18 09:00"

# iMessage: search threads or inspect attachments
imessage -q "invoice"
imessage -c "+16471234567" -a
imessage -q "IMG_6503" -a
apple-pay --help
```

# Agent Instructions (`AGENTS.md` / `CLAUDE.md` / `GEMINI.md`)

Paste the rules from [`AGENTS.md`](AGENTS.md) into your global agent instructions so your AI assistant automatically knows how and when to invoke each tool.

# Permissions

Grant your terminal or IDE the following under **System Settings > Privacy & Security**:
- **Full Disk Access**: `imessage`, `whatsapp`, `apple-pay`
- **Calendars & Reminders**: `cal-event`
- **Speech Recognition**: `whatsapp` (for local voice-note transcription)

