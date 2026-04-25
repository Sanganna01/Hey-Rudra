"""
revert_engine.py
================
Core logic for reverting events and restoring file states.

Strategy
--------
- file_create  → delete the file
- file_edit    → restore content_before
- file_delete  → restore content_before (bring file back)
- shell_command→ warn user (cannot auto-revert shell side-effects)
- group revert → revert all events in group, newest-first
"""

import os
import json

from history.history_store import (
    get_history,
    get_events_in_group,
    get_nearest_snapshot_before,
    get_events_after_snapshot,
)


# ─── Single-event revert ───────────────────────────────────────────────────────

def revert_event(event: dict, cwd: str):
    """
    Revert one event.
    Returns (success: bool, message: str).
    """
    etype = event.get("type", "")
    filename = event.get("filename")
    content_before = event.get("content_before")

    if etype == "file_create":
        if not filename:
            return False, "Event has no filename — skipped."
        fpath = os.path.join(cwd, filename)
        if os.path.exists(fpath):
            os.remove(fpath)
            return True, f"Deleted '{filename}'  (reverted creation)"
        return False, f"'{filename}' already absent — skipped."

    elif etype in ("file_edit", "file_delete"):
        if not filename:
            return False, "Event has no filename — skipped."
        if content_before is None:
            return False, f"No previous content stored for '{filename}' — skipped."
        fpath = os.path.join(cwd, filename)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content_before)
        action = "restored" if etype == "file_delete" else "rolled back"
        return True, f"'{filename}' {action} to previous version"

    elif etype == "shell_command":
        cmd = event.get("command", "")
        return False, f"Cannot auto-revert shell command: `{cmd[:60]}`"

    elif etype == "git_commit":
        return False, "Cannot auto-revert git commits — use `git revert` manually."

    return False, f"Unknown event type '{etype}' — skipped."


# ─── Group revert ─────────────────────────────────────────────────────────────

def revert_group(group_id: str, cwd: str):
    """
    Revert every event in an action-group, newest-first.
    Returns list of (success, message).
    """
    events = get_events_in_group(group_id)
    events.reverse()          # undo in reverse order
    return [revert_event(e, cwd) for e in events]


# ─── Revert last N events ─────────────────────────────────────────────────────

def revert_last_n(n: int, cwd: str):
    """
    Revert the N most-recent events for this cwd.
    Returns list of (success, message).
    """
    history = get_history(limit=n, cwd=cwd)
    if not history:
        return [(False, "No history found for this directory.")]

    results = []
    seen_groups = set()

    for event in history:
        gid = event.get("group_id")
        if gid and gid in seen_groups:
            continue                          # already handled entire group
        if gid:
            seen_groups.add(gid)
            results.extend(revert_group(gid, cwd))
        else:
            results.append(revert_event(event, cwd))

    return results


# ─── Snapshot-based full restore ──────────────────────────────────────────────

def restore_from_snapshot(snapshot: dict, cwd: str):
    """
    Restore the entire working directory to a snapshot state.
    USE WITH CAUTION — overwrites current files.
    """
    files = json.loads(snapshot.get("files_json", "{}"))
    restored, skipped = [], []

    for fname, content in files.items():
        fpath = os.path.join(cwd, fname)
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            restored.append(fname)
        except Exception as e:
            skipped.append(f"{fname} ({e})")

    return restored, skipped


# ─── Display helpers ──────────────────────────────────────────────────────────

def format_history(events: list) -> str:
    """Format event list into a human-readable history table."""
    if not events:
        return "\nNo history recorded yet. Start using heyrudra to track changes!\n"

    lines = [
        "",
        "=" * 65,
        "  HeyRudra  --  Version History  (most recent first)",
        "=" * 65,
        f"  {'#':<4} {'Time':<19} {'Type':<14} {'Detail':<30} {'Group'}",
        "-" * 65,
    ]
    for i, e in enumerate(events, 1):
        ts = (e.get("timestamp") or "")[:19].replace("T", " ")
        etype = (e.get("type") or "unknown")[:13]
        detail = (
            e.get("label")
            or e.get("filename")
            or e.get("command", "")[:30]
            or "—"
        )[:30]
        grp = "[group]" if e.get("group_id") else ""
        lines.append(f"  #{i:<3} {ts}  {etype:<14} {detail:<30} {grp}")

    lines += [
        "=" * 65,
        "  Commands:",
        '    heyrudra "revert last change"',
        '    heyrudra "revert last 3 changes"',
        '    heyrudra "show history"',
        "=" * 65,
        "",
    ]
    return "\n".join(lines)
