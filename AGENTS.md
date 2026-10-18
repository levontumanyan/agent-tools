# AGENTS.md

- **Calendar & Reminders CLI**: Use `cal-event add "<title>" --start "<YYYY-MM-DD HH:MM>"` for calendar events (defaults to iCloud -> Home) and `cal-event add "<title>" --reminder --due "<YYYY-MM-DD HH:MM>"` for Apple Reminders (integrates directly with Reminders & Calendar; see `cal-event --help`). Reminders should always be created with this script using the `--reminder` flag.
- **WhatsApp CLI**: Use `whatsapp chats` (list/recent), `whatsapp read "<contact/phone>"`, `whatsapp documents` (list/search docs & attachments), `whatsapp search "<query>"`, `whatsapp unread`, or `whatsapp draft --to "<contact/phone>" --message "<text>"` (see `whatsapp --help`).
- **Outlook CLI**: Reads, searches, and drafts Outlook emails via Microsoft Graph API; see `outlook --help` for options.
- **Apple Pay CLI**: Queries and searches local Apple Pay transactions on macOS; see `apple-pay --help` for options.
- **iMessage CLI**: Queries and searches local iMessage chat history on macOS; see `imessage --help` for options.
- **Browser Automation MCP**: Use the dedicated Patchright stealth Chromium instance via MCP (`brave-mcp` / `uv run --script`) for agent browsing; see `brave-mcp --help` for options. Never launch a second Brave binary alongside an active one on macOS because shared Mach port rendezvous (`com.brave.Browser.MachPortRendezvousServer`) freezes tab opening and IPC in the primary browser.

# Development

- **Swift tools (`src/*.swift`)**: Edit source in `src/` and run `make` to compile optimized binaries into `bin/`. Compiled binaries in `bin/` are gitignored.
- **Script tools (`bin/*`)**: Standalone executables edited directly in `bin/`.
- **Make targets**: `make` / `make build` (compiles `src/*.swift` -> `bin/%`), `make clean` (removes compiled binaries).

