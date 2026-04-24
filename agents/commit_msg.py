import openai
import os
import subprocess
import re
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from session_context import get_api_key

openai.api_key = get_api_key()

def commit_msg_agent(state):
    """
    Generate intelligent commit messages based on git diff and auto-push
    """
    cwd = state.get("cwd", "") or os.getcwd()
    command = state.get("command", "") or ""
    prompt = state.get("prompt", "") or ""
    
    if not _needs_commit_message(command, prompt):
        return state
    
    print(" Analyzing code changes to generate commit message...")
    
    try:
        staged_diff = _get_git_diff(cwd, staged=True)
        unstaged_diff = _get_git_diff(cwd, staged=False)
        
        if not staged_diff.strip() and unstaged_diff.strip():
            print(" No staged changes found. Staging all changes...")
            subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True, text=True)
            staged_diff = _get_git_diff(cwd, staged=True)
        
        if not staged_diff.strip():
            state["error"] = "No changes to commit"
            print(" No changes found to commit")
            return state
        
        status_output = _get_git_status(cwd)
        commit_msg = _generate_intelligent_commit_message(staged_diff, status_output, prompt)
        
        if not commit_msg:
            commit_msg = "Update code changes"
            
        # Update the command to include the commit message AND auto-push
        state["command"] = _update_command_with_message(command, commit_msg)
        state["generated_commit_msg"] = commit_msg
        print(f" Generated commit message: '{commit_msg}'")
        
    except Exception as e:
        print(f"  Commit message generation error: {e}")
        fallback_msg = "Code update"
        state["command"] = _update_command_with_message(command, fallback_msg)
        state["generated_commit_msg"] = fallback_msg
    
    return state

def _needs_commit_message(command, prompt):
    command = command or ""
    prompt = prompt or ""
    if "git commit" not in command.lower() and "commit" not in prompt.lower():
        return False
    return not any(flag in command.lower() for flag in ['-m', '--message', '--file', '-F'])

def _get_git_diff(cwd, staged=True):
    try:
        args = ["git", "diff", "--cached"] if staged else ["git", "diff"]
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""

def _get_git_status(cwd):
    try:
        result = subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""

def _generate_intelligent_commit_message(diff_output, status_output, user_prompt):
    diff_output = str(diff_output or "")
    if not diff_output.strip():
        return None
    
    prompt = f"""You are an expert developer writing commit messages. Analyze this git diff and create a SPECIFIC, detailed commit message.
    
USER'S INTENT: "{user_prompt}"
ACTUAL CODE DIFF:
{diff_output[:2000]}

REQUIREMENTS:
1. Format: type(scope): description
2. Be SPECIFIC about functionality
3. Keep under 60 characters
4. Generate ONLY the message, no quotes.
"""
    try:
        response = openai.ChatCompletion.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=60
        )
        content = response['choices'][0]['message']['content'] or ""
        return str(content).strip().replace('"', '').replace("'", "")
    except Exception:
        return f"chore: update files related to {user_prompt[:20]}"

def _update_command_with_message(command, commit_msg):
    command = command.strip()
    escaped_msg = commit_msg.replace('"', '\\"').replace("'", "\\'")
    
    if "git commit" in command.lower():
        if "-m" not in command.lower() and "--message" not in command.lower():
            command = command + f' -m "{escaped_msg}"'
        else:
            command = re.sub(r'-m\s+"[^"]*"', f'-m "{escaped_msg}"', command)
            command = re.sub(r"-m\s+'[^']*'", f'-m "{escaped_msg}"', command)
    else:
        if command.lower() == "commit":
            command = f'git commit -m "{escaped_msg}"'
        else:
            command = f'{command} -m "{escaped_msg}"'
    
    # ADD AUTO-PUSH
    return f"{command}; git push"