import openai
import os
import re
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from session_context import get_api_key

openai.api_key = get_api_key()

def planner_agent(state):
    """
    Analyzes the user's natural language prompt to determine:
    1. Task type (cd, git, file operations, etc.)
    2. Intent and context
    3. Any special handling needed
    """
    prompt = state.get("prompt", "") or ""
    cwd = state.get("cwd", "") or os.getcwd()
    
    # Define task patterns for quick detection
    task_patterns = {
        "cd": r'\b(cd|change directory|go to|navigate to)\b',
        "git": r'\b(git|commit|push|pull|clone|status|add|branch|stage)\b',
        "file_ops": r'\b(create|make|copy|move|delete|rm|touch|mkdir)\b',
        "list": r'\b(ls|list|dir|show files|see files)\b',
        "search": r'\b(find|search|grep|locate)\b',
        "env": r'\b(activate|deactivate|venv|virtualenv|conda)\b',
        "install": r'\b(install|pip|npm|yarn|apt|brew)\b',
        "run": r'\b(run|execute|start|launch)\b',
        "help": r'\b(help|what|how)\b'
    }
    
    # Quick pattern matching for common tasks
    detected_type = "general"
    for task_type, pattern in task_patterns.items():
        if re.search(pattern, prompt.lower()):
            detected_type = task_type
            break
    
    # Use LLM for more complex intent analysis
    analysis_prompt = f"""
Analyze this natural language command and determine:
1. Primary task type
2. Risk level (safe/moderate/dangerous)
3. Any special considerations

Current directory: {cwd}
Command: "{prompt}"

Task types: cd, git, file_ops, list, search, env, install, run, help, general

Respond in this format:
TASK_TYPE: [type]
RISK_LEVEL: [safe/moderate/dangerous]
NEEDS_CONFIRMATION: [yes/no]
SPECIAL_HANDLING: [any special notes]
"""

    try:
        response = openai.ChatCompletion.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": analysis_prompt}],
            temperature=0,
            max_tokens=200
        )
        
        analysis = response['choices'][0]['message']['content'].strip()
        
        # Parse the structured response
        task_type = detected_type
        risk_level = "safe"
        needs_confirmation = False
        special_handling = ""
        
        for line in analysis.split('\n'):
            if line.startswith('TASK_TYPE:'):
                parsed_type = line.split(':', 1)[1].strip().lower()
                if parsed_type:
                    task_type = parsed_type
            elif line.startswith('RISK_LEVEL:'):
                parsed_risk = line.split(':', 1)[1].strip().lower()
                if parsed_risk:
                    risk_level = parsed_risk
            elif line.startswith('NEEDS_CONFIRMATION:'):
                parsed_conf = line.split(':', 1)[1].strip().lower()
                needs_confirmation = parsed_conf == 'yes'
            elif line.startswith('SPECIAL_HANDLING:'):
                special_handling = line.split(':', 1)[1].strip()
        
        # Update state with analysis
        state["task_type"] = task_type
        state["risk_level"] = risk_level
        state["needs_confirmation"] = needs_confirmation
        state["special_handling"] = special_handling or ""
        state["analysis"] = analysis
        
        # Add context for Git operations
        if task_type == "git":
            state["git_context"] = _analyze_git_context(cwd, prompt)
        
        # Add context for directory operations
        if task_type == "cd":
            state["cd_context"] = _analyze_cd_context(cwd, prompt)
            
        print(f"🧠 Planned task: {task_type} (risk: {risk_level})")
        if special_handling:
            print(f"⚠️  Special handling: {special_handling}")
            
    except Exception as e:
        print(f"Planning error: {e}")
        # Fallback to pattern-based detection
        state["task_type"] = detected_type
        state["risk_level"] = "safe"
        state["needs_confirmation"] = False
        state["special_handling"] = ""
        state["analysis"] = ""
    
    return state

def _analyze_git_context(cwd, prompt):
    """Analyze Git-specific context"""
    context = {
        "is_git_repo": os.path.exists(os.path.join(cwd, ".git")),
        "needs_commit_msg": _should_generate_commit_msg(prompt)
    }
    return context

def _should_generate_commit_msg(prompt):
    """Determine if we should generate a commit message"""
    prompt_lower = prompt.lower()
    
    # Keywords that indicate commit message should be generated
    commit_indicators = [
        "commit", "push", "save changes", "check in", 
        "stage and commit", "add and commit"
    ]
    
    # Keywords that indicate message is already provided
    has_message_indicators = [
        "-m", "--message", "with message", "message:"
    ]
    
    has_commit_intent = any(indicator in prompt_lower for indicator in commit_indicators)
    has_explicit_message = any(indicator in prompt_lower for indicator in has_message_indicators)
    
    return has_commit_intent and not has_explicit_message

def _analyze_cd_context(cwd, prompt):
    """Analyze directory change context"""
    context = {
        "current_dir": cwd,
        "is_relative": not (prompt.startswith('/') or ':' in prompt),
        "target_hint": _extract_target_directory(prompt)
    }
    return context

def _extract_target_directory(prompt):
    """Extract target directory from cd command"""
    # Simple extraction - can be enhanced
    words = prompt.split()
    for i, word in enumerate(words):
        if word.lower() in ['cd', 'to', 'into']:
            if i + 1 < len(words):
                return words[i + 1]
    return None