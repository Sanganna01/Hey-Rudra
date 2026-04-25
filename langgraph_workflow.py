"""
langgraph_workflow.py
=====================
Main agent workflow graph for HeyRudra.

Flow
----
  User Prompt
      |
  [Planner]
      |
      +---> file_writer   (write/create file content)   --> END
      +---> revert_agent  (history / undo / revert)     --> END
      +---> command_gen   (everything else)
                |
                +---> commit_msg  (git commits)
                |         |
                +----+----+
                     |
                +---> verifier  (dangerous commands)
                |         |
                +----+----+
                     |
                [executor] --> END
"""

from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
import sys
import os
import re

sys.path.append(os.path.join(os.path.dirname(__file__), 'agents'))

from agents.planner import planner_agent
from agents.command_gen import generate_command_agent
from agents.commit_msg import commit_msg_agent
from agents.verifier import verifier_agent
from agents.executor import executor_agent
from agents.file_writer import file_writer_agent
from agents.revert_agent import revert_agent


class WorkflowState(TypedDict):
    prompt: str
    cwd: str
    task_type: Optional[str]
    risk_level: Optional[str]
    needs_confirmation: Optional[bool]
    special_handling: Optional[str]
    analysis: Optional[str]
    git_context: Optional[dict]
    cd_context: Optional[dict]
    command: Optional[str]
    stdout: Optional[str]
    stderr: Optional[str]
    return_code: Optional[int]
    status: Optional[str]
    error: Optional[str]
    execution_time: Optional[float]
    commit_hash: Optional[str]
    generated_commit_msg: Optional[str]
    verification_result: Optional[dict]
    verification_error: Optional[str]
    verification_passed: Optional[bool]
    safety_score: Optional[int]
    safety_warnings: Optional[list]


# ── Intent detection helpers ──────────────────────────────────────────────────

_WRITE_KEYWORDS = re.compile(
    r'\b(write|create|generate|make|put|add|fill|insert|code)\b', re.IGNORECASE,
)
_FILE_PATTERN = re.compile(r'\b[\w\-]+\.\w{1,5}\b')

# Also match "file named X" even without an extension
_FILE_NAMED_PATTERN = re.compile(
    r'\b(?:file\s+named?|named?\s+file|file\s+called)\s+[\w\-]+', re.IGNORECASE,
)

# Language keywords that imply file creation
_LANG_FILE_PATTERN = re.compile(
    r'(python|java|javascript|c\+\+|cpp|rust|go|ruby|html|css|sql|php|'
    r'typescript|bash|shell|markdown)\s+file', re.IGNORECASE,
)

_REVERT_KEYWORDS = re.compile(
    r'\b(revert|undo|rollback|roll\s*back|history|show\s*history|'
    r'list\s*history|view\s*history|go\s*back|previous\s*version|'
    r'restore|time\s*travel)\b',
    re.IGNORECASE,
)


def _is_file_write_request(prompt: str) -> bool:
    has_write = bool(_WRITE_KEYWORDS.search(prompt))
    has_file = (bool(_FILE_PATTERN.search(prompt))
                or bool(_FILE_NAMED_PATTERN.search(prompt))
                or bool(_LANG_FILE_PATTERN.search(prompt)))
    return has_write and has_file


def _is_revert_request(prompt: str) -> bool:
    return bool(_REVERT_KEYWORDS.search(prompt))


# ── Routing functions ─────────────────────────────────────────────────────────

def route_after_planner(state: WorkflowState) -> str:
    prompt = state.get("prompt", "")
    task_type = (state.get("task_type") or "").lower()

    # Revert / history always goes to revert_agent
    if _is_revert_request(prompt):
        return "revert_agent"

    # File write/create goes to file_writer
    if task_type == "file_ops" and _is_file_write_request(prompt):
        return "file_writer"

    # Everything else (git, list, search, run, etc.) goes to command_gen
    return "command_gen"


def route_after_command_gen(state: WorkflowState) -> str:
    task_type = (state.get("task_type") or "").lower()
    git_context = state.get("git_context") or {}

    if task_type == "git" and git_context.get("needs_commit_msg", False):
        return "commit_msg"

    risk_level = state.get("risk_level", "safe")
    if risk_level == "dangerous" or state.get("needs_confirmation"):
        return "verifier"
    return "executor"


def route_to_execution(state: WorkflowState) -> str:
    risk_level = state.get("risk_level", "safe")
    if risk_level == "dangerous" or state.get("needs_confirmation"):
        return "verifier"
    return "executor"


# ── Main workflow ─────────────────────────────────────────────────────────────

def run_agent_flow(prompt: str, context: dict) -> WorkflowState:
    workflow = StateGraph(WorkflowState)

    # Nodes
    workflow.add_node("planner", planner_agent)
    workflow.add_node("file_writer", file_writer_agent)
    workflow.add_node("revert_agent", revert_agent)
    workflow.add_node("command_gen", generate_command_agent)
    workflow.add_node("commit_msg", commit_msg_agent)
    workflow.add_node("verifier", verifier_agent)
    workflow.add_node("executor", executor_agent)

    # Entry
    workflow.set_entry_point("planner")

    # After planner → file_writer | revert_agent | command_gen
    workflow.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "file_writer": "file_writer",
            "revert_agent": "revert_agent",
            "command_gen": "command_gen",
        },
    )

    # Terminal nodes
    workflow.add_edge("file_writer", END)
    workflow.add_edge("revert_agent", END)

    # After command_gen → commit_msg | verifier | executor
    workflow.add_conditional_edges(
        "command_gen",
        route_after_command_gen,
        {
            "commit_msg": "commit_msg",
            "verifier": "verifier",
            "executor": "executor",
        },
    )

    # After commit_msg → verifier | executor
    workflow.add_conditional_edges(
        "commit_msg",
        route_to_execution,
        {
            "verifier": "verifier",
            "executor": "executor",
        },
    )

    # After verifier → executor (only if passed) | END
    workflow.add_conditional_edges(
        "verifier",
        lambda s: "executor" if s.get("verification_passed") else END,
        {
            "executor": "executor",
            END: END,
        },
    )

    workflow.add_edge("executor", END)

    app = workflow.compile()

    initial_state: WorkflowState = {
        "prompt": prompt,
        "cwd": context["cwd"],
        "task_type": None,
        "risk_level": None,
        "needs_confirmation": None,
        "special_handling": None,
        "analysis": None,
        "git_context": None,
        "cd_context": None,
        "command": None,
        "stdout": None,
        "stderr": None,
        "return_code": None,
        "status": None,
        "error": None,
        "execution_time": None,
        "commit_hash": None,
        "generated_commit_msg": None,
        "verification_result": None,
        "verification_error": None,
        "verification_passed": None,
        "safety_score": None,
        "safety_warnings": None,
    }

    try:
        return app.invoke(initial_state)
    except Exception as e:
        initial_state["error"] = str(e)
        initial_state["status"] = "error"
        return initial_state