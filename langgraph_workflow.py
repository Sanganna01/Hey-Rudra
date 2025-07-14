from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
import sys
import os

# Add the agents directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'agents'))




# Import agents - these should be in the agents/ folder
from agents.planner import planner_agent
from agents.command_gen import generate_command_agent
from agents.commit_msg import commit_msg_agent  
from agents.verifier import verifier_agent
from agents.executor import executor_agent

class WorkflowState(TypedDict):
    """State schema for the workflow"""
    # Input
    prompt: str
    cwd: str
    
    # Planning
    task_type: Optional[str]
    risk_level: Optional[str]
    needs_confirmation: Optional[bool]
    special_handling: Optional[str]
    analysis: Optional[str]
    
    # Context
    git_context: Optional[dict]
    cd_context: Optional[dict]
    
    # Command generation
    command: Optional[str]
    
    # Execution
    stdout: Optional[str]
    stderr: Optional[str]
    return_code: Optional[int]
    status: Optional[str]
    error: Optional[str]
    execution_time: Optional[float]
    
    # Git specific
    commit_hash: Optional[str]
    generated_commit_msg: Optional[str]
    
    # Verification
    verification_result: Optional[dict]
    verification_error: Optional[str]
    verification_passed: Optional[bool]
    safety_score: Optional[int]
    safety_warnings: Optional[list]

def should_generate_commit_message(state: WorkflowState) -> str:
    """Decide if we need to generate a commit message"""
    task_type = state.get("task_type", "") or ""
    git_context = state.get("git_context", {}) or {}
    
    if task_type == "git" and git_context.get("needs_commit_msg", False):
        return "commit_msg"
    else:
        return "command_gen"

def should_verify_command(state: WorkflowState) -> str:
    """Decide if we need to verify the command"""
    risk_level = state.get("risk_level", "") or "safe"
    needs_confirmation = state.get("needs_confirmation", False) or False
    
    if risk_level == "dangerous" or needs_confirmation:
        return "verifier"
    else:
        return "executor"

def run_agent_flow(prompt: str, context: dict) -> WorkflowState:
    """Run the complete agent workflow"""
    
    # Initialize the workflow graph
    workflow = StateGraph(WorkflowState)
    
    # Add nodes
    workflow.add_node("planner", planner_agent)
    workflow.add_node("command_gen", generate_command_agent)
    workflow.add_node("commit_msg", commit_msg_agent)
    workflow.add_node("verifier", verifier_agent)
    workflow.add_node("executor", executor_agent)
    
    # Define the flow
    workflow.set_entry_point("planner")
    
    # Conditional routing after planner
    workflow.add_conditional_edges(
        "planner",
        should_generate_commit_message,
        {
            "commit_msg": "commit_msg",
            "command_gen": "command_gen"
        }
    )
    
    # After commit message generation, go to command generation
    workflow.add_edge("commit_msg", "command_gen")
    
    # After command generation, conditional routing to verification
    workflow.add_conditional_edges(
        "command_gen",
        should_verify_command,
        {
            "verifier": "verifier",
            "executor": "executor"
        }
    )
    
    # After verification, go to execution
    workflow.add_edge("verifier", "executor")
    
    # End after execution
    workflow.add_edge("executor", END)
    
    # Compile the workflow
    app = workflow.compile()
    
    # Initial state
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
    
    # Run the workflow
    try:
        result = app.invoke(initial_state)
        return result
    except Exception as e:
        print(f"Workflow error: {e}")
        # Return error state
        initial_state["error"] = str(e)
        initial_state["status"] = "error"
        return initial_state

def run_simple_flow(prompt: str, context: dict) -> WorkflowState:
    """Simplified linear flow for testing"""
    state: WorkflowState = {
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
        # Run agents in sequence
        print("🧠 Planning...")
        state = planner_agent(state)
        
        print("⚙️  Generating command...")
        state = generate_command_agent(state)
        
        print("🚀 Executing...")
        state = executor_agent(state)
        
        return state
        
    except Exception as e:
        print(f"Simple flow error: {e}")
        state["error"] = str(e)
        state["status"] = "error"
        return state