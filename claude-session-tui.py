#!/usr/bin/env python3
"""
Claude Session Viewer - Interactive TUI for browsing and resuming Claude Code sessions.

This provides an interactive terminal interface to:
- Browse all Claude sessions across workspaces
- View full conversation history with metadata
- See session analytics (token usage, tool stats)
- Resume sessions directly in current or new terminal

Usage:
    python claude-session-tui.py                 # Show all sessions
    python claude-session-tui.py --workspace NAME # Show specific workspace
"""

import json
import sys
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict
import argparse

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, DataTable, Static, Label, Tree,
    Input, Button, TabbedContent, TabPane, Markdown, RichLog, TextArea
)
from textual.binding import Binding
from textual.screen import Screen
from textual import events
from rich.syntax import Syntax
from rich.markdown import Markdown as RichMarkdown
from rich.table import Table as RichTable
from rich.text import Text


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class SessionMetadata:
    """Metadata for a Claude session."""
    session_id: str
    workspace: str
    file_path: Path
    modified: datetime
    size_bytes: int
    message_count: int
    first_message_time: Optional[datetime] = None
    last_message_time: Optional[datetime] = None
    model: Optional[str] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_create_tokens: int = 0
    tool_usage: Dict[str, int] = None
    cwd: Optional[str] = None
    description: Optional[str] = None  # Auto-generated from first user message
    custom_tag: Optional[str] = None  # User-defined custom tag/description

    def __post_init__(self):
        if self.tool_usage is None:
            self.tool_usage = {}


