#!/usr/bin/env python3
"""
Parse Claude Code session JSONL files and display conversations.
Usage:
    python view-claude-session.py                    # Parse most recent session
    python view-claude-session.py SESSION_ID         # Parse specific session by ID
    python view-claude-session.py /path/to/file.jsonl # Parse specific file
    python view-claude-session.py --list             # List recent sessions
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
import argparse

def get_claude_dir():
    """Get the Claude Code directory."""
    home = Path.home()
    claude_dir = home / ".claude"
    if not claude_dir.exists():
        print(f"Error: Claude directory not found at {claude_dir}", file=sys.stderr)
        sys.exit(1)
    return claude_dir

def get_projects_dir(workspace=None):
    """Get the projects directory for a workspace."""
    claude_dir = get_claude_dir()

    if workspace:
        # Use specified workspace
        projects_dir = claude_dir / "projects" / workspace
    else:
        # Find the first projects subdirectory
        projects_base = claude_dir / "projects"
        if not projects_base.exists():
            print(f"Error: Projects directory not found at {projects_base}", file=sys.stderr)
            sys.exit(1)

        subdirs = [d for d in projects_base.iterdir() if d.is_dir()]
        if not subdirs:
            print(f"Error: No workspace directories found in {projects_base}", file=sys.stderr)
            sys.exit(1)

        # Use the first one (typically there's only one)
        projects_dir = subdirs[0]

    return projects_dir

def list_sessions(limit=10):
    """List recent sessions with metadata."""
    projects_dir = get_projects_dir()

    # Get all session files sorted by modification time
    session_files = sorted(
        projects_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    print(f"Recent sessions in {projects_dir.name}:")
    print("-" * 80)

    for i, session_file in enumerate(session_files[:limit]):
        session_id = session_file.stem
        mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
        size = session_file.stat().st_size

        # Count messages
        message_count = 0
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get('type') in ['user', 'assistant']:
                            message_count += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            message_count = "?"

        print(f"{i+1}. Session: {session_id}")
        print(f"   Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Size: {size / 1024 / 1024:.2f} MB")
        print(f"   Messages: {message_count}")
        print()

def find_session_file(session_id_or_path):
    """Find a session file by ID or path."""
    # Check if it's a direct path
    if os.path.exists(session_id_or_path):
        return Path(session_id_or_path)

    # Try to find by session ID
    projects_dir = get_projects_dir()
    session_file = projects_dir / f"{session_id_or_path}.jsonl"

    if session_file.exists():
        return session_file

    print(f"Error: Session file not found: {session_id_or_path}", file=sys.stderr)
    print(f"Tried: {session_file}", file=sys.stderr)
    sys.exit(1)

def get_most_recent_session():
    """Get the most recently modified session file."""
    projects_dir = get_projects_dir()

    session_files = list(projects_dir.glob("*.jsonl"))
    if not session_files:
        print(f"Error: No session files found in {projects_dir}", file=sys.stderr)
        sys.exit(1)

    most_recent = max(session_files, key=lambda f: f.stat().st_mtime)
    return most_recent

def format_message_content(content):
    """Format message content for display."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Handle content blocks (text and tool use)
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    parts.append(block.get('text', ''))
                elif block.get('type') == 'tool_use':
                    tool_name = block.get('name', 'unknown')
                    tool_input = json.dumps(block.get('input', {}), indent=2)
                    parts.append(f"\n**[Tool Use: {tool_name}]**\n```json\n{tool_input}\n```\n")
            elif isinstance(block, str):
                parts.append(block)
        return '\n'.join(parts)
    else:
        return str(content)

def format_tool_result(tool_use_id, content, is_error=False):
    """Format tool result for display."""
    status = "ERROR" if is_error else "SUCCESS"
    result_text = content if isinstance(content, str) else json.dumps(content, indent=2)

    # Truncate very long results
    max_length = 2000
    if len(result_text) > max_length:
        result_text = result_text[:max_length] + f"\n... (truncated, {len(result_text)} total chars)"

    return f"\n**[Tool Result: {status}]**\n```\n{result_text}\n```\n"

