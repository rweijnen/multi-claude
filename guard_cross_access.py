#!/usr/bin/env python
"""PreToolUse hook: cross-account access guard.

Reads CLAUDE_ACCOUNT_FORBIDDEN_DIRS (comma-separated) from the
environment and denies Bash, Read, Write, Edit, Glob, and Grep calls
that reference any forbidden path. This prevents one account from
touching other accounts' configuration directories.

Falls back to singular CLAUDE_ACCOUNT_FORBIDDEN_DIR for backward
compatibility.

Checks forward-slash, backslash, and MSYS2 (/c/...) path formats.
"""

import json
import os
import re
import sys


def _normalize(path):
    """Lowercase and forward-slash normalize a path string."""
    return path.replace("\\", "/").lower().rstrip("/")


def _msys2_form(win_path):
    """Convert c:/users/... to /c/users/... (MSYS2 mount format)."""
    m = re.match(r"^([a-z]):/(.*)$", win_path)
    if m:
        return "/" + m.group(1) + "/" + m.group(2)
    return None


def _contains_any_forbidden(text, forbidden_list):
    """Check if text contains any forbidden path in any format."""
    lowered = text.lower()
    fwd = lowered.replace("\\", "/")
    for norm, msys in forbidden_list:
        if norm in fwd:
            return norm
        if norm.replace("/", "\\") in lowered:
            return norm
        if msys and msys in lowered:
            return norm
    return None


def _get_forbidden_dirs():
    """Read forbidden dirs from environment, return list of raw paths."""
    # Prefer plural (comma-separated)
    dirs_str = os.environ.get("CLAUDE_ACCOUNT_FORBIDDEN_DIRS", "")
    if dirs_str:
        return [d.strip() for d in dirs_str.split(",") if d.strip()]

    # Fall back to singular
    single = os.environ.get("CLAUDE_ACCOUNT_FORBIDDEN_DIR", "")
    if single:
        return [single.strip()]

    return []


def main():
    raw_dirs = _get_forbidden_dirs()
    if not raw_dirs:
        sys.exit(0)

    # Pre-compute normalized + MSYS2 forms
    forbidden_list = []
    for d in raw_dirs:
        norm = _normalize(d)
        msys = _msys2_form(norm)
        forbidden_list.append((norm, msys))

    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    matched = None

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if command:
            matched = _contains_any_forbidden(command, forbidden_list)

    elif tool_name in ("Read", "Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            matched = _contains_any_forbidden(file_path, forbidden_list)

    elif tool_name in ("Glob", "Grep"):
        path = tool_input.get("path", "")
        if path:
            matched = _contains_any_forbidden(path, forbidden_list)

    if matched:
        account = os.environ.get("CLAUDE_ACCOUNT", "unknown")
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")
        # Reconstruct the original path for display
        display_dir = matched.replace("/", "\\") if "\\" in raw_dirs[0] else matched
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "reason": (
                    f"Cross-account access denied. "
                    f"You are running as the '{account}' account "
                    f"(config: {config_dir}). "
                    f"Access to {display_dir} is forbidden. "
                    f"That path belongs to a different account."
                ),
            }
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
