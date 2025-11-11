# Claude Code Session Viewer

A Python utility to parse and view Claude Code conversation history in a readable markdown format.

## Overview

When using [Claude Code](https://claude.com/claude-code), conversation sessions are stored as JSONL files in `~/.claude/projects/`. While Claude can resume these sessions and load the context, the conversation history isn't re-displayed in your terminal after resuming.

This tool solves that problem by parsing the JSONL session files and exporting them to readable markdown documents that you can open in your IDE or text editor.

## Features

- 📜 **Parse any Claude Code session** - View complete conversation history
- 🔍 **List recent sessions** - See all your past conversations with metadata
- 📊 **Rich formatting** - Markdown output with syntax highlighting for code blocks
- 🛠️ **Tool tracking** - See all tool uses and their results
- ⚡ **Fast and lightweight** - Pure Python with no external dependencies
- 📱 **Cross-platform** - Works on Windows, macOS, and Linux

## Installation

### Prerequisites

- Python 3.7 or higher
- Claude Code installed and configured

### Quick Install

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/claude-session-viewer.git
cd claude-session-viewer

# Run directly (no installation needed)
python view-claude-session.py
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
- **Assistant messages** - All responses from Claude
- **Tool usage** - Commands executed (Bash, Edit, Read, etc.) with parameters
- **Tool results** - Output from tool executions (truncated if very long)

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

I'll check the pod health on kvm02...

**[Tool Use: mcp__ssh-mcp-kvm02__exec]**
```json
{
  "command": "podman pod ps"
}
```

**[Tool Result: SUCCESS]**
```
POD ID        NAME      STATUS    CREATED     INFRA ID
abc123def     n8n-pod   Running   2 days ago  xyz789
```
```

## Use Cases

### After System Reboot

If you exit Claude Code and reboot your workstation, your terminal scrollback is lost. Use this tool to review what was discussed:

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

- **No external dependencies**, but also no advanced parsing
- **Large sessions** (>1000 messages) create large markdown files
- **Tool results are truncated** at 2000 characters to keep files manageable
- **Some internal Claude Code metadata** is not included (checkpoints, file snapshots, etc.)

## Tips

- Use `--list` regularly to see your session history
- Export important conversations for documentation
- Large markdown files may take a moment to open in some editors
- Use Ctrl+F in your editor to search the exported conversation

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Ideas for Contributions

- Add filtering by date range
- Export to other formats (HTML, PDF, JSON)
- Interactive TUI for browsing sessions
- Search within sessions before exporting
- Include checkpoint information
- Statistics and analytics on tool usage

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

Issues and feature requests: [GitHub Issues](https://github.com/YOUR_USERNAME/claude-session-viewer/issues)
