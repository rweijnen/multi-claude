#!/usr/bin/env python
"""Claude Code account launcher.

Config-driven TUI picker that lets the user choose between multiple
Anthropic accounts, sets the appropriate environment variables and
Windows Terminal tab color, then launches the real claude binary.

Configuration is read from ~/.claude-launcher.json.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

CHOICE_FILE = Path.home() / ".claude-account"
CONFIG_FILE = Path.home() / ".claude-launcher.json"

# Windows Terminal reset: restore default tab color (OSC 104;264)
WT_RESET = "\x1b]104;264\x07"


# -- Color utilities --------------------------------------------------------

def hex_to_rgb(color):
    """Parse '#RRGGBB' or 'RRGGBB' -> (r, g, b)."""
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"Invalid hex color: {color}")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def rgb_to_ansi256(r, g, b):
    """Map RGB to nearest xterm-256 color index."""
    # Check grayscale ramp first (indices 232-255)
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round((r - 8) / 247 * 24) + 232

    # Map to the 6x6x6 color cube (indices 16-231)
    ri = round(r / 255 * 5)
    gi = round(g / 255 * 5)
    bi = round(b / 255 * 5)
    return 16 + 36 * ri + 6 * gi + bi


def ansi_fg(color_index):
    """Return ESC[38;5;Nm string for foreground color."""
    return f"\033[38;5;{color_index}m"


def wt_tab_sequence(r, g, b):
    """Return OSC 4;264;rgb:RR/GG/BB BEL string for Windows Terminal tab color."""
    return f"\x1b]4;264;rgb:{r:02x}/{g:02x}/{b:02x}\x07"


# -- Config loading ---------------------------------------------------------

def default_claude_exe():
    """Return the default claude binary path for this platform."""
    if platform.system() == "Windows":
        return str(Path.home() / ".local" / "bin" / "claude.exe")
    return str(Path.home() / ".local" / "bin" / "claude")


def default_config():
    """Return a minimal single-account config when no config file exists."""
    return {
        "claude_exe": default_claude_exe(),
        "accounts": [
            {
                "id": "default",
                "label": "Default",
                "color": "#ffffff",
                "config_dir": None,
                "hotkey": "d",
            }
        ],
    }


def load_config():
    """Load and validate ~/.claude-launcher.json, with fallbacks."""
    if not CONFIG_FILE.exists():
        return default_config()

    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: failed to load {CONFIG_FILE}: {exc}", file=sys.stderr)
        return default_config()

    if "accounts" not in cfg or not cfg["accounts"]:
        print(f"Warning: no accounts in {CONFIG_FILE}, using defaults", file=sys.stderr)
        return default_config()

    # Fill in defaults
    cfg.setdefault("claude_exe", default_claude_exe())
    for acct in cfg["accounts"]:
        acct.setdefault("id", acct.get("label", "default").lower())
        acct.setdefault("label", acct["id"].title())
        acct.setdefault("color", "#ffffff")
        acct.setdefault("config_dir", None)
        acct.setdefault("hotkey", acct["id"][0] if acct["id"] else "x")

    return cfg


# -- Account helpers --------------------------------------------------------

def resolve_config_dir(acct):
    """Return the resolved config dir path, or None for the default account."""
    d = acct.get("config_dir")
    if d:
        return str(Path(d).resolve())
    return None


def compute_forbidden_dirs(accounts, current_index):
    """Compute the forbidden dirs for account at current_index.

    Returns a list of resolved config dir paths for all OTHER accounts.
    For accounts with config_dir=None (default), use ~/.claude as the path.
    """
    forbidden = []
    default_dir = str(Path.home() / ".claude")
    for i, acct in enumerate(accounts):
        if i == current_index:
            continue
        d = resolve_config_dir(acct)
        if d:
            forbidden.append(d)
        else:
            forbidden.append(default_dir)
    return forbidden


# -- TUI menu --------------------------------------------------------------

def read_last_choice(accounts):
    """Read the last account choice from disk."""
    try:
        text = CHOICE_FILE.read_text(encoding="utf-8").strip().lower()
        for acct in accounts:
            if acct["id"] == text:
                return text
    except OSError:
        pass
    return accounts[0]["id"]


def save_choice(choice):
    """Persist the account choice to disk."""
    try:
        CHOICE_FILE.write_text(choice + "\n", encoding="utf-8")
    except OSError:
        pass


def show_menu(accounts, default_id):
    """Display the account picker on stderr and return the chosen account id."""
    if platform.system() == "Windows":
        return _menu_windows(accounts, default_id)
    return _menu_unix(accounts, default_id)


def _build_key_map(accounts):
    """Build a mapping from key press -> account id."""
    key_map = {}
    for i, acct in enumerate(accounts):
        # Number key (1-9)
        if i < 9:
            key_map[str(i + 1)] = acct["id"]
        # Hotkey letter
        hk = acct.get("hotkey", "")
        if hk and hk.lower() not in key_map:
            key_map[hk.lower()] = acct["id"]
    return key_map


def _render_menu(accounts, default_id):
    """Render the menu text to stderr."""
    stderr = sys.stderr
    stderr.write(f"\n{BOLD}Claude Code -- Select Account{RESET}\n")

    for i, acct in enumerate(accounts):
        try:
            r, g, b = hex_to_rgb(acct["color"])
            color = ansi_fg(rgb_to_ansi256(r, g, b))
        except (ValueError, KeyError):
            color = ""

        marker = f" {DIM}(default){RESET}" if acct["id"] == default_id else ""
        num = i + 1
        hk = acct.get("hotkey", "")
        key_hint = f"{num}"
        if hk:
            key_hint = f"{num}/{hk}"
        stderr.write(f"  {color}[{key_hint}]{RESET} {acct['label']}{marker}\n")

    # Build prompt hint
    keys = []
    for i, acct in enumerate(accounts):
        if i < 9:
            keys.append(str(i + 1))
    hotkeys = [a.get("hotkey", "") for a in accounts if a.get("hotkey")]
    hint = "/".join(keys)
    if hotkeys:
        hint += " or " + "/".join(hotkeys)
    stderr.write(f"  {DIM}[c]{RESET} Configure accounts...\n")
    stderr.write(f"\n{DIM}Press {hint}, Enter=default, c=config, q=quit{RESET} > ")
    stderr.flush()


def _menu_windows(accounts, default_id):
    """Windows menu using msvcrt."""
    import msvcrt

    key_map = _build_key_map(accounts)
    id_to_label = {a["id"]: a["label"] for a in accounts}
    _render_menu(accounts, default_id)

    while True:
        ch = msvcrt.getch()
        # Handle escape sequences (arrow keys etc.) -- ignore
        if ch in (b"\x00", b"\xe0"):
            msvcrt.getch()  # consume second byte
            continue
        c = ch.decode("latin-1", errors="replace").lower()
        if c in key_map:
            chosen = key_map[c]
            sys.stderr.write(f"{id_to_label[chosen]}\n")
            return chosen
        elif c in ("\r", "\n"):
            sys.stderr.write(f"{id_to_label[default_id]}\n")
            return default_id
        elif c == "c":
            sys.stderr.write("Configure\n")
            return "__configure__"
        elif c in ("q", "\x1b"):
            sys.stderr.write("Cancelled\n")
            sys.exit(1)


def _menu_unix(accounts, default_id):
    """Unix menu using tty/termios."""
    import termios
    import tty

    key_map = _build_key_map(accounts)
    id_to_label = {a["id"]: a["label"] for a in accounts}
    _render_menu(accounts, default_id)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            c = os.read(fd, 1).decode("utf-8", errors="replace").lower()
            if c in key_map:
                chosen = key_map[c]
                sys.stderr.write(f"{id_to_label[chosen]}\r\n")
                return chosen
            elif c in ("\r", "\n"):
                sys.stderr.write(f"{id_to_label[default_id]}\r\n")
                return default_id
            elif c == "c":
                sys.stderr.write("Configure\r\n")
                return "__configure__"
            elif c in ("q", "\x1b"):
                sys.stderr.write("Cancelled\r\n")
                sys.exit(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# -- Config management ------------------------------------------------------

DEFAULT_COLORS = ["#cc3333", "#2ecc71", "#3498db", "#e67e22", "#9b59b6",
                  "#1abc9c", "#e74c3c", "#f39c12", "#2980b9"]


def _input(prompt, default=None):
    """Read a line from stdin with optional default."""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    sys.stderr.write(prompt)
    sys.stderr.flush()
    val = input().strip()
    return val if val else default


def save_config(cfg):
    """Write config back to ~/.claude-launcher.json."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    sys.stderr.write(f"Saved {CONFIG_FILE}\n")


def config_add_account(cfg):
    """Add a new account interactively."""
    sys.stderr.write(f"\n{BOLD}Add Account{RESET}\n")
    acct_id = _input("  Account ID (e.g. work, client)")
    if not acct_id:
        sys.stderr.write("  Cancelled.\n")
        return
    acct_id = acct_id.lower().replace(" ", "-")

    # Check for duplicates
    for a in cfg["accounts"]:
        if a["id"] == acct_id:
            sys.stderr.write(f"  Account '{acct_id}' already exists.\n")
            return

    label = _input("  Display label", default=acct_id.title())
    idx = len(cfg["accounts"])
    color = _input("  Hex color (#RRGGBB)",
                   default=DEFAULT_COLORS[idx % len(DEFAULT_COLORS)])
    default_dir = str(Path.home() / f".claude-{acct_id}")
    config_dir = _input("  Config directory", default=default_dir)
    hotkey = _input("  Hotkey letter", default=acct_id[0])

    cfg["accounts"].append({
        "id": acct_id,
        "label": label,
        "color": color,
        "config_dir": config_dir,
        "hotkey": hotkey[0] if hotkey else acct_id[0],
    })
    save_config(cfg)
    sys.stderr.write(f"  Added account '{acct_id}'.\n")


def config_remove_account(cfg):
    """Remove an account interactively."""
    accounts = cfg["accounts"]
    if len(accounts) <= 1:
        sys.stderr.write("  Cannot remove the last account.\n")
        return

    sys.stderr.write(f"\n{BOLD}Remove Account{RESET}\n")
    for i, acct in enumerate(accounts):
        sys.stderr.write(f"  [{i + 1}] {acct['label']} ({acct['id']})\n")
    choice = _input("  Account number to remove")
    if not choice or not choice.isdigit():
        sys.stderr.write("  Cancelled.\n")
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(accounts):
        sys.stderr.write("  Invalid choice.\n")
        return

    removed = accounts.pop(idx)
    save_config(cfg)
    sys.stderr.write(f"  Removed account '{removed['id']}'.\n")
    sys.stderr.write(f"  Note: config directory '{removed.get('config_dir', '~/.claude')}' was NOT deleted.\n")


def config_edit_account(cfg):
    """Edit an existing account interactively."""
    accounts = cfg["accounts"]

    sys.stderr.write(f"\n{BOLD}Edit Account{RESET}\n")
    for i, acct in enumerate(accounts):
        sys.stderr.write(f"  [{i + 1}] {acct['label']} ({acct['id']})\n")
    choice = _input("  Account number to edit")
    if not choice or not choice.isdigit():
        sys.stderr.write("  Cancelled.\n")
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(accounts):
        sys.stderr.write("  Invalid choice.\n")
        return

    acct = accounts[idx]
    sys.stderr.write(f"  Editing '{acct['id']}' (press Enter to keep current value)\n")
    acct["label"] = _input("  Label", default=acct["label"])
    acct["color"] = _input("  Color", default=acct["color"])
    if acct["config_dir"] is not None:
        acct["config_dir"] = _input("  Config dir", default=acct["config_dir"])
    acct["hotkey"] = _input("  Hotkey", default=acct.get("hotkey", acct["id"][0]))
    save_config(cfg)
    sys.stderr.write(f"  Updated account '{acct['id']}'.\n")


def config_menu(cfg):
    """Show the config management submenu."""
    while True:
        sys.stderr.write(f"\n{BOLD}Configure Accounts{RESET}\n")
        sys.stderr.write(f"  [a] Add account\n")
        sys.stderr.write(f"  [r] Remove account\n")
        sys.stderr.write(f"  [e] Edit account\n")
        sys.stderr.write(f"  [l] List accounts\n")
        sys.stderr.write(f"  [q] Back to launcher\n")
        sys.stderr.write(f"\n{DIM}Choice{RESET} > ")
        sys.stderr.flush()

        if platform.system() == "Windows":
            import msvcrt
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                msvcrt.getch()
                continue
            c = ch.decode("latin-1", errors="replace").lower()
        else:
            c = input().strip().lower()[:1]

        if c == "a":
            sys.stderr.write("Add\n")
            config_add_account(cfg)
        elif c == "r":
            sys.stderr.write("Remove\n")
            config_remove_account(cfg)
        elif c == "e":
            sys.stderr.write("Edit\n")
            config_edit_account(cfg)
        elif c == "l":
            sys.stderr.write("List\n")
            sys.stderr.write(f"\n{BOLD}Current Accounts{RESET}\n")
            for i, acct in enumerate(cfg["accounts"]):
                d = acct["config_dir"] or "~/.claude (default)"
                try:
                    r, g, b = hex_to_rgb(acct["color"])
                    color = ansi_fg(rgb_to_ansi256(r, g, b))
                except (ValueError, KeyError):
                    color = ""
                sys.stderr.write(
                    f"  {color}[{i + 1}]{RESET} {acct['label']} "
                    f"(id={acct['id']}, color={acct['color']}, "
                    f"hotkey={acct.get('hotkey', '?')}, dir={d})\n"
                )
        elif c in ("q", "\x1b"):
            sys.stderr.write("Back\n")
            break


# -- Launch -----------------------------------------------------------------

def set_tab_color(acct):
    """Emit Windows Terminal tab color escape sequence."""
    try:
        r, g, b = hex_to_rgb(acct["color"])
        sys.stdout.write(wt_tab_sequence(r, g, b))
        sys.stdout.flush()
    except (ValueError, KeyError):
        pass


def reset_tab_color():
    """Reset Windows Terminal tab color to default."""
    sys.stdout.write(WT_RESET)
    sys.stdout.flush()


def launch(cfg, acct, acct_index, extra_args):
    """Set env vars and launch the claude binary."""
    env = os.environ.copy()

    env["CLAUDE_ACCOUNT"] = acct["id"]

    # Compute and set forbidden dirs (all other accounts' config dirs)
    forbidden = compute_forbidden_dirs(cfg["accounts"], acct_index)
    if forbidden:
        env["CLAUDE_ACCOUNT_FORBIDDEN_DIRS"] = ",".join(forbidden)
    else:
        env.pop("CLAUDE_ACCOUNT_FORBIDDEN_DIRS", None)

    # Also set singular form for backward compat
    if forbidden:
        env["CLAUDE_ACCOUNT_FORBIDDEN_DIR"] = forbidden[0]

    config_dir = resolve_config_dir(acct)
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)

    set_tab_color(acct)
    try:
        result = subprocess.run(
            [cfg["claude_exe"]] + extra_args,
            env=env,
        )
        return result.returncode
    finally:
        reset_tab_color()


# -- Main -------------------------------------------------------------------

def main():
    cfg = load_config()
    accounts = cfg["accounts"]

    # If CLAUDE_ACCOUNT is already set, skip the picker (re-entry guard)
    existing = os.environ.get("CLAUDE_ACCOUNT", "").lower()
    if existing:
        for i, acct in enumerate(accounts):
            if acct["id"] == existing:
                rc = launch(cfg, acct, i, sys.argv[1:])
                sys.exit(rc)

    # Single account -- skip picker
    if len(accounts) == 1:
        rc = launch(cfg, accounts[0], 0, sys.argv[1:])
        sys.exit(rc)

    while True:
        default_id = read_last_choice(accounts)
        choice = show_menu(accounts, default_id)

        if choice == "__configure__":
            config_menu(cfg)
            # Reload config in case accounts were added/removed/edited
            cfg = load_config()
            accounts = cfg["accounts"]
            if len(accounts) == 1:
                choice = accounts[0]["id"]
                break
            continue

        break

    save_choice(choice)

    for i, acct in enumerate(accounts):
        if acct["id"] == choice:
            rc = launch(cfg, acct, i, sys.argv[1:])
            sys.exit(rc)

    # Should not reach here
    print("Error: chosen account not found", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
