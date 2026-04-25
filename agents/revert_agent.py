"""
revert_agent.py
===============
LangGraph agent that handles:
  - "show history" / "list history"
  - "revert last change"
  - "revert last N changes"
  - "undo"
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from history.history_store import get_history
from history.revert_engine import revert_last_n, format_history


def revert_agent(state: dict) -> dict:
    prompt = (state.get("prompt") or "").lower().strip()
    cwd = state.get("cwd") or os.getcwd()

    # ── Show history ─────────────────────────────────────────────────────────
    if any(kw in prompt for kw in ("show history", "list history", "view history",
                                    "my history", "history")):
        events = get_history(limit=25, cwd=cwd)
        state["stdout"] = format_history(events)
        state["status"] = "success"
        state["return_code"] = 0
        return state

    # ── Revert last N changes ─────────────────────────────────────────────────
    m = re.search(r'(?:revert|undo)\s+last\s+(\d+)', prompt)
    if m:
        n = int(m.group(1))
        return _do_revert(state, n, cwd)

    # ── Revert last change (singular) ─────────────────────────────────────────
    if re.search(r'(?:revert|undo)\s+(last|the\s+last|previous|my\s+last)', prompt):
        return _do_revert(state, 1, cwd)

    # ── Bare "revert" / "undo" ────────────────────────────────────────────────
    if "revert" in prompt or "undo" in prompt:
        return _do_revert(state, 1, cwd)

    state["error"] = "Could not understand the revert command. Try: heyrudra \"revert last change\""
    state["status"] = "error"
    return state


# ── Helper ────────────────────────────────────────────────────────────────────

def _do_revert(state: dict, n: int, cwd: str) -> dict:
    plural = "s" if n != 1 else ""
    print(f" Reverting last {n} change{plural}...")

    results = revert_last_n(n, cwd)

    ok_lines, fail_lines = [], []
    for success, msg in results:
        if success:
            ok_lines.append(f"  [OK]   {msg}")
        else:
            fail_lines.append(f"  [SKIP] {msg}")

    lines = []
    if ok_lines:
        lines += [f"\nSuccessfully reverted {len(ok_lines)} action{plural}:"] + ok_lines
    if fail_lines:
        lines += ["\nCould not revert (manual action needed):"] + fail_lines
    if not ok_lines and not fail_lines:
        lines = ["\nNothing to revert."]

    state["stdout"] = "\n".join(lines)
    state["status"] = "success"
    state["return_code"] = 0
    return state
