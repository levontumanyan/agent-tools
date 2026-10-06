# agent-tools

CLI utilities built for local automation and AI agents.

# Tools

- `cal-event`: macOS Calendar & Reminders via EventKit.
- `whatsapp`: WhatsApp chats, messages, media, and drafting via local SQLite storage.
- `outlook`: Read, search, draft, and send Outlook email via Microsoft Graph API.
- `apple-pay`: Query and search Apple Pay transactions on macOS.
- `imessage`: Query and search local iMessage chat history.

# Installation

Clone and add `bin/` to `$PATH`:

```sh
git clone https://github.com/levontumanyan/agent-tools.git ~/repos/agent-tools
```

In `~/.zshrc` or `~/.bashrc`:

```sh
if [ -d "$HOME/repos/agent-tools/bin" ]; then
	export PATH="$HOME/repos/agent-tools/bin:$PATH"
fi
```

# Agent Setup

Copy the directives in [`AGENTS.md`](file:///Users/levontumanyan/repos/agent-tools/AGENTS.md) into your agent prompt or system instructions.