def parse_session(session_file, output_file=None):
    """Parse a session JSONL file and convert to markdown."""
    print(f"Parsing session: {session_file.name}")
    print(f"File size: {session_file.stat().st_size / 1024 / 1024:.2f} MB")

    messages = []

    with open(session_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line)

                # Extract message data
                msg_type = data.get('type')

                if msg_type == 'user':
                    message = data.get('message', {})
                    content = message.get('content', '')
                    timestamp = data.get('timestamp')

                    messages.append({
                        'role': 'user',
                        'content': format_message_content(content),
                        'timestamp': timestamp,
                        'line': line_num
                    })

                elif msg_type == 'assistant':
                    message = data.get('message', {})
                    content = message.get('content', '')
                    timestamp = data.get('timestamp')

                    messages.append({
                        'role': 'assistant',
                        'content': format_message_content(content),
                        'timestamp': timestamp,
                        'line': line_num
                    })

                elif msg_type == 'tool-result':
                    # Tool results
                    content = data.get('content', '')
                    tool_use_id = data.get('toolUseId', 'unknown')
                    is_error = data.get('isError', False)

                    messages.append({
                        'role': 'tool-result',
                        'content': format_tool_result(tool_use_id, content, is_error),
                        'timestamp': data.get('timestamp'),
                        'line': line_num
                    })

            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse line {line_num}: {e}", file=sys.stderr)
                continue
            except Exception as e:
                print(f"Warning: Error processing line {line_num}: {e}", file=sys.stderr)
                continue

    # Generate markdown
    markdown_lines = []
    markdown_lines.append(f"# Claude Code Session: {session_file.stem}\n")
    markdown_lines.append(f"**Session File:** `{session_file}`\n")
    markdown_lines.append(f"**Total Messages:** {len([m for m in messages if m['role'] in ['user', 'assistant']])}\n")
    markdown_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    markdown_lines.append("\n---\n")

    for i, msg in enumerate(messages, 1):
        role = msg['role']
        content = msg['content']

        if role == 'user':
            markdown_lines.append(f"\n## Message {i}: User\n")
            markdown_lines.append(f"{content}\n")

        elif role == 'assistant':
            markdown_lines.append(f"\n## Message {i}: Assistant\n")
            markdown_lines.append(f"{content}\n")

        elif role == 'tool-result':
            markdown_lines.append(f"{content}\n")

    markdown_content = '\n'.join(markdown_lines)

    # Write to output file
    if output_file:
        output_path = Path(output_file)
    else:
        output_path = Path(f"claude-session-{session_file.stem}.md")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown_content)

    print(f"\n[OK] Conversation exported to: {output_path}")
    print(f"  Total messages: {len([m for m in messages if m['role'] in ['user', 'assistant']])}")
    print(f"  Output size: {output_path.stat().st_size / 1024:.2f} KB")

    return output_path

def main():
    parser = argparse.ArgumentParser(
        description='Parse Claude Code session files and display conversations.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python view-claude-session.py                              # Parse most recent session
  python view-claude-session.py a643dfaa-2606-4d83-94e9      # Parse by session ID
  python view-claude-session.py ~/.claude/projects/.../session.jsonl  # Parse specific file
  python view-claude-session.py --list                       # List recent sessions
  python view-claude-session.py --output my-session.md       # Custom output filename
        """
    )

    parser.add_argument('session', nargs='?', help='Session ID or file path (defaults to most recent)')
    parser.add_argument('--list', '-l', action='store_true', help='List recent sessions')
    parser.add_argument('--output', '-o', help='Output markdown file path')
    parser.add_argument('--limit', type=int, default=10, help='Number of sessions to list (default: 10)')

    args = parser.parse_args()

    # List sessions
    if args.list:
        list_sessions(limit=args.limit)
        return

    # Find session file
    if args.session:
        session_file = find_session_file(args.session)
    else:
        session_file = get_most_recent_session()

    # Parse and export
    output_path = parse_session(session_file, args.output)

    print(f"\nOpen in your IDE:")
    print(f"  code {output_path}")
    print(f"  or just: {output_path}")

if __name__ == '__main__':
    main()
