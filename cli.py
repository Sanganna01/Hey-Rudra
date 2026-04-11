import os
import sys
import subprocess
import openai
from session_context import get_current_context, get_api_key
from redis_client import get_cache, set_cache
from langgraph_workflow import run_agent_flow

openai.api_key = get_api_key()  # Use environment variable for the key to avoid leaking secrets
openai.api_base = "https://api.groq.com/openai/v1"

def main():
    if len(sys.argv) < 2:
        print("Usage: heyrudra \"<natural language command>\"")
        sys.exit(1)

    prompt = sys.argv[1]
    context = get_current_context()
    cwd = context['cwd']

    print(f"🎯 Interpreting: '{prompt}'")
    print(f"📁 Current folder: {cwd}")
    print()

    cached = get_cache(prompt)
    if cached:
        command = cached.decode()
        print("⚡ Using cached command:")
        print(f"   {command}")
        print()
        print("🚀 Executing cached command...")
        
        if os.name == 'nt':
            subprocess.run(["powershell", "-NoProfile", "-Command", command], cwd=cwd)
        else:
            subprocess.run(command, shell=True, cwd=cwd)
        return

    # Run the agent workflow
    state = run_agent_flow(prompt, context)

    # Display results with better formatting
    print()
    print("=" * 50)
    
    if state.get("status") == "success":
        print("🎉 EXECUTION SUCCESSFUL")
        if state.get("stdout") and state.get("stdout").strip():
            print("\n📤 Output:")
            print(state["stdout"].strip())
    elif state.get("status") == "partial_success":
        print("EXECUTION COMPLETED WITH WARNINGS")
        if state.get("stdout") and state.get("stdout").strip():
            print("\n📤 Output:")
            print(state["stdout"].strip())
        if state.get("stderr") and state.get("stderr").strip():
            print("\n  Warnings:")
            print(state["stderr"].strip())
    elif state.get("status") == "error":
        print(" EXECUTION FAILED")
        if state.get("error"):
            print(f"\n Error: {state['error']}")
        if state.get("stderr") and state.get("stderr").strip():
            print(f"\nDetails: {state['stderr'].strip()}")
    else:
        print("❓ UNKNOWN STATUS")
        if state.get("stdout") and state.get("stdout").strip():
            print(f"\nOutput: {state['stdout'].strip()}")
        if state.get("stderr") and state.get("stderr").strip():
            print(f"\n  Errors: {state['stderr'].strip()}")

    # Cache successful commands
    if state.get("command") and state.get("status") in ["success", "partial_success"]:
        set_cache(prompt, state["command"])
        print(f"\n💾 Command cached for future use")

    print("=" * 50)

if __name__ == "__main__":
    main()