# AGENTS.md

- **Calendar & Reminders CLI**: Use `cal-event add "<title>" --start "<YYYY-MM-DD HH:MM>"` for calendar events (defaults to iCloud -> Home) and `cal-event add "<title>" --reminder --due "<YYYY-MM-DD HH:MM>"` for Apple Reminders (integrates directly with Reminders & Calendar; see `cal-event --help`). Reminders should always be created with this script using the `--reminder` flag. When adding items to groceries (`--calendar "Grocery"`), always add each item atomically (one single item per reminder, e.g. separate commands for milk and meat, never combined like 'milk and meat'). Before adding anything to the grocery list, always run `cal-event list --reminder --calendar "Grocery" --all` first to inspect the entire grocery history in one shot, so existing items can be matched and reactivated cleanly without creating duplicates.
- **Call Recordings CLI**: Access, search, transcribe, and export iPhone call recordings synced to Apple Notes via `call-recordings [list]`, `call-recordings read <id>`, `call-recordings transcribe <id|--all>`, `call-recordings search "<query>"`, `call-recordings export <id>`, or `call-recordings open <id>` (see `call-recordings --help`). Uses native on-device speech recognition via macOS `Speech` framework with local transcript caching.
- **WhatsApp CLI**: Use `whatsapp chats` (list/recent), `whatsapp read "<contact/phone/username>"` (supports `@username`), `whatsapp documents` (list/search docs & attachments), `whatsapp search "<query>"`, `whatsapp unread`, or `whatsapp draft --to "<contact/phone/username>" --message "<text>"` (see `whatsapp --help`).
- **Outlook CLI**: Reads, searches, and drafts Outlook emails via Microsoft Graph API; see `outlook --help` for options.
- **Apple Pay CLI**: Queries and searches local Apple Pay transactions on macOS; see `apple-pay --help` for options.
- **iMessage CLI**: Queries, searches, and inspects local iMessage chat history and attachments on macOS (supports `-a` / `--attachments`); see `imessage --help` for options.
- **Browser Automation MCP**: Always use the stealth browser MCP (`brave-mcp`) for agent browsing; see `brave-mcp --help` for options. Never launch system browser binaries directly.
- **Antigravity Telemetry Shipper**: Use `antigravity-shipper` (runs as a launchd daemon or one-shot via `antigravity-shipper --once`); tails local conversation transcripts, redacts secrets, and ships telemetry to PostgreSQL; see `antigravity-shipper --help`.
- **Airbnb CLI**: Use `airbnb` for listing search, scoring, and inspection (see `airbnb --help`). Always explicitly report the nightly rate (e.g. CAD $XX/night) whether presenting a single listing or multiple listings. Detailed agent instructions and development standards are centralized in [airbnb/AGENTS.md](airbnb/AGENTS.md).
- **Video Downloader CLI**: Use `download-video "<url>"` (or bare `download-video` to grab URL from clipboard) to download reels, stories, and videos (defaults to `$DOWNLOAD_VIDEO_DIR` or `~/Downloads`) with Apple Vision OCR frame analysis, WhatsApp-compatible H.264/AAC transcoding, and metadata tagging; see `download-video --help`.

# Development

- **Swift tools (`src/*.swift`)**: Edit source in `src/` and run `make` to compile optimized binaries into `bin/`. Compiled binaries in `bin/` are gitignored.
- **Script tools (`bin/*`)**: Standalone executables edited directly in `bin/`.
- **Python tools (`airbnb/`)**: Managed with `uv`. Follow centralized instructions in `airbnb/AGENTS.md`.
- **Make targets**: `make` / `make build` (compiles `src/*.swift` -> `bin/%`), `make clean` (removes compiled binaries).

