#!/usr/bin/env python
"""Interactive setup for multi-account Claude Code.

Walks the user through configuring multiple Claude accounts:
1. Asks for account names, labels, colors, config dirs
2. Writes ~/.claude-launcher.json
3. Creates config dirs for non-default accounts
4. Copies hooks from the default account (if they exist)
5. Writes settings.json with guard hook for each non-default account
6. Copies wrappers to ~/bin/
7. Writes CLAUDE.md isolation section for each account
8. Copies launcher.py to ~/.claude/
9. Checks PATH and warns if ~/bin is not ahead of ~/.local/bin
"""

import json
import os
import platform
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HOME = Path.home()
CONFIG_FILE = HOME / ".claude-launcher.json"
DEFAULT_COLORS = ["#cc3333", "#2ecc71", "#3498db", "#e67e22", "#9b59b6",
                  "#1abc9c", "#e74c3c", "#f39c12", "#2980b9"]


def ask(prompt, default=None):
    """Prompt user for input with an optional default."""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    val = input(prompt).strip()
    return val if val else default


def ask_yn(prompt, default=True):
    """Ask a yes/no question."""
    hint = "Y/n" if default else "y/N"
    val = input(f"{prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def find_claude_exe():
    """Try to locate the claude binary."""
    if platform.system() == "Windows":
        candidates = [
            HOME / ".local" / "bin" / "claude.exe",
            HOME / "AppData" / "Local" / "Programs" / "claude" / "claude.exe",
        ]
    else:
        candidates = [
            HOME / ".local" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[0])


def setup_accounts():
    """Interactively configure accounts."""
    accounts = []
    print("\n--- Account Setup ---")
    print("The first account is the default (uses ~/.claude config dir).")
    print("Press Enter with empty ID to finish adding accounts.\n")

    i = 0
    while True:
        if i == 0:
            print(f"Account #{i + 1} (default account):")
        else:
            print(f"\nAccount #{i + 1} (additional account):")

        acct_id = ask("  Account ID (e.g. personal, business)",
                      default=None if i > 0 else "personal")
        if not acct_id:
            if i < 2:
                print("  You need at least 2 accounts for multi-account mode.")
                continue
            break

        acct_id = acct_id.lower().replace(" ", "-")
        label = ask("  Display label", default=acct_id.title())
        color = ask("  Hex color (#RRGGBB)",
                     default=DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
        hotkey = ask("  Hotkey letter", default=acct_id[0])

        if i == 0:
            config_dir = None
            print(f"  Config dir: ~/.claude (default)")
        else:
            default_dir = str(HOME / f".claude-{acct_id}")
            config_dir = ask("  Config directory", default=default_dir)

        accounts.append({
            "id": acct_id,
            "label": label,
            "color": color,
            "config_dir": config_dir,
            "hotkey": hotkey[0] if hotkey else acct_id[0],
        })
        i += 1

    return accounts


def write_config(claude_exe, accounts):
    """Write ~/.claude-launcher.json."""
    cfg = {
        "claude_exe": claude_exe,
        "accounts": accounts,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"\nWrote {CONFIG_FILE}")


def create_config_dirs(accounts):
    """Create config directories for non-default accounts."""
    for acct in accounts:
        if acct["config_dir"]:
            d = Path(acct["config_dir"])
            if not d.exists():
                d.mkdir(parents=True)
                print(f"Created {d}")
            # Create hooks subdir
            hooks_dir = d / "hooks"
            if not hooks_dir.exists():
                hooks_dir.mkdir(parents=True)
                print(f"Created {hooks_dir}")


def copy_guard_hook(accounts):
    """Copy guard_cross_access.py to each account's hooks dir."""
    src = SCRIPT_DIR / "guard_cross_access.py"
    if not src.exists():
        print(f"Warning: {src} not found, skipping hook installation")
        return

    for acct in accounts:
        if acct["config_dir"]:
            dst = Path(acct["config_dir"]) / "hooks" / "guard_cross_access.py"
        else:
            dst = HOME / ".claude" / "hooks" / "guard_cross_access.py"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"Installed {dst}")


def write_settings_json(accounts):
    """Write or update settings.json with the guard hook for each account."""
    hook_entry = {
        "type": "command",
        "command": "python hooks/guard_cross_access.py",
    }

    for acct in accounts:
        if acct["config_dir"]:
            settings_path = Path(acct["config_dir"]) / "settings.json"
        else:
            settings_path = HOME / ".claude" / "settings.json"

        # Load existing settings or start fresh
        settings = {}
        if settings_path.exists():
            try:
                with open(settings_path, encoding="utf-8") as f:
                    settings = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # Ensure hooks.PreToolUse contains the guard
        hooks = settings.setdefault("hooks", {})
        pre_tool = hooks.setdefault("PreToolUse", [])

        # Check if guard hook already exists
        already = any("guard_cross_access" in (h.get("command", ""))
                       for h in pre_tool if isinstance(h, dict))
        if not already:
            pre_tool.append(hook_entry)

        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        print(f"Updated {settings_path}")


def write_claude_md_isolation(accounts):
    """Append account isolation section to each account's CLAUDE.md."""
    for idx, acct in enumerate(accounts):
        if acct["config_dir"]:
            claude_md = Path(acct["config_dir"]) / "CLAUDE.md"
        else:
            claude_md = HOME / ".claude" / "CLAUDE.md"

        # Build forbidden list
        other_dirs = []
        default_dir = str(HOME / ".claude")
        for i, other in enumerate(accounts):
            if i == idx:
                continue
            d = other["config_dir"] if other["config_dir"] else default_dir
            other_dirs.append(d)

        isolation_section = (
            f"\n## Account Isolation\n"
            f"This is the {acct['label'].upper()} account. "
            f"Config: {acct['config_dir'] or default_dir}\n"
        )
        for d in other_dirs:
            isolation_section += f"NEVER access files under {d}.\n"

        # Check if CLAUDE.md already has an isolation section
        existing = ""
        if claude_md.exists():
            existing = claude_md.read_text(encoding="utf-8")

        if "## Account Isolation" in existing:
            # Replace existing section
            import re
            existing = re.sub(
                r"\n## Account Isolation\n.*?(?=\n## |\Z)",
                isolation_section,
                existing,
                flags=re.DOTALL,
            )
            claude_md.write_text(existing, encoding="utf-8")
        else:
            with open(claude_md, "a", encoding="utf-8") as f:
                f.write(isolation_section)

        print(f"Updated {claude_md}")


def copy_launcher(accounts):
    """Copy launcher.py to the default account's config dir."""
    src = SCRIPT_DIR / "launcher.py"
    if not src.exists():
        print(f"Warning: {src} not found, skipping launcher install")
        return

    dst = HOME / ".claude" / "launcher.py"
    shutil.copy2(src, dst)
    print(f"Installed {dst}")


def copy_wrappers():
    """Copy wrapper scripts to ~/bin/."""
    bin_dir = HOME / "bin"
    bin_dir.mkdir(exist_ok=True)

    wrapper_dir = SCRIPT_DIR / "wrappers"
    if not wrapper_dir.exists():
        print(f"Warning: {wrapper_dir} not found, skipping wrapper install")
        return

    for name in ("claude", "claude.cmd"):
        src = wrapper_dir / name
        if src.exists():
            dst = bin_dir / name
            shutil.copy2(src, dst)
            if platform.system() != "Windows":
                os.chmod(dst, 0o755)
            print(f"Installed {dst}")


def check_path():
    """Warn if ~/bin is not in PATH or not ahead of ~/.local/bin."""
    bin_dir = str(HOME / "bin")
    local_bin = str(HOME / ".local" / "bin")
    path = os.environ.get("PATH", "")
    path_dirs = path.split(os.pathsep)

    # Normalize for comparison
    norm_dirs = [p.replace("\\", "/").lower().rstrip("/") for p in path_dirs]
    norm_bin = bin_dir.replace("\\", "/").lower().rstrip("/")
    norm_local = local_bin.replace("\\", "/").lower().rstrip("/")

    if norm_bin not in norm_dirs:
        print(f"\nWARNING: {bin_dir} is not in your PATH.")
        print("Add it to your PATH ahead of ~/.local/bin for the wrappers to work.")
        return

    bin_idx = norm_dirs.index(norm_bin)
    if norm_local in norm_dirs:
        local_idx = norm_dirs.index(norm_local)
        if bin_idx > local_idx:
            print(f"\nWARNING: {bin_dir} appears AFTER ~/.local/bin in PATH.")
            print("Move it earlier so the wrapper takes precedence over the real binary.")
        else:
            print(f"\nPATH looks good: {bin_dir} is ahead of ~/.local/bin.")
    else:
        print(f"\nPATH looks good: {bin_dir} is in PATH.")


def main():
    print("=" * 60)
    print("  Multi-Account Claude Code Setup")
    print("=" * 60)

    # Find claude binary
    claude_exe = find_claude_exe()
    claude_exe = ask("\nPath to claude binary", default=claude_exe)

    # Configure accounts
    accounts = setup_accounts()
    if len(accounts) < 2:
        print("\nNeed at least 2 accounts. Aborting.")
        sys.exit(1)

    # Confirm
    print("\n--- Configuration Summary ---")
    print(f"Claude binary: {claude_exe}")
    for i, acct in enumerate(accounts):
        d = acct["config_dir"] or "~/.claude (default)"
        print(f"  [{i + 1}] {acct['label']} (id={acct['id']}, color={acct['color']}, dir={d})")

    if not ask_yn("\nProceed with setup?"):
        print("Aborted.")
        sys.exit(0)

    # Execute setup steps
    write_config(claude_exe, accounts)
    create_config_dirs(accounts)
    copy_guard_hook(accounts)
    write_settings_json(accounts)
    write_claude_md_isolation(accounts)
    copy_launcher(accounts)
    copy_wrappers()
    check_path()

    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print("\nRun 'claude' from your terminal to test the account picker.")


if __name__ == "__main__":
    main()
