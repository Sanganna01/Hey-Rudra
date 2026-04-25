import openai
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from session_context import get_api_key

openai.api_key = get_api_key()

def generate_command_agent(state):
    prompt = state["prompt"]
    cwd = state["cwd"]
    file_list = os.listdir(cwd)

    user_prompt = f"""
You are a CLI assistant. You are currently in: {cwd}
This folder contains: {file_list}

Instruction: \"{prompt}\"

Convert this to a Windows PowerShell command. Output ONLY the valid PowerShell command. Do NOT use Linux commands like 'ls', 'grep', 'head', 'cat', or 'awk'. Use native PowerShell cmdlets like Get-Process, Select-Object, Where-Object, etc.

CRITICAL: If the user is asking to 'commit', 'push', or 'save' changes to git, ensure the command follows this exact sequence to prevent push rejections: 'git add .; git commit -m "message"; git pull --rebase origin main; git push'
CRITICAL: If the user is asking to 'delete' or 'remove' a file, and it's a git repo, use 'git rm <file>; git commit -m "Delete <file>"; git push' to ensure it is removed from both codebase and GitHub.
"""

    response = openai.ChatCompletion.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0
    )

    command = response['choices'][0]['message']['content'].strip()
    
    # Strip markdown backticks
    if command.startswith("```"):
        lines = command.split('\n')
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        command = '\n'.join(lines).strip()

    state["command"] = command
    return state