@dataclass
class Message:
    """A single message in a conversation."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    line_num: int = 0
    git_branch: Optional[str] = None
    claude_version: Optional[str] = None


# ============================================================================
# SESSION PARSING AND LOADING
# ============================================================================

class SessionLoader:
    """Loads and parses Claude session files."""

    @staticmethod
    def _get_meta_file(session_file: Path) -> Path:
        """Get the sidecar metadata file path for a session."""
        return session_file.with_suffix('.meta.json')

    @staticmethod
    def _load_custom_tag(session_file: Path) -> Optional[str]:
        """Load custom tag from sidecar metadata file if it exists."""
        meta_file = SessionLoader._get_meta_file(session_file)
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('custom_tag')
            except Exception:
                pass
        return None

    @staticmethod
    def save_custom_tag(session_file: Path, custom_tag: Optional[str]) -> bool:
        """Save custom tag to sidecar metadata file."""
        meta_file = SessionLoader._get_meta_file(session_file)
        try:
            if custom_tag:
                # Save tag to metadata file
                data = {'custom_tag': custom_tag}
                with open(meta_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            else:
                # Remove metadata file if tag is empty/None
                if meta_file.exists():
                    meta_file.unlink()
            return True
        except Exception:
            return False

    @staticmethod
    def get_claude_dir() -> Path:
        """Get the Claude Code directory."""
        claude_dir = Path.home() / ".claude"
        if not claude_dir.exists():
            raise FileNotFoundError(f"Claude directory not found at {claude_dir}")
        return claude_dir

    @staticmethod
    def get_all_workspaces() -> List[str]:
        """Get all workspace names."""
        claude_dir = SessionLoader.get_claude_dir()
        projects_base = claude_dir / "projects"

        if not projects_base.exists():
            return []

        return [d.name for d in projects_base.iterdir() if d.is_dir()]

    @staticmethod
    def list_sessions(workspace: Optional[str] = None, custom_paths: Optional[List[Path]] = None) -> List[SessionMetadata]:
        """List all sessions, optionally filtered by workspace or from custom paths."""
        sessions = []

        # If custom paths are provided, scan those instead of the default location
        if custom_paths:
            for custom_path in custom_paths:
                if not custom_path.exists():
                    continue

                # If it's a directory, scan for .jsonl files recursively
                if custom_path.is_dir():
                    for session_file in custom_path.rglob("*.jsonl"):
                        # Skip history.jsonl and other non-session files
                        if session_file.name == "history.jsonl":
                            continue
                        # Skip agent sessions by default
                        if session_file.stem.startswith("agent-"):
                            continue

                        try:
                            # Use parent directory name as workspace
                            ws = session_file.parent.name
                            metadata = SessionLoader._extract_metadata(session_file, ws)
                            sessions.append(metadata)
                        except Exception:
                            continue
                # If it's a file, try to load it directly
                elif custom_path.is_file() and custom_path.suffix == ".jsonl":
                    try:
                        ws = custom_path.parent.name
                        metadata = SessionLoader._extract_metadata(custom_path, ws)
                        sessions.append(metadata)
                    except Exception:
                        pass
        else:
            # Default behavior: scan ~/.claude/projects/
            claude_dir = SessionLoader.get_claude_dir()
            projects_base = claude_dir / "projects"

            if not projects_base.exists():
                return []

            # Determine which workspaces to scan
            if workspace:
                workspaces = [workspace]
            else:
                workspaces = [d.name for d in projects_base.iterdir() if d.is_dir()]

            for ws in workspaces:
                ws_dir = projects_base / ws
                if not ws_dir.exists():
                    continue

                # Find all .jsonl files (excluding agent sessions by default)
                for session_file in ws_dir.glob("*.jsonl"):
                    # Skip agent sessions in list view (can still be viewed if opened directly)
                    if session_file.stem.startswith("agent-"):
                        continue

                    try:
                        metadata = SessionLoader._extract_metadata(session_file, ws)
                        sessions.append(metadata)
                    except Exception:
                        # Skip corrupted sessions
                        continue

        # Sort by modification time, most recent first
        sessions.sort(key=lambda s: s.modified, reverse=True)
        return sessions

    @staticmethod
    def _find_meaningful_message(user_messages: List[str]) -> Optional[str]:
        """
        Find the first meaningful task/request message from a list of user messages.

        Skips over:
        - Common continuation phrases (continue, ok, yes, etc.)
        - Very short messages (< 20 characters)
        - Session resume indicators

        Returns the first message that:
        - Is at least 30 characters long
        - Contains task/request indicators (action verbs, questions, etc.)
        """
        # Skip patterns (lowercase for case-insensitive matching)
        skip_patterns = [
            # Continuation phrases
            'continue', 'ok', 'yes', 'go ahead', 'proceed', 'sure',
            'please continue', 'keep going', 'go on',
            'continuing from', 'resuming', 'resume from',
            'sounds good', 'looks good', 'perfect', 'great',
            'done', 'finished', 'completed',
            # System/automated messages
            'caveat:', 'the messages below were generated',
            '<command-name>', '<local-command-stdout>', '<command-message>',
            'context usage', 'mcp tools', 'memory files',
            '/context', '/model', 'set model to'
        ]

        # Task/request indicators
        task_indicators = [
            # Imperative verbs
            'help', 'create', 'make', 'fix', 'add', 'update', 'change', 'modify',
            'remove', 'delete', 'build', 'implement', 'write', 'read', 'show',
            'display', 'check', 'test', 'review', 'analyze', 'debug', 'install',
            'configure', 'setup', 'deploy', 'run', 'execute', 'search', 'find',
            # Question words
            'how', 'what', 'when', 'where', 'why', 'which', 'who',
            'can you', 'could you', 'would you', 'will you',
            # Request patterns
            'i need', 'i want', 'i would like', 'please', 'let\'s'
        ]

        for message in user_messages:
            message_lower = message.lower()
            message_start = message_lower[:100]  # Check first 100 chars for system patterns

            # Skip if message is too short
            if len(message) < 20:
                continue

            # Always skip system/automated messages (check beginning of message)
            system_skip = [
                'caveat:', '<command-name>', '<local-command-stdout>',
                'the messages below were generated', 'context usage',
                '/context', '/model', 'set model to'
            ]
            if any(pattern in message_start for pattern in system_skip):
                continue

            # Skip if matches common skip patterns
            if any(pattern in message_lower for pattern in skip_patterns):
                # But only skip if the ENTIRE message is basically the skip pattern
                # Allow messages like "ok, now let's create a function"
                if len(message) < 50:  # Short message with skip pattern -> skip it
                    continue

            # Accept if message is substantial (30+ chars) AND contains task indicators
            if len(message) >= 30:
                if any(indicator in message_lower for indicator in task_indicators):
                    return message
                # Also accept if it's long enough and doesn't match skip patterns
                # (fallback for messages that are clearly tasks but don't match our patterns)
                elif len(message) >= 50:
                    return message

        # Fallback: return first non-skip message if nothing matched
        for message in user_messages:
            if len(message) >= 20:
                message_lower = message.lower()
                if not any(pattern in message_lower for pattern in skip_patterns):
                    return message

        # Last resort: return first message if we have any
        return user_messages[0] if user_messages else None

    @staticmethod
    def _extract_metadata(session_file: Path, workspace: str) -> SessionMetadata:
        """Extract metadata from a session file without loading full content."""
        session_id = session_file.stem
        stat = session_file.stat()

        # Quick scan to get message count and basic info
        message_count = 0
        first_timestamp = None
        last_timestamp = None
        model = None
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_create = 0
        tool_usage = defaultdict(int)
        cwd = None
        user_messages = []  # Collect first 10 user messages for smart parsing

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        msg_type = data.get('type')

                        if msg_type in ['user', 'assistant']:
                            message_count += 1
                            timestamp = data.get('timestamp')

                            if timestamp:
                                if not first_timestamp:
                                    first_timestamp = timestamp
                                last_timestamp = timestamp

                            # Collect first 10 user messages for smart description parsing
                            if msg_type == 'user' and len(user_messages) < 10:
                                message = data.get('message', {})
                                content = message.get('content', '')
                                msg_text = None
                                if isinstance(content, str):
                                    msg_text = content.strip()
                                elif isinstance(content, list):
                                    # Extract text from content blocks
                                    for block in content:
                                        if isinstance(block, dict) and block.get('type') == 'text':
                                            msg_text = block.get('text', '').strip()
                                            break
                                        elif isinstance(block, str):
                                            msg_text = block.strip()
                                            break
                                if msg_text:
                                    user_messages.append(msg_text)

                            if msg_type == 'assistant':
                                message = data.get('message', {})
                                if not model:
                                    model = message.get('model')

                                # Accumulate token usage
                                usage = message.get('usage', {})
                                total_input += usage.get('input_tokens', 0)
                                total_output += usage.get('output_tokens', 0)
                                total_cache_read += usage.get('cache_read_input_tokens', 0)
                                total_cache_create += usage.get('cache_creation_input_tokens', 0)

                                # Count tool usage
                                content = message.get('content', [])
                                if isinstance(content, list):
                                    for block in content:
                                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                                            tool_name = block.get('name', 'unknown')
                                            tool_usage[tool_name] += 1

                        # Extract cwd from user messages
                        if msg_type == 'user' and not cwd:
                            cwd = data.get('cwd')

                    except (json.JSONDecodeError, Exception):
                        continue
        except Exception:
            pass

        # Convert timestamps to datetime if available
        first_dt = None
        last_dt = None
        if first_timestamp:
            try:
                first_dt = datetime.fromisoformat(first_timestamp.replace('Z', '+00:00'))
            except:
                pass
        if last_timestamp:
            try:
                last_dt = datetime.fromisoformat(last_timestamp.replace('Z', '+00:00'))
            except:
                pass

        # Smart description parsing: find first meaningful task/request message
        description = None
        meaningful_message = SessionLoader._find_meaningful_message(user_messages)

        if meaningful_message:
            # Truncate to ~80 chars for the message part
            message_part = meaningful_message[:80]
            if len(meaningful_message) > 80:
                message_part = message_part.rsplit(' ', 1)[0] + '...'
            # Clean up newlines
            message_part = message_part.replace('\n', ' ').replace('\r', '')

            # Prepend directory name if available for better context
            if cwd:
                # Get just the directory name (last part of path)
                dir_name = Path(cwd).name
                description = f"[{dir_name}] {message_part}"
            else:
                description = message_part
        elif cwd:
            # Use working directory if no first message
            description = f"[{cwd}]"
        else:
            description = "[Empty session]"

        # Load custom tag from sidecar file if it exists
        custom_tag = SessionLoader._load_custom_tag(session_file)

        return SessionMetadata(
            session_id=session_id,
            workspace=workspace,
            file_path=session_file,
            modified=datetime.fromtimestamp(stat.st_mtime),
            size_bytes=stat.st_size,
            message_count=message_count,
            first_message_time=first_dt,
            last_message_time=last_dt,
            model=model,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_read_tokens=total_cache_read,
            total_cache_create_tokens=total_cache_create,
            tool_usage=dict(tool_usage),
            cwd=cwd,
            description=description,
            custom_tag=custom_tag
        )

    @staticmethod
    def load_session_messages(session_file: Path, limit: Optional[int] = None) -> List[Message]:
        """Load all messages from a session file."""
        messages = []

        with open(session_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line)
                    msg_type = data.get('type')

                    if msg_type == 'user':
                        message = data.get('message', {})
                        content = SessionLoader._format_content(message.get('content', ''))
                        timestamp = data.get('timestamp')
                        git_branch = data.get('gitBranch')
                        claude_version = data.get('version')

                        messages.append(Message(
                            role='user',
                            content=content,
                            timestamp=timestamp,
                            line_num=line_num,
                            git_branch=git_branch,
                            claude_version=claude_version
                        ))

                    elif msg_type == 'assistant':
                        message = data.get('message', {})
                        content = SessionLoader._format_content(message.get('content', ''))
                        timestamp = data.get('timestamp')
                        git_branch = data.get('gitBranch')
                        claude_version = data.get('version')

                        # Extract metadata
                        metadata = {}
                        metadata['model'] = message.get('model')
                        metadata['stop_reason'] = message.get('stop_reason')
                        usage = message.get('usage', {})
                        if usage:
                            metadata['usage'] = usage

                        messages.append(Message(
                            role='assistant',
                            content=content,
                            timestamp=timestamp,
                            metadata=metadata,
                            line_num=line_num,
                            git_branch=git_branch,
                            claude_version=claude_version
                        ))

                    if limit and len(messages) >= limit:
                        break

                except (json.JSONDecodeError, Exception):
                    continue

        return messages

    @staticmethod
    def _format_content(content: Any) -> str:
        """Format message content for display."""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get('type')

                    if block_type == 'text':
                        parts.append(block.get('text', ''))

                    elif block_type == 'tool_use':
                        tool_name = block.get('name', 'unknown')
                        tool_input = json.dumps(block.get('input', {}), indent=2)
                        parts.append(f"\n[Tool: {tool_name}]\n{tool_input}\n")

                    elif block_type == 'tool_result':
                        tool_id = block.get('tool_use_id', 'unknown')
                        is_error = block.get('is_error', False)
                        result = block.get('content', '')
                        status = "ERROR" if is_error else "OK"
                        if isinstance(result, str):
                            # Truncate long results
                            if len(result) > 1000:
                                result = result[:1000] + f"\n... ({len(result)} chars total)"
                            parts.append(f"\n[Tool Result {status}]\n{result}\n")

                    elif block_type == 'thinking':
                        thinking = block.get('thinking', '')
                        if len(thinking) > 500:
                            thinking = thinking[:500] + f"... ({len(thinking)} chars total)"
                        parts.append(f"\n[Thinking]\n{thinking}\n")

                    elif block_type == 'image':
                        source = block.get('source', {})
                        media_type = source.get('media_type', 'unknown')
                        parts.append(f"\n[Image: {media_type}]\n")

                elif isinstance(block, str):
                    parts.append(block)

            return '\n'.join(parts)
        else:
            return str(content)

    @staticmethod
    def search_session_content(session_file: Path, search_term: str) -> bool:
        """
        Search the full content of a session file for a search term.
        Returns True if the term is found in any message.
        """
        search_lower = search_term.lower()
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        msg_type = data.get('type')

                        if msg_type in ['user', 'assistant']:
                            message = data.get('message', {})
                            content = message.get('content', '')

                            # Handle string content
                            if isinstance(content, str):
                                if search_lower in content.lower():
                                    return True
                            # Handle list content (blocks)
                            elif isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict):
                                        # Check text blocks
                                        if block.get('type') == 'text':
                                            text = block.get('text', '')
                                            if search_lower in text.lower():
                                                return True
                                        # Check thinking blocks
                                        elif block.get('type') == 'thinking':
                                            thinking = block.get('thinking', '')
                                            if search_lower in thinking.lower():
                                                return True
                                        # Check tool use
                                        elif block.get('type') == 'tool_use':
                                            tool_input = json.dumps(block.get('input', {}))
                                            if search_lower in tool_input.lower():
                                                return True
                                    elif isinstance(block, str):
                                        if search_lower in block.lower():
                                            return True
                    except (json.JSONDecodeError, Exception):
                        continue
        except Exception:
            pass
        return False


# ============================================================================
# TEXTUAL WIDGETS
# ============================================================================

class SessionBrowser(Container):
    """Widget showing the list of sessions."""

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Horizontal(id="search-bar"):
            yield Input(placeholder="Search sessions (prefix with // for deep search)...", id="search-input")
        yield DataTable(id="session-table")

    def on_mount(self) -> None:
        """Set up the table when mounted."""
        table = self.query_one("#session-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        # Add columns
        table.add_column("Date", width=20)
        table.add_column("Tag", width=25)  # Custom user-defined tag
        table.add_column("Description", width=45)  # Auto-generated description
        table.add_column("Workspace", width=25)
        table.add_column("Messages", width=10)
        table.add_column("Tokens", width=12)
        table.add_column("Size", width=10)


class SessionDetail(VerticalScroll):
    """Widget showing detailed session conversation."""

    BINDINGS = [
        Binding("ctrl+home", "scroll_home", "Ctrl+Home: Top", show=True),
        Binding("ctrl+end", "scroll_end", "Ctrl+End: Bottom", show=True),
        Binding("pageup", "page_up", "PgUp", show=True),
        Binding("pagedown", "page_down", "PgDn", show=True),
        Binding("ctrl+up", "prev_message", "Ctrl+↑: Prev Msg", show=True),
        Binding("ctrl+down", "next_message", "Ctrl+↓: Next Msg", show=True),
        Binding("slash", "start_search", "/: Search", show=True),
        Binding("n", "find_next", "n: Next", show=True),
        Binding("shift+n", "find_prev", "N: Prev", show=True),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message_positions = []  # List of y-positions for each message separator
        self.current_message_index = 0
        self.search_term = ""
        self.search_matches = []  # List of (line, col) positions
        self.current_match_index = -1

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        # Label for displaying custom tag
        yield Label("", id="conversation-tag")
        # Search input (hidden by default)
        yield Input(placeholder="Search in conversation...", id="conversation-search")
        # Use TextArea for selectable, copyable text
        yield TextArea(id="conversation-log", read_only=True, show_line_numbers=False)

    def action_scroll_home(self) -> None:
        """Scroll to the top of the conversation."""
        text_area = self.query_one("#conversation-log", TextArea)
        text_area.move_cursor((0, 0))
        self.current_message_index = 0

    def action_scroll_end(self) -> None:
        """Scroll to the bottom of the conversation."""
        text_area = self.query_one("#conversation-log", TextArea)
        # Move to the last line
        last_line = len(text_area.text.split('\n')) - 1
        text_area.move_cursor((last_line, 0))
        if self.message_positions:
            self.current_message_index = len(self.message_positions) - 1

    def action_page_up(self) -> None:
        """Scroll up one page."""
        self.scroll_page_up()

    def action_page_down(self) -> None:
        """Scroll down one page."""
        self.scroll_page_down()

    def action_prev_message(self) -> None:
        """Jump to the previous message."""
        if not self.message_positions:
            return

        if self.current_message_index > 0:
            self.current_message_index -= 1
            # Get the TextArea and scroll it to the line number
            text_area = self.query_one("#conversation-log", TextArea)
            target_line = self.message_positions[self.current_message_index]
            # Move cursor to the target line - this will scroll the view
            text_area.move_cursor((target_line, 0))

    def action_next_message(self) -> None:
        """Jump to the next message."""
        if not self.message_positions:
            return

        if self.current_message_index < len(self.message_positions) - 1:
            self.current_message_index += 1
            # Get the TextArea and scroll it to the line number
            text_area = self.query_one("#conversation-log", TextArea)
            target_line = self.message_positions[self.current_message_index]
            # Move cursor to the target line - this will scroll the view
            text_area.move_cursor((target_line, 0))

    def set_message_positions(self, positions: list):
        """Set the message separator positions for navigation."""
        self.message_positions = positions
        self.current_message_index = 0

    def on_mount(self) -> None:
        """Hide search input on mount."""
        search_input = self.query_one("#conversation-search", Input)
        search_input.display = False

    def action_start_search(self) -> None:
        """Show the search input."""
        search_input = self.query_one("#conversation-search", Input)
        search_input.display = True
        search_input.value = ""
        search_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search submission."""
        if event.input.id == "conversation-search":
            self.perform_search(event.value)
            # Hide search input and return focus to text area
            event.input.display = False
            text_area = self.query_one("#conversation-log", TextArea)
            self.app.set_focus(text_area)

    def on_key(self, event) -> None:
        """Handle key events for search input."""
        search_input = self.query_one("#conversation-search", Input)
        if search_input.display and event.key == "escape":
            # Cancel search and hide input
            search_input.display = False
            text_area = self.query_one("#conversation-log", TextArea)
            self.app.set_focus(text_area)
            event.stop()

    def perform_search(self, search_term: str) -> None:
        """Search for term in conversation and jump to first match."""
        if not search_term:
            return

        self.search_term = search_term.lower()
        self.search_matches = []
        self.current_match_index = -1

        text_area = self.query_one("#conversation-log", TextArea)
        lines = text_area.text.split('\n')

        # Find all matches
        for line_num, line in enumerate(lines):
            line_lower = line.lower()
            col = 0
            while True:
                pos = line_lower.find(self.search_term, col)
                if pos == -1:
                    break
                self.search_matches.append((line_num, pos))
                col = pos + 1

        if self.search_matches:
            self.current_match_index = 0
            self.go_to_match(0)
            self.app.notify(f"Found {len(self.search_matches)} matches", severity="information")
        else:
            self.app.notify(f"No matches for '{search_term}'", severity="warning")

    def go_to_match(self, index: int) -> None:
        """Jump to a specific match."""
        if not self.search_matches or index < 0 or index >= len(self.search_matches):
            return

        line, col = self.search_matches[index]
        text_area = self.query_one("#conversation-log", TextArea)
        text_area.move_cursor((line, col))

    def action_find_next(self) -> None:
        """Jump to next search match."""
        if not self.search_matches:
            if self.search_term:
                self.app.notify("No matches", severity="warning")
            return

        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        self.go_to_match(self.current_match_index)
        self.app.notify(f"Match {self.current_match_index + 1}/{len(self.search_matches)}", severity="information")

    def action_find_prev(self) -> None:
        """Jump to previous search match."""
        if not self.search_matches:
            if self.search_term:
                self.app.notify("No matches", severity="warning")
            return

        self.current_match_index = (self.current_match_index - 1) % len(self.search_matches)
        self.go_to_match(self.current_match_index)
        self.app.notify(f"Match {self.current_match_index + 1}/{len(self.search_matches)}", severity="information")

    def clear_search(self) -> None:
        """Clear search state."""
        self.search_term = ""
        self.search_matches = []
        self.current_match_index = -1


