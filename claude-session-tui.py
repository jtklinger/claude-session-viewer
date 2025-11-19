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
    Input, Button, TabbedContent, TabPane, Markdown, RichLog
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
    description: Optional[str] = None  # First user message or description

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


# ============================================================================
# SESSION PARSING AND LOADING
# ============================================================================

class SessionLoader:
    """Loads and parses Claude session files."""

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
    def list_sessions(workspace: Optional[str] = None) -> List[SessionMetadata]:
        """List all sessions, optionally filtered by workspace."""
        claude_dir = SessionLoader.get_claude_dir()
        projects_base = claude_dir / "projects"

        if not projects_base.exists():
            return []

        sessions = []

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
        first_user_message = None

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

                            # Extract first user message for description
                            if msg_type == 'user' and not first_user_message:
                                message = data.get('message', {})
                                content = message.get('content', '')
                                if isinstance(content, str):
                                    first_user_message = content.strip()
                                elif isinstance(content, list):
                                    # Extract text from content blocks
                                    for block in content:
                                        if isinstance(block, dict) and block.get('type') == 'text':
                                            first_user_message = block.get('text', '').strip()
                                            break
                                        elif isinstance(block, str):
                                            first_user_message = block.strip()
                                            break

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

        # Create description from first user message or cwd
        description = None
        if first_user_message:
            # Truncate to ~100 chars, break on word boundary
            description = first_user_message[:100]
            if len(first_user_message) > 100:
                description = description.rsplit(' ', 1)[0] + '...'
            # Clean up newlines
            description = description.replace('\n', ' ').replace('\r', '')
        elif cwd:
            # Use working directory if no first message
            description = f"[{cwd}]"
        else:
            description = "[Empty session]"

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
            description=description
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

                        messages.append(Message(
                            role='user',
                            content=content,
                            timestamp=timestamp,
                            line_num=line_num
                        ))

                    elif msg_type == 'assistant':
                        message = data.get('message', {})
                        content = SessionLoader._format_content(message.get('content', ''))
                        timestamp = data.get('timestamp')

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
                            line_num=line_num
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


# ============================================================================
# TEXTUAL WIDGETS
# ============================================================================

class SessionBrowser(Container):
    """Widget showing the list of sessions."""

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Input(placeholder="Search sessions...", id="search-input")
        yield DataTable(id="session-table")

    def on_mount(self) -> None:
        """Set up the table when mounted."""
        table = self.query_one("#session-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        # Add columns
        table.add_column("Date", width=20)
        table.add_column("Description", width=60)
        table.add_column("Workspace", width=25)
        table.add_column("Messages", width=10)
        table.add_column("Tokens", width=12)
        table.add_column("Size", width=10)


class SessionDetail(VerticalScroll):
    """Widget showing detailed session conversation."""

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield RichLog(id="conversation-log", wrap=True, highlight=True)


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

    #search-input {
        dock: top;
        margin: 1;
    }

    #session-table {
        height: 100%;
    }

    #conversation-log {
        height: 100%;
        border: solid $accent;
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("?", "help", "Help"),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_selection", "Toggle Selection"),
        Binding("d", "delete_session", "Delete Session(s)"),
        # Enter is handled by on_data_table_row_selected event, not app-level binding
        Binding("ctrl+n", "resume_new_terminal", "Resume Session"),
        Binding("escape", "back_to_list", "Back to List"),
    ]

    TITLE = "Claude Session Viewer"

    def __init__(self, workspace: Optional[str] = None):
        """Initialize the app."""
        super().__init__()
        self.workspace_filter = workspace
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
            self.sessions = SessionLoader.list_sessions(self.workspace_filter)
        except Exception as e:
            self.notify(f"Error loading sessions: {e}", severity="error")
            self.sessions = []

    def populate_table(self, filter_text: str = "") -> None:
        """Populate the sessions table."""
        table = self.query_one("#session-table", DataTable)
        table.clear()

        # Filter out empty sessions and apply search filter
        filtered = [s for s in self.sessions if s.message_count > 0]

        if filter_text:
            filter_lower = filter_text.lower()
            filtered = [
                s for s in filtered
                if filter_lower in s.session_id.lower()
                or filter_lower in s.workspace.lower()
                or (s.description and filter_lower in s.description.lower())
                or (s.cwd and filter_lower in s.cwd.lower())
            ]

        # Add rows
        for session in filtered:
            date_str = session.modified.strftime("%Y-%m-%d %H:%M:%S")
            tokens_str = f"{session.total_input_tokens + session.total_output_tokens:,}"
            size_str = f"{session.size_bytes / 1024 / 1024:.1f} MB"

            # Add selection indicator
            description = session.description or "[No description]"
            if session.session_id in self.selected_for_delete:
                description = f"[✓] {description}"

            table.add_row(
                date_str,
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

            # Show loading message in the log before starting the actual load
            if self.selected_session.message_count > 50:
                log = self.query_one("#conversation-log", RichLog)
                log.clear()
                log.write("[bold yellow]Loading conversation...[/bold yellow]")
                log.write(f"[dim]{self.selected_session.message_count} messages[/dim]")

            # Defer the actual conversation loading to let the loading message display
            def do_load():
                self.load_conversation()
                self.load_analytics()

                # Set focus to the conversation log
                try:
                    log = self.query_one("#conversation-log", RichLog)
                    self.set_focus(log)
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

        log = self.query_one("#conversation-log", RichLog)
        log.clear()
        log.write(f"[bold cyan]Session: {self.selected_session.session_id}[/bold cyan]")
        log.write(f"[dim]Workspace: {self.selected_session.workspace}[/dim]")
        log.write(f"[dim]Messages: {self.selected_session.message_count}[/dim]")
        if self.selected_session.cwd:
            log.write(f"[dim]Directory: {self.selected_session.cwd}[/dim]")
        log.write("")
        log.write("[bold]" + "=" * 60 + "[/bold]")
        log.write("")

        # Load messages
        try:
            messages = SessionLoader.load_session_messages(
                self.selected_session.file_path
            )

            for i, msg in enumerate(messages, 1):
                if msg.role == 'user':
                    log.write(f"\n[bold green]User (Message {i}):[/bold green]")
                    log.write(msg.content)

                elif msg.role == 'assistant':
                    log.write(f"\n[bold blue]Assistant (Message {i}):[/bold blue]")

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
                            log.write(f"[dim italic]{' | '.join(meta_parts)}[/dim italic]")

                    log.write(msg.content)

                log.write("")

            # Show completion notification for large conversations
            if self.selected_session.message_count > 50:
                self.notify(f"Loaded {len(messages)} messages", severity="information")

        except Exception as e:
            log.write(f"[bold red]Error loading conversation: {e}[/bold red]")

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

    def action_refresh(self) -> None:
        """Refresh the session list."""
        self.load_sessions()
        search_input = self.query_one("#search-input", Input)
        self.populate_table(search_input.value)
        self.notify("Sessions refreshed", severity="information")

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

## Search
Type in the search box to filter sessions by description, ID, workspace, or directory.

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
    args = parser.parse_args()

    # Run the app
    app = SessionViewerApp(workspace=args.workspace)
    app.run()


if __name__ == '__main__':
    main()
