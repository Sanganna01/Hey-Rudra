from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
import sys
import os

# Add the agents directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'agents'))

# Import agents
from agents.planner import planner_agent
from agents.command_gen import generate_command_agent
from agents.commit_msg import commit_msg_agent  
from agents.verifier import verifier_agent
from agents.executor import executor_agent

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

def route_after_command_gen(state: WorkflowState) -> str:
    """Decide if we need a commit message or skip to verification"""
    task_type = state.get("task_type", "") or ""
    git_context = state.get("git_context", {}) or {}
    
    if task_type == "git" and git_context.get("needs_commit_msg", False):
        return "commit_msg"
    
    # Otherwise go to verifier or executor
    risk_level = state.get("risk_level", "safe")
    if risk_level == "dangerous" or state.get("needs_confirmation"):
        return "verifier"
    return "executor"

def route_to_execution(state: WorkflowState) -> str:
    """Decide if we need verification before execution"""
    risk_level = state.get("risk_level", "safe")
    if risk_level == "dangerous" or state.get("needs_confirmation"):
        return "verifier"
    return "executor"

def run_agent_flow(prompt: str, context: dict) -> WorkflowState:
    workflow = StateGraph(WorkflowState)
    
    workflow.add_node("planner", planner_agent)
    workflow.add_node("command_gen", generate_command_agent)
    workflow.add_node("commit_msg", commit_msg_agent)
    workflow.add_node("verifier", verifier_agent)
    workflow.add_node("executor", executor_agent)
    
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "command_gen")
    
    workflow.add_conditional_edges(
        "command_gen",
        route_after_command_gen,
        {
            "commit_msg": "commit_msg",
            "verifier": "verifier",
            "executor": "executor"
        }
    )
    
    workflow.add_conditional_edges(
        "commit_msg",
        route_to_execution,
        {
            "verifier": "verifier",
            "executor": "executor"
        }
    )
    
    # After verification, go to execution only if passed
    workflow.add_conditional_edges(
        "verifier",
        lambda state: "executor" if state.get("verification_passed") else END,
        {
            "executor": "executor",
            END: END
        }
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
        "safety_warnings": None
    }
    
    try:
        return app.invoke(initial_state)
    except Exception as e:
        initial_state["error"] = str(e)
        initial_state["status"] = "error"
        return initial_state