class SessionAnalytics(Container):
    """Widget showing session analytics and statistics."""

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Static(id="analytics-content")


# ============================================================================
# MAIN APPLICATION
# ============================================================================

class SessionViewerApp(App):
    """Main TUI application for viewing Claude sessions."""

    CSS = """
    Screen {
        layers: base overlay;
    }

    #search-bar {
        dock: top;
        height: auto;
        margin: 1;
    }

    #search-input {
        width: 100%;
    }

    #session-table {
        height: 100%;
    }

    #conversation-tag {
        dock: top;
        width: 100%;
        background: $accent;
        color: $text;
        padding: 0 2;
        text-align: center;
        height: auto;
    }

    #conversation-search {
        dock: top;
        width: 100%;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $warning;
    }

    #conversation-log {
        height: 100%;
        border: solid $accent;
    }

    TextArea {
        background: $surface;
    }

    #analytics-content {
        height: 100%;
        padding: 1 2;
    }

    TabbedContent {
        height: 100%;
    }

    .help-text {
        background: $boost;
        padding: 1 2;
        margin: 1;
    }

    #confirm-dialog {
        background: $surface;
        border: thick $error;
        padding: 2 4;
        width: 60;
        height: auto;
    }

    #confirm-dialog Label {
        width: 100%;
        content-align: center middle;
        padding: 1 0;
    }

    #confirm-dialog Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0;
    }

    #confirm-dialog Button {
        margin: 0 1;
    }

    #tag-dialog {
        background: $surface;
        border: thick $accent;
        padding: 2 4;
        width: 80;
        height: auto;
    }

    #tag-dialog Label {
        width: 100%;
        padding: 0 0 1 0;
    }

    #tag-dialog Input {
        width: 100%;
        margin: 1 0;
    }

    #tag-dialog Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0;
    }

    #tag-dialog Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("t", "edit_tag", "Edit Tag"),
        Binding("space", "toggle_selection", "Toggle Selection"),
        Binding("d", "delete_session", "Delete Session(s)"),
        # Enter is handled by on_data_table_row_selected event, not app-level binding
        Binding("ctrl+n", "resume_new_terminal", "Resume Session"),
        Binding("escape", "back_to_list", "Back to List"),
    ]

    TITLE = "Claude Session Viewer"

    def __init__(self, workspace: Optional[str] = None, custom_paths: Optional[List[Path]] = None):
        """Initialize the app."""
        super().__init__()
        self.workspace_filter = workspace
        self.custom_paths = custom_paths
        self.sessions: List[SessionMetadata] = []
        self.selected_session: Optional[SessionMetadata] = None
        self.selected_for_delete: set = set()  # Track multi-selected sessions
        self.current_view = "list"  # 'list', 'detail', 'analytics'

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(show_clock=True)

        with TabbedContent(initial="browser"):
            with TabPane("Sessions", id="browser"):
                yield SessionBrowser()

            with TabPane("Conversation", id="detail"):
                yield SessionDetail()

            with TabPane("Analytics", id="analytics"):
                yield SessionAnalytics()

        yield Footer()

    def on_mount(self) -> None:
        """Called when app starts."""
        self.load_sessions()
        self.populate_table()
        # Set focus to the session table so user can immediately navigate with arrow keys
        self.set_focus(self.query_one("#session-table"))

    def load_sessions(self) -> None:
        """Load all sessions from disk."""
        try:
            self.sessions = SessionLoader.list_sessions(self.workspace_filter, self.custom_paths)
        except Exception as e:
            self.notify(f"Error loading sessions: {e}", severity="error")
            self.sessions = []

    def populate_table(self, filter_text: str = "", deep_search: bool = False) -> None:
        """Populate the sessions table."""
        table = self.query_one("#session-table", DataTable)
        table.clear()

        # Filter out empty sessions and apply search filter
        filtered = [s for s in self.sessions if s.message_count > 0]

        if filter_text:
            # Check for deep search prefix
            if filter_text.startswith("//"):
                deep_search = True
                filter_text = filter_text[2:].strip()
                if not filter_text:
                    # Just "//" with no search term - show all
                    deep_search = False

            if filter_text:
                filter_lower = filter_text.lower()

                if deep_search:
                    # Deep search: search full conversation content
                    self.notify(f"Deep searching for '{filter_text}'...", severity="information")
                    deep_results = []
                    for s in filtered:
                        # First check quick fields
                        if (filter_lower in s.session_id.lower()
                            or filter_lower in s.workspace.lower()
                            or (s.description and filter_lower in s.description.lower())
                            or (s.custom_tag and filter_lower in s.custom_tag.lower())
                            or (s.cwd and filter_lower in s.cwd.lower())):
                            deep_results.append(s)
                        # Then do deep content search
                        elif SessionLoader.search_session_content(s.file_path, filter_text):
                            deep_results.append(s)
                    filtered = deep_results
                    self.notify(f"Found {len(filtered)} sessions", severity="information")
                else:
                    # Quick search: only search metadata fields
                    filtered = [
                        s for s in filtered
                        if filter_lower in s.session_id.lower()
                        or filter_lower in s.workspace.lower()
                        or (s.description and filter_lower in s.description.lower())
                        or (s.custom_tag and filter_lower in s.custom_tag.lower())
                        or (s.cwd and filter_lower in s.cwd.lower())
                    ]

        # Add rows
        for session in filtered:
            date_str = session.modified.strftime("%Y-%m-%d %H:%M:%S")
            tokens_str = f"{session.total_input_tokens + session.total_output_tokens:,}"
            size_str = f"{session.size_bytes / 1024 / 1024:.1f} MB"

            # Custom tag (user-defined)
            tag = session.custom_tag or ""

            # Auto-generated description with selection indicator
            description = session.description or "[No description]"
            if session.session_id in self.selected_for_delete:
                description = f"[✓] {description}"

            table.add_row(
                date_str,
                tag,
                description,
                session.workspace,
                str(session.message_count),
                tokens_str,
                size_str,
                key=session.session_id
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "search-input":
            self.populate_table(event.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the sessions table - fires when Enter is pressed."""
        if event.data_table.id != "session-table":
            return

        session_id = event.row_key.value
        self.selected_session = next(
            (s for s in self.sessions if s.session_id == session_id),
            None
        )

        if not self.selected_session:
            self.notify("Session not found", severity="error")
            return

        # Show loading notification immediately for large conversations
        if self.selected_session.message_count > 50:
            self.notify(f"Loading {self.selected_session.message_count} messages...", severity="information")

        # Defer tab switch and conversation loading until after event completes
        # This prevents race conditions with Textual's event processing
        def switch_and_load():
            tabbed = self.query_one(TabbedContent)
            tabbed.active = "detail"

            # Show loading message in the text area before starting the actual load
            if self.selected_session.message_count > 50:
                text_area = self.query_one("#conversation-log", TextArea)
                text_area.text = f"Loading conversation...\n{self.selected_session.message_count} messages"

            # Defer the actual conversation loading to let the loading message display
            def do_load():
                self.load_conversation()
                self.load_analytics()

                # Set focus to the conversation log
                try:
                    text_area = self.query_one("#conversation-log", TextArea)
                    self.set_focus(text_area)
                except Exception:
                    pass

            # For large conversations, defer the load to show loading message first
            if self.selected_session.message_count > 50:
                self.call_after_refresh(do_load)
            else:
                do_load()

        self.call_after_refresh(switch_and_load)

    def action_toggle_selection(self) -> None:
        """Toggle selection of the current session for multi-delete."""
        table = self.query_one("#session-table", DataTable)

        # Get the currently highlighted row (cursor position)
        if table.cursor_row is None or table.cursor_row < 0:
            self.notify("No session highlighted", severity="warning")
            return

        # Get the session ID from the row at cursor position
        try:
            row = table.ordered_rows[table.cursor_row]
            session_id = row.key.value
        except Exception as e:
            self.notify(f"Could not get session from cursor position: {e}", severity="error")
            return

        if session_id in self.selected_for_delete:
            self.selected_for_delete.remove(session_id)
        else:
            self.selected_for_delete.add(session_id)

        # Refresh table to show selection indicators, keeping cursor position
        search_input = self.query_one("#search-input", Input)
        current_row_index = table.cursor_coordinate.row
        self.populate_table(search_input.value)

        # Move cursor back to the same position
        try:
            table.move_cursor(row=current_row_index)
        except Exception:
            # If row not found (filtered out), just stay at current position
            pass

        count = len(self.selected_for_delete)
        if count > 0:
            self.notify(f"{count} session(s) selected for deletion", severity="information")
        else:
            self.notify("Selection cleared", severity="information")

    def action_view_session(self) -> None:
        """View the selected session in detail."""
        # Only handle if we're on the browser tab
        # The RowSelected event already handles the tab switch
        tabbed = self.query_one(TabbedContent)
        if tabbed.active != "browser":
            return

        table = self.query_one("#session-table", DataTable)

        # Get the currently highlighted row (cursor position)
        if table.cursor_row is None or table.cursor_row < 0:
            self.notify("No session highlighted", severity="warning")
            return

        # Get the session ID from the row at cursor position
        try:
            row = table.ordered_rows[table.cursor_row]
            session_id = row.key.value
        except Exception as e:
            self.notify(f"Could not get session: {e}", severity="error")
            return

        self.selected_session = next(
            (s for s in self.sessions if s.session_id == session_id),
            None
        )

        if not self.selected_session:
            self.notify("Session not found", severity="error")
            return

        # Switch to detail tab
        tabbed.active = "detail"

        # Load and display conversation
        self.load_conversation()

        # Also update analytics
        self.load_analytics()

    def load_conversation(self) -> None:
        """Load and display the conversation for the selected session."""
        if not self.selected_session:
            return

        text_area = self.query_one("#conversation-log", TextArea)
        tag_label = self.query_one("#conversation-tag", Label)

        # Update tag label
        if self.selected_session.custom_tag:
            tag_label.update(f"🏷️  {self.selected_session.custom_tag}")
            tag_label.display = True
        else:
            tag_label.display = False

        # Helper function to format timestamp from UTC to local time
        def format_timestamp(ts_str: Optional[str]) -> str:
            if not ts_str:
                return ""
            try:
                # Parse ISO format timestamp (UTC)
                from datetime import timezone
                if ts_str.endswith('Z'):
                    ts_str = ts_str[:-1] + '+00:00'
                utc_dt = datetime.fromisoformat(ts_str)
                # Convert to local time
                local_dt = utc_dt.replace(tzinfo=timezone.utc).astimezone()
                return local_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return ts_str

        # Build the conversation as plain text
        lines = []
        message_positions = []  # Track line numbers where messages start

        lines.append(f"Session: {self.selected_session.session_id}")
        lines.append(f"Workspace: {self.selected_session.workspace}")
        lines.append(f"Messages: {self.selected_session.message_count}")
        if self.selected_session.cwd:
            lines.append(f"Directory: {self.selected_session.cwd}")
        lines.append("")
        lines.append("=" * 80)
        lines.append("")

        # Load messages
        try:
            messages = SessionLoader.load_session_messages(
                self.selected_session.file_path
            )

            # Track git branch to show when it changes
            current_git_branch = None

            for i, msg in enumerate(messages, 1):
                # Show git branch if it changed
                if msg.git_branch and msg.git_branch != current_git_branch:
                    current_git_branch = msg.git_branch
                    lines.append(f"[Git Branch: {current_git_branch}]")
                    lines.append("")

                # Format timestamp
                timestamp_str = format_timestamp(msg.timestamp)
                time_suffix = f" - {timestamp_str}" if timestamp_str else ""

                if msg.role == 'user':
                    lines.append("")
                    lines.append("=" * 80)
                    lines.append(f"USER (Message {i}){time_suffix}:")
                    # Record the position of the USER line we just added
                    message_positions.append(len(lines) - 1)
                    lines.append("=" * 80)
                    lines.append(msg.content)

                elif msg.role == 'assistant':
                    lines.append("")
                    lines.append("=" * 80)
                    lines.append(f"ASSISTANT (Message {i}){time_suffix}:")
                    # Record the position of the ASSISTANT line we just added
                    message_positions.append(len(lines) - 1)

                    # Show metadata
                    if msg.metadata:
                        meta_parts = []
                        if msg.metadata.get('model'):
                            meta_parts.append(f"Model: {msg.metadata['model']}")
                        if msg.metadata.get('stop_reason'):
                            meta_parts.append(f"Stop: {msg.metadata['stop_reason']}")
                        if msg.metadata.get('usage'):
                            usage = msg.metadata['usage']
                            tokens = f"Tokens: in={usage.get('input_tokens', 0)}, out={usage.get('output_tokens', 0)}"
                            if usage.get('cache_read_input_tokens'):
                                tokens += f", cache_read={usage['cache_read_input_tokens']}"
                            meta_parts.append(tokens)

                        if meta_parts:
                            lines.append(f"{' | '.join(meta_parts)}")

                    lines.append(f"{'=' * 80}")
                    lines.append(msg.content)

                lines.append("")

            # Set the text content (this is selectable and copyable)
            text_area.text = '\n'.join(lines)

            # Set message positions for navigation
            session_detail = self.query_one(SessionDetail)
            session_detail.set_message_positions(message_positions)

            # Set focus to the text area so navigation keys work immediately
            self.set_focus(text_area)

            # Show completion notification for large conversations
            if self.selected_session.message_count > 50:
                self.notify(f"Loaded {len(messages)} messages", severity="information")

        except Exception as e:
            text_area.text = f"Error loading conversation: {e}"

    def load_analytics(self) -> None:
        """Load and display analytics for the selected session."""
        if not self.selected_session:
            return

        container = self.query_one("#analytics-content", Static)

        s = self.selected_session

        # Build analytics text
        lines = []
        lines.append(f"[bold cyan]Session Analytics: {s.session_id}[/bold cyan]\n")

        lines.append("[bold]Overview[/bold]")
        lines.append(f"  Workspace: {s.workspace}")
        lines.append(f"  Messages: {s.message_count}")
        lines.append(f"  File Size: {s.size_bytes / 1024 / 1024:.2f} MB")
        if s.model:
            lines.append(f"  Model: {s.model}")
        if s.cwd:
            lines.append(f"  Working Dir: {s.cwd}")
        lines.append("")

        lines.append("[bold]Token Usage[/bold]")
        lines.append(f"  Input Tokens: {s.total_input_tokens:,}")
        lines.append(f"  Output Tokens: {s.total_output_tokens:,}")
        lines.append(f"  Total: {s.total_input_tokens + s.total_output_tokens:,}")
        if s.total_cache_read_tokens:
            lines.append(f"  Cache Read: {s.total_cache_read_tokens:,}")
        if s.total_cache_create_tokens:
            lines.append(f"  Cache Create: {s.total_cache_create_tokens:,}")
        lines.append("")

        if s.tool_usage:
            lines.append("[bold]Tool Usage[/bold]")
            for tool, count in sorted(s.tool_usage.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {tool}: {count}")
            lines.append("")

        if s.first_message_time and s.last_message_time:
            duration = s.last_message_time - s.first_message_time
            lines.append("[bold]Timeline[/bold]")
            lines.append(f"  First Message: {s.first_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"  Last Message: {s.last_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"  Duration: {duration}")

        container.update("\n".join(lines))

    def action_resume_new_terminal(self) -> None:
        """Resume session in a new Windows Terminal window."""
        # First determine which session to resume
        # Check if we're viewing a session in detail view, otherwise use table cursor
        tabbed = self.query_one(TabbedContent)

        if tabbed.active == "detail" and self.selected_session:
            # Resume the currently viewed session
            session = self.selected_session
        else:
            # Resume from table cursor position
            table = self.query_one("#session-table", DataTable)

            # Get the currently highlighted row (cursor position)
            if table.cursor_row is None or table.cursor_row < 0:
                self.notify("No session highlighted", severity="warning")
                return

            # Get the session ID from the row at cursor position
            try:
                row = table.ordered_rows[table.cursor_row]
                session_id = row.key.value
            except Exception as e:
                self.notify(f"Could not get session: {e}", severity="error")
                return

            session = next(
                (s for s in self.sessions if s.session_id == session_id),
                None
            )

            if not session:
                self.notify("Session not found", severity="error")
                return

        try:
            # For Windows Terminal
            if sys.platform == "win32":
                # Find the full path to claude to avoid PATH issues in new terminal
                claude_path = shutil.which('claude')
                if not claude_path:
                    self.notify("Could not find claude executable in PATH", severity="error")
                    return

                # Use the session's original working directory if available
                start_dir = session.cwd if session.cwd else str(Path.home())

                # Use full path and quote it in case of spaces
                # Start in the original working directory so Claude can find the session
                cmd = f'wt.exe -d "{start_dir}" "{claude_path}" --resume {session.session_id}'
                subprocess.Popen(cmd, shell=True)
                self.notify(f"Launched session {session.session_id[:8]}... in new terminal", severity="information")
            else:
                # For other platforms, try common terminal emulators
                self.notify("New terminal launch not implemented for this platform", severity="warning")
        except Exception as e:
            self.notify(f"Error launching terminal: {e}", severity="error")

    def action_delete_session(self) -> None:
        """Delete selected session(s) after confirmation."""
        # Determine what to delete: multi-selected or current session
        sessions_to_delete = []

        if self.selected_for_delete:
            # Delete all multi-selected sessions
            sessions_to_delete = [
                s for s in self.sessions
                if s.session_id in self.selected_for_delete
            ]
        else:
            # Delete only the currently highlighted session
            table = self.query_one("#session-table", DataTable)

            if table.cursor_row is None or table.cursor_row < 0:
                self.notify("No session highlighted", severity="warning")
                return

            # Get the session ID from the row at cursor position
            try:
                row = table.ordered_rows[table.cursor_row]
                session_id = row.key.value
            except Exception as e:
                self.notify(f"Could not get session: {e}", severity="error")
                return

            current_session = next(
                (s for s in self.sessions if s.session_id == session_id),
                None
            )

            if not current_session:
                self.notify("Session not found", severity="error")
                return

            sessions_to_delete = [current_session]

        # Build confirmation message
        count = len(sessions_to_delete)
        if count == 1:
            session = sessions_to_delete[0]
            description = session.description or session.session_id[:12]
            message_count = session.message_count
            if message_count == 0:
                confirm_msg = f"Delete empty session '{description}'?"
            else:
                confirm_msg = f"Delete session '{description}' ({message_count} messages)?\n\nThis cannot be undone!"
        else:
            total_messages = sum(s.message_count for s in sessions_to_delete)
            confirm_msg = f"Delete {count} sessions ({total_messages} total messages)?\n\nThis cannot be undone!"

        # Callback for confirmation
        def confirm_delete(confirmed: bool) -> None:
            if confirmed:
                deleted_count = 0
                errors = []

                try:
                    for session in sessions_to_delete:
                        try:
                            session.file_path.unlink()
                            deleted_count += 1
                        except Exception as e:
                            errors.append(f"{session.session_id[:8]}: {str(e)}")

                    # Report results
                    if deleted_count > 0:
                        self.notify(f"Deleted {deleted_count} session(s)", severity="information")

                    if errors:
                        error_msg = "\n".join(errors[:3])  # Show first 3 errors
                        if len(errors) > 3:
                            error_msg += f"\n...and {len(errors) - 3} more"
                        self.notify(f"Errors:\n{error_msg}", severity="error")

                    # Reload sessions
                    self.load_sessions()
                    search_input = self.query_one("#search-input", Input)
                    self.populate_table(search_input.value)

                    # Clear selections
                    self.selected_session = None
                    self.selected_for_delete.clear()

                    # Go back to list
                    tabbed = self.query_one(TabbedContent)
                    tabbed.active = "browser"

                except Exception as e:
                    self.notify(f"Error deleting sessions: {e}", severity="error")

        # Show confirmation dialog
        from textual.screen import ModalScreen
        from textual.widgets import Button, Label

        class ConfirmDeleteScreen(ModalScreen):
            """Confirmation dialog for deleting session(s)."""

            def compose(self) -> ComposeResult:
                with Container(id="confirm-dialog"):
                    yield Label(confirm_msg)
                    with Horizontal():
                        yield Button("Delete", variant="error", id="confirm-yes")
                        yield Button("Cancel", variant="primary", id="confirm-no")

            def on_button_pressed(self, event: Button.Pressed) -> None:
                if event.button.id == "confirm-yes":
                    self.dismiss(True)
                else:
                    self.dismiss(False)

        self.push_screen(ConfirmDeleteScreen(), confirm_delete)

    def check_action_back_to_list(self) -> bool:
        """Check if back to list action should be enabled (only when not on browser tab)."""
        try:
            tabbed = self.query_one(TabbedContent)
            return tabbed.active != "browser"
        except:
            return False

    def action_back_to_list(self) -> None:
        """Go back to the session list."""
        tabbed = self.query_one(TabbedContent)
        # Only switch if not already on browser tab
        if tabbed.active == "browser":
            return
        tabbed.active = "browser"
        # Set focus back to session table for immediate navigation
        self.set_focus(self.query_one("#session-table"))

    def check_action_refresh(self) -> bool:
        """Check if refresh action should be enabled (only on browser tab)."""
        try:
            tabbed = self.query_one(TabbedContent)
            return tabbed.active == "browser"
        except:
            return False

    def action_refresh(self) -> None:
        """Refresh the session list."""
        self.load_sessions()
        search_input = self.query_one("#search-input", Input)
        self.populate_table(search_input.value)
        self.notify("Sessions refreshed", severity="information")

    def action_edit_tag(self) -> None:
        """Edit the custom tag for the highlighted session."""
        table = self.query_one("#session-table", DataTable)

        # Get the currently highlighted row
        if table.cursor_row is None or table.cursor_row < 0:
            self.notify("No session highlighted", severity="warning")
            return

        # Get the session ID from the row at cursor position
        try:
            row = table.ordered_rows[table.cursor_row]
            session_id = row.key.value
        except Exception as e:
            self.notify(f"Could not get session: {e}", severity="error")
            return

        session = next(
            (s for s in self.sessions if s.session_id == session_id),
            None
        )

        if not session:
            self.notify("Session not found", severity="error")
            return

        # Show tag input screen
        from textual.screen import ModalScreen
        from textual.widgets import Label

        class TagInputScreen(ModalScreen):
            """Modal screen for editing session tag."""

            def compose(self) -> ComposeResult:
                with Container(id="tag-dialog"):
                    yield Label(f"Edit tag for: {session.description[:50] if session.description else session.session_id[:12]}...")
                    yield Input(placeholder="Enter custom tag (leave empty to remove)", id="tag-input", value=session.custom_tag or "")
                    with Horizontal():
                        yield Button("Save", variant="primary", id="save-tag")
                        yield Button("Cancel", variant="default", id="cancel-tag")

            def on_mount(self) -> None:
                """Focus the input when mounted."""
                self.query_one("#tag-input", Input).focus()

            def on_button_pressed(self, event: Button.Pressed) -> None:
                if event.button.id == "save-tag":
                    tag_input = self.query_one("#tag-input", Input)
                    self.dismiss(tag_input.value.strip() or None)
                else:
                    self.dismiss(False)

        def handle_tag_result(result):
            """Handle the tag input result."""
            if result is False:
                # User cancelled
                return

            # Save the tag
            if SessionLoader.save_custom_tag(session.file_path, result):
                # Update the session object
                session.custom_tag = result

                # Update the selected session if we're viewing it
                if self.selected_session and self.selected_session.session_id == session.session_id:
                    self.selected_session.custom_tag = result
                    # Update the tag label in conversation view if visible
                    try:
                        tag_label = self.query_one("#conversation-tag", Label)
                        if result:
                            tag_label.update(f"🏷️  {result}")
                            tag_label.display = True
                        else:
                            tag_label.display = False
                    except Exception:
                        pass

                # Refresh the table
                search_input = self.query_one("#search-input", Input)
                current_row_index = table.cursor_coordinate.row
                self.populate_table(search_input.value)
                # Restore cursor position
                try:
                    table.move_cursor(row=current_row_index)
                except Exception:
                    pass
                if result:
                    self.notify(f"Tag saved: {result}", severity="information")
                else:
                    self.notify("Tag removed", severity="information")
            else:
                self.notify("Failed to save tag", severity="error")

        self.push_screen(TagInputScreen(), handle_tag_result)

    def action_help(self) -> None:
        """Show help information."""
        help_text = """
# Claude Session Viewer - Keyboard Shortcuts

## Navigation
- **↑/↓** - Navigate session list
- **Enter** - View selected session details
- **Escape** - Back to session list
- **Tab** - Switch between tabs

## Session Actions
- **Space** - Toggle selection for multi-delete (shows ✓ indicator)
- **D** - Delete selected session(s) (with confirmation)
- **Ctrl+N** - Resume session in new Windows Terminal window

## General
- **R** - Refresh session list
- **?** - Show this help
- **Q** - Quit application

## Multi-Select Delete Workflow
1. Press **Space** on sessions you want to delete (✓ appears)
2. Continue selecting multiple sessions
3. Press **D** to delete all selected sessions at once
4. Or just press **D** on a single session without Space

## Session List Search
Type in the search box to filter sessions by description, ID, workspace, or directory.

**Deep Search:** Prefix your search with `//` to search the full conversation content.
- Example: `//incremental` searches all message text for "incremental"
- Deep search is slower but finds text anywhere in conversations

## Conversation View Search
When viewing a conversation:
- **/** - Open search box
- **Enter** - Search and jump to first match
- **n** - Jump to next match
- **N** (Shift+n) - Jump to previous match
- **Escape** - Cancel search

## Notes
- Empty sessions (0 messages) are automatically filtered out
- Sessions are sorted by most recent first
- Description shows the first user message from each conversation
- Selected sessions show a ✓ indicator

---
Press Escape to close this help.
        """
        self.notify("Help: See footer for key bindings", title="Keyboard Shortcuts")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Interactive TUI for viewing and resuming Claude Code sessions.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python claude-session-tui.py                     # Show all sessions from all workspaces
  python claude-session-tui.py --workspace NAME    # Show sessions from specific workspace
  python claude-session-tui.py --path /custom/dir  # Scan custom directory for sessions
  python claude-session-tui.py --path /dir1 --path /dir2  # Scan multiple directories

Keyboard Shortcuts:
  Enter       - View session details
  Ctrl+N      - Resume session in new terminal
  Space       - Toggle selection for multi-delete
  D           - Delete selected session(s)
  R           - Refresh session list
  Q           - Quit
  ?           - Help
        """
    )

    parser.add_argument('--workspace', '-w', help='Filter to specific workspace')
    parser.add_argument('--path', '-p', action='append', type=Path,
                        help='Custom path(s) to scan for .jsonl session files (can be specified multiple times)')
    args = parser.parse_args()

    # Run the app
    app = SessionViewerApp(workspace=args.workspace, custom_paths=args.path)
    app.run()


if __name__ == '__main__':
    main()
