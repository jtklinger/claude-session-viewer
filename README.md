# Claude Code Session Viewer

A comprehensive toolkit for viewing, browsing, and resuming Claude Code conversation sessions. Includes both a command-line parser for exporting sessions to markdown and an interactive TUI for browsing your session history with permanent memory!

## Overview

When using [Claude Code](https://claude.com/claude-code), conversation sessions are stored as JSONL files in `~/.claude/projects/`. While Claude can resume these sessions and load the context, the conversation history isn't re-displayed in your terminal after resuming.

This toolkit provides two complementary tools:

1. **`view-claude-session.py`** - Command-line parser that exports sessions to readable markdown
2. **`claude-session-tui.py`** - Interactive TUI for browsing, viewing, and resuming sessions (like giving Claude permanent memory!)

## Features

### Interactive TUI (`claude-session-tui.py`) ⭐ NEW!

- 🖥️ **Interactive Terminal Interface** - Browse all your Claude sessions in a beautiful TUI
- 🔍 **Search & Filter** - Quickly find sessions by ID, workspace, or directory
- 📊 **Session Analytics** - View token usage, tool statistics, and conversation metrics
- 💬 **Full Conversation View** - Read entire conversations with metadata and syntax highlighting
- 🚀 **Resume Sessions** - Launch sessions in new terminal windows with automatic directory switching
- 🧠 **Permanent Memory** - Never forget what you discussed with Claude!
- 📁 **Multi-Workspace Support** - Browse sessions across all your projects
- ⌨️ **Keyboard-Driven** - Fast navigation with immediate focus on session table
- 🏷️ **Smart Descriptions** - Sessions identified by `[directory] first message` format
- ⏳ **Loading Indicators** - Progress feedback for large conversations (>50 messages)

### Command-Line Parser (`view-claude-session.py`)

- 📜 **Export to Markdown** - Convert any session to readable markdown format
- 🔍 **List Sessions** - See all your past conversations with metadata
- 🎯 **Extended Thinking Support** - View Claude's extended thinking blocks
- 🖼️ **Image Detection** - Identify image content in conversations
- 📊 **Rich Metadata** - Model info, token usage, cache statistics
- 🛠️ **Complete Tool Tracking** - See all tool uses and their results (including nested tool results)
- ⚡ **Fast and Lightweight** - Pure Python, minimal dependencies
- 📱 **Cross-Platform** - Works on Windows, macOS, and Linux

## Installation

### Prerequisites

- Python 3.7 or higher
- Claude Code installed and configured

### Quick Install

```bash
# Clone the repository
git clone https://github.com/jtklinger/claude-session-viewer.git
cd claude-session-viewer

# For the command-line parser only (no dependencies)
python view-claude-session.py

# For the interactive TUI (requires textual)
pip install -r requirements.txt
python claude-session-tui.py
```

### Install TUI Dependencies

```bash
# Install required packages for the interactive TUI
pip install textual rich pygments

# Or use requirements.txt
pip install -r requirements.txt
```

### Optional: Add to PATH

**Linux/macOS:**
```bash
# Make executable
chmod +x view-claude-session.py

# Add to PATH (add to ~/.bashrc or ~/.zshrc)
export PATH="$PATH:/path/to/claude-session-viewer"

# Now run from anywhere
view-claude-session.py --list
```

**Windows:**
```powershell
# Add directory to PATH via System Environment Variables
# Then run from anywhere
python view-claude-session.py --list
```

## Usage

## Interactive TUI Mode (`claude-session-tui.py`) ⭐

### Launch the TUI

```bash
# Browse all sessions from all workspaces
python claude-session-tui.py

# Browse sessions from a specific workspace
python claude-session-tui.py --workspace C--Users-jtkli
```

### Keyboard Shortcuts

| Key | Action | Availability |
|-----|--------|--------------|
| **↑/↓** | Navigate session list | All tabs |
| **Enter** | View selected session details | Sessions tab |
| **Space** | Toggle selection for multi-delete (shows ✓ indicator) | All tabs |
| **D** | Delete selected session(s) with confirmation | All tabs |
| **Ctrl+N** | Resume session in new Windows Terminal window | All tabs |
| **R** | Refresh session list | Sessions tab only |
| **Tab** | Switch between tabs (Sessions/Conversation/Analytics) | All tabs |
| **Escape** | Back to session list | Conversation/Analytics tabs only |
| **Q** | Quit | All tabs |

### TUI Features

**Sessions Tab:**
- Browse all your Claude sessions with descriptive summaries showing `[directory-name] First user message...`
- Automatically filters out empty sessions (0 messages)
- Search by description, session ID, workspace, or directory
- See message count, token usage, and file size at a glance
- Sort by date (most recent first)
- Multi-select sessions with Space bar (shows ✓ indicator)
- Delete single or multiple sessions with confirmation (press 'D')
- Cursor starts on session table for immediate navigation

**Conversation Tab:**
- Read full conversation history
- Loading indicators for large conversations (>50 messages)
- View model information and token usage per message
- See all tool uses and results
- Syntax highlighting for code and JSON
- Focus automatically set to conversation view after loading

**Analytics Tab:**
- Total token usage (input/output/cache)
- Tool usage statistics
- Conversation timeline
- Session duration

### Browsing and Resuming Sessions

**Viewing Sessions:**
- Navigate sessions with ↑/↓ arrow keys (cursor starts on session table)
- Press Enter to view conversation details
- Conversation loads with progress indicators for large sessions
- Press Escape to return to session list (focus returns to table)
- Switch between Sessions/Conversation/Analytics tabs to explore

**Resuming Sessions (Ctrl+N):**
- Select a session and press Ctrl+N
- Opens new Windows Terminal tab in the session's original directory
- Uses full path to claude executable to avoid PATH issues
- Automatically resumes the session with `claude --resume <session-id>`
- TUI stays open so you can continue browsing other sessions

**Deleting Sessions:**

*Single Session:*
- Navigate to a session and press 'D'
- Confirm deletion
- Session file is permanently deleted

*Multiple Sessions (Bulk Delete):*
1. Press **Space** on first session (✓ indicator appears)
2. Navigate to other sessions and press **Space** to select them
3. Press **D** to delete all selected sessions at once
4. Confirmation shows total count and message count
5. Perfect for cleaning up multiple empty or test sessions

*Tips:*
- Space bar toggles selection (press again to deselect)
- Selected sessions show a ✓ checkmark in the description
- Delete works on current session if nothing is multi-selected

## Command-Line Parser Mode (`view-claude-session.py`)

### View Most Recent Session

```bash
python view-claude-session.py
```

This creates a markdown file like `claude-session-{SESSION_ID}.md` that you can open in any text editor or IDE.

### List Recent Sessions

```bash
python view-claude-session.py --list
```

Output:
```
Recent sessions in C--Users-jtkli:
--------------------------------------------------------------------------------
1. Session: a643dfaa-2606-4d83-94e9-a1cb50f95a7a
   Modified: 2025-11-11 09:37:52
   Size: 8.62 MB
   Messages: 2970

2. Session: 5d1c3323-fea7-4510-ab0c-01c49e515dc4
   Modified: 2025-11-11 09:25:57
   Size: 0.05 MB
   Messages: 3
```

### View Specific Session

```bash
# By session ID
python view-claude-session.py a643dfaa-2606-4d83-94e9-a1cb50f95a7a

# By full path
python view-claude-session.py ~/.claude/projects/C--Users-jtkli/session.jsonl
```

### Custom Output Filename

```bash
python view-claude-session.py --output my-conversation.md
```

### List More Sessions

```bash
python view-claude-session.py --list --limit 20
```

### Get Help

```bash
python view-claude-session.py --help
```

## Output Format

The exported markdown file includes:

- **Session metadata** - Session ID, file path, message count, generation timestamp
- **User messages** - All prompts you sent to Claude
- **Assistant messages** - All responses from Claude with model and token usage metadata
- **Extended Thinking** - Claude's extended thinking blocks (when present)
- **Tool usage** - Commands executed (Bash, Edit, Read, etc.) with parameters
- **Tool results** - Output from tool executions (properly handles nested results)
- **Images** - Image content indicators with media type and size
- **Token Statistics** - Input/output tokens, cache hits/creation per message

Example output structure:
```markdown
# Claude Code Session: a643dfaa-2606-4d83-94e9-a1cb50f95a7a

**Session File:** `/home/user/.claude/projects/.../session.jsonl`
**Total Messages:** 2970
**Generated:** 2025-11-11 10:30:00

---

## Message 1: User

check the health of the n8n-pod on kvm02

## Message 2: Assistant

*Model: `claude-sonnet-4-5-20250929` | Stop: `tool_use` | Tokens: in=245, out=87, cache_read=12450*

I'll check the pod health on kvm02...

**[Tool Use: mcp__ssh-mcp-kvm02__exec]**
```json
{
  "command": "podman pod ps"
}
```

## Message 3: User

**[Tool Result: SUCCESS]**
```
POD ID        NAME      STATUS    CREATED     INFRA ID
abc123def     n8n-pod   Running   2 days ago  xyz789
```
```

## Use Cases

### Permanent Memory with the TUI ⭐

The interactive TUI gives Claude effectively "permanent memory" across sessions:

```bash
# Launch the TUI
python claude-session-tui.py

# Browse your session history with ↑/↓ arrow keys
# Press Enter to view any past conversation
# Press Ctrl+N to resume in a new terminal window
```

**Why this is powerful:**
- Remember what you discussed weeks ago
- Continue complex projects across multiple days
- Find that perfect prompt you used before
- Review what worked and what didn't
- Share context between different Claude sessions
- Sessions automatically identified by `[directory] description` format

### After System Reboot

If you exit Claude Code and reboot your workstation, your terminal scrollback is lost. Use the TUI or parser to review what was discussed:

```bash
python view-claude-session.py --list
python view-claude-session.py {SESSION_ID}
code claude-session-{SESSION_ID}.md
```

### Before Using `/compact`

While Claude Code has a `/compact` command to create summaries, you might want the full conversation history. Export the session first:

```bash
python view-claude-session.py --output full-conversation.md
```

Then run `/compact` in Claude Code.

### Sharing Conversations

Export a session to share with team members or for documentation:

```bash
python view-claude-session.py abc123 --output project-setup-walkthrough.md
```

### Troubleshooting

Review the exact commands and outputs from a debugging session:

```bash
python view-claude-session.py --output debug-session.md
```

## How It Works

Claude Code stores conversation sessions as JSONL (JSON Lines) files:

```
~/.claude/
  └── projects/
      └── {WORKSPACE}/
          ├── {SESSION_ID_1}.jsonl
          ├── {SESSION_ID_2}.jsonl
          └── ...
```

Each line in the JSONL file is a JSON object representing:
- User messages
- Assistant responses
- Tool invocations
- Tool results
- Metadata (timestamps, file snapshots, etc.)

This script:
1. Locates the session file by ID or uses the most recent
2. Parses each JSON line
3. Extracts relevant conversation data
4. Formats it as readable markdown
5. Exports to a file you can open in any editor

## Limitations

### Command-Line Parser

- **Large sessions** (>1000 messages) create large markdown files
- **Tool results and thinking blocks are truncated** to keep files manageable
- **Some internal Claude Code metadata** is not included (checkpoints, file snapshots, summaries)

### Interactive TUI

- **Requires Textual** - Adds a dependency (unlike the parser which is pure Python)
- **New terminal resume on Windows only** - Ctrl+N uses `wt.exe` (Windows Terminal)
- **Large sessions may take time to load** - Full conversation view loads all messages (loading indicators shown for >50 messages)
- **Agent sessions hidden by default** - Agent sub-task sessions don't appear in the session list (but can be viewed if you know the ID)

## Tips

### TUI Tips

- **Keyboard-driven workflow** - Cursor starts on session table, use ↑/↓ to navigate immediately
- **Quick identification** - Sessions show `[directory] description` format for easy recognition
- **Use search** - Type in search box to filter by directory, description, or session ID
- **Check analytics** - View token usage to understand API consumption
- **Resume sessions** - Use Ctrl+N to continue old conversations in a new terminal
- **Multi-workspace** - Browse all projects at once or filter with `--workspace`
- **Context-aware bindings** - Footer shows only relevant shortcuts for current tab

### Parser Tips

- Use `--list` regularly to see your session history
- Export important conversations for documentation
- Large markdown files may take a moment to open in some editors
- Use Ctrl+F in your editor to search the exported conversation

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Ideas for Contributions

- Add filtering by date range in TUI
- Export to other formats (HTML, PDF, JSON)
- ~~Interactive TUI for browsing sessions~~ ✅ Implemented!
- Search within conversation content (not just metadata)
- Include checkpoint information
- ~~Statistics and analytics on tool usage~~ ✅ Implemented!
- Session comparison (diff between sessions)
- Export sessions directly from TUI
- Session tagging and categorization
- Cost estimation based on token usage and pricing

## License

MIT License - See [LICENSE](LICENSE) file for details

## Related Projects

- [Claude Code](https://claude.com/claude-code) - The official Claude CLI
- [Claude Code Documentation](https://code.claude.com/docs/en/overview.md)

## Troubleshooting

### "Error: Claude directory not found"

Make sure Claude Code is installed and you've run at least one session:
```bash
claude --version
```

### "Error: No session files found"

Check if sessions exist:
```bash
ls -la ~/.claude/projects/
```

### Unicode encoding errors (Windows)

The script uses ASCII-safe characters for output. If you still see errors, ensure your Python installation supports UTF-8:
```bash
python -c "import sys; print(sys.getdefaultencoding())"
```

## Acknowledgments

Created to solve the problem of viewing Claude Code conversation history after terminal scrollback is lost.

## Contact

Issues and feature requests: [GitHub Issues](https://github.com/jtklinger/claude-session-viewer/issues)
