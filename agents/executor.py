import subprocess
import os
import sys
import time

# Add parent directory to path to import session_context
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from session_context import set_cwd

# History recording (best-effort — never crash executor if history fails)
try:
    from history.history_store import record_event
    _HISTORY_ENABLED = True
except Exception:
    _HISTORY_ENABLED = False


def _record(type_, command, cwd, label=None, filename=None,
            content_before=None, content_after=None):
    """Wrapper that silently ignores history errors."""
    if not _HISTORY_ENABLED:
        return
    try:
        record_event(
            type_=type_,
            command=command,
            label=label or command[:60],
            filename=filename,
            content_before=content_before,
            content_after=content_after,
            cwd=cwd,
        )
    except Exception:
        pass


def _sniff_deleted_file(command: str, cwd: str):
    """Try to detect the file being deleted and read its content before deletion."""
    import re
    m = re.search(r'git\s+rm\s+["\']?([\w./\\\-]+)["\']?', command, re.IGNORECASE)
    if not m:
        m = re.search(r'(?:Remove-Item|del|rm)\s+["\']?([\w./\\\-]+)["\']?',
                      command, re.IGNORECASE)
    if m:
        fname = m.group(1).strip('.\\/').replace('\\', '/').split('/')[-1]
        fpath = os.path.join(cwd, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                return fname, f.read()
        except Exception:
            pass
    return None, None

def executor_agent(state):
    """
    Safely execute shell commands and capture output.
    Records git commits and file deletions in the history store.
    """
    command = state.get("command", "")
    cwd = state.get("cwd", os.getcwd())
    task_type = state.get("task_type", "general")
    risk_level = state.get("risk_level", "safe")

    if not command:
        state["error"] = "No command to execute"
        return state

    print(f" Executing: {command}")

    # Handle special cases
    if task_type == "cd":
        return _handle_cd_command(state, command, cwd)

    # Safety check for dangerous commands
    if risk_level == "dangerous":
        if not _confirm_dangerous_command(command):
            state["error"] = "Command execution cancelled by user"
            return state

    # Pre-sniff file to be deleted (before it disappears)
    cmd_lower = command.lower()
    is_delete = any(k in cmd_lower for k in ("git rm", "remove-item", "del ", "rm "))
    deleted_file, deleted_content = (None, None)
    if is_delete:
        deleted_file, deleted_content = _sniff_deleted_file(command, cwd)

    # Execute
    if '\n' in command.strip():
        result_state = _execute_multiline_command(state, command, cwd)
    else:
        result_state = _execute_single_command(state, command, cwd)

    # Post-execution history recording
    if result_state.get("return_code") == 0:
        if "git commit" in cmd_lower or "git push" in cmd_lower:
            _record("git_commit", command, cwd,
                    label=state.get("generated_commit_msg") or "git commit")
        elif is_delete and deleted_file:
            _record("file_delete", command, cwd,
                    filename=deleted_file, content_before=deleted_content,
                    label=f"delete '{deleted_file}'")
        else:
            _record("shell_command", command, cwd)

    return result_state

def _execute_single_command(state, command, cwd):
    """Execute a single command"""
    try:
        if os.name == 'nt':
            cmd_args = ["powershell", "-NoProfile", "-Command", command]
            use_shell = False
        else:
            cmd_args = command
            use_shell = True
            
        result = subprocess.run(
            cmd_args,
            shell=use_shell,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30  # 30 second timeout
        )
        
        state["stdout"] = result.stdout
        state["stderr"] = result.stderr
        state["return_code"] = result.returncode
        state["execution_time"] = time.time()
        
        # Handle command-specific post-processing
        task_type = state.get("task_type", "general")
        if task_type == "git" and "commit" in command.lower():
            _handle_git_commit_success(state, result)
        
        # Success/failure indication
        if result.returncode == 0:
            state["status"] = "success"
            print(f" Command completed successfully")
            if result.stdout.strip():
                print(f"Output: {result.stdout.strip()}")
        else:
            state["status"] = "error"
            print(f" Command failed with return code {result.returncode}")
            if result.stderr.strip():
                print(f"Error: {result.stderr.strip()}")
                
    except subprocess.TimeoutExpired:
        state["error"] = "Command timed out after 30 seconds"
        state["status"] = "timeout"
        print(" Command timed out")
        
    except Exception as e:
        state["error"] = f"Execution error: {str(e)}"
        state["status"] = "error"
        print(f" Execution error: {e}")
    
    return state

def _execute_multiline_command(state, command, cwd):
    """Execute multiple commands in sequence"""
    commands = [cmd.strip() for cmd in command.strip().split('\n') if cmd.strip()]
    
    all_stdout = []
    all_stderr = []
    final_return_code = 0
    
    print(f" Executing {len(commands)} commands in sequence:")
    
    for i, cmd in enumerate(commands, 1):
        print(f"  {i}. {cmd}")
        
        try:
            if os.name == 'nt':
                cmd_args = ["powershell", "-NoProfile", "-Command", cmd]
                use_shell = False
            else:
                cmd_args = cmd
                use_shell = True
                
            result = subprocess.run(
                cmd_args,
                shell=use_shell,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Collect outputs
            if result.stdout.strip():
                all_stdout.append(f"Command {i}: {result.stdout.strip()}")
                print(f"     Output: {result.stdout.strip()}")
            
            if result.stderr.strip():
                all_stderr.append(f"Command {i}: {result.stderr.strip()}")
                print(f"      Error: {result.stderr.strip()}")
            
            # If any command fails, note it but continue
            if result.returncode != 0:
                final_return_code = result.returncode
                print(f"     Command {i} failed with return code {result.returncode}")
                # For git commands, we might want to continue even if one fails
                if not cmd.lower().startswith('git'):
                    break
            else:
                print(f"     Command {i} completed successfully")
                
        except subprocess.TimeoutExpired:
            all_stderr.append(f"Command {i} timed out")
            print(f"     Command {i} timed out")
            final_return_code = 1
            break
            
        except Exception as e:
            all_stderr.append(f"Command {i} error: {str(e)}")
            print(f"     Command {i} error: {e}")
            final_return_code = 1
            break
    
    # Combine all outputs
    state["stdout"] = '\n'.join(all_stdout) if all_stdout else ""
    state["stderr"] = '\n'.join(all_stderr) if all_stderr else ""
    state["return_code"] = final_return_code
    state["execution_time"] = time.time()
    
    # Overall status
    if final_return_code == 0:
        state["status"] = "success"
        print(f" All commands completed successfully!")
    else:
        state["status"] = "partial_success" if any("completed successfully" in line.lower() for line in all_stdout) else "error"
        print(f"  Command sequence completed with some issues")
    
    return state

def _handle_cd_command(state, command, current_cwd):
    """
    Handle directory change commands specially
    Since we can't change the actual process cwd, we update our session state
    """
    # Extract target directory from command
    target_dir = _extract_cd_target(command)
    
    if not target_dir:
        state["error"] = "Could not determine target directory"
        return state
    
    # Handle relative paths
    if not os.path.isabs(target_dir):
        target_dir = os.path.join(current_cwd, target_dir)
    
    # Normalize path
    target_dir = os.path.normpath(target_dir)
    
    # Check if directory exists
    if not os.path.exists(target_dir):
        state["error"] = f"Directory does not exist: {target_dir}"
        state["status"] = "error"
        return state
    
    if not os.path.isdir(target_dir):
        state["error"] = f"Path is not a directory: {target_dir}"
        state["status"] = "error"
        return state
    
    # Update session state
    if set_cwd(target_dir):
        state["cwd"] = target_dir
        state["stdout"] = f"Changed directory to: {target_dir}"
        state["status"] = "success"
        state["return_code"] = 0
        print(f" Directory changed to: {target_dir}")
    else:
        state["error"] = f"Failed to change directory to: {target_dir}"
        state["status"] = "error"
    
    return state

def _extract_cd_target(command):
    """Extract target directory from cd command"""
    # Handle various cd command formats
    parts = command.split()
    
    # Find 'cd' and get the next argument
    for i, part in enumerate(parts):
        if part.lower() == 'cd':
            if i + 1 < len(parts):
                return parts[i + 1]
            else:
                return os.path.expanduser("~")  # cd with no args goes home
    
    # If no 'cd' found, assume the whole thing is the target
    return command.strip()

def _confirm_dangerous_command(command):
    """Ask user to confirm dangerous commands"""
    dangerous_patterns = [
        'rm -rf', 'del /s', 'format', 'fdisk', 'mkfs',
        'shutdown', 'reboot', 'halt', 'poweroff'
    ]
    
    is_dangerous = any(pattern in command.lower() for pattern in dangerous_patterns)
    
    if is_dangerous:
        print(f"  DANGEROUS COMMAND DETECTED: {command}")
        response = input("Are you sure you want to execute this? (yes/no): ")
        return response.lower() in ['yes', 'y']
    
    return True

def _handle_git_commit_success(state, result):
    """Handle successful git commit"""
    if result.returncode == 0 and "commit" in state.get("command", "").lower():
        # Extract commit hash if available
        output = result.stdout
        if output:
            lines = output.split('\n')
            for line in lines:
                if 'commit' in line.lower() and len(line) > 10:
                    state["commit_hash"] = line.strip()
                    break
        
        print(" Git commit successful!")

def _is_safe_command(command):
    """Basic safety check for commands"""
    dangerous_patterns = [
        'rm -rf /', 'del /s /q C:\\', 'format c:',
        'shutdown -h now', 'reboot', 'halt',
        'dd if=/dev/zero', 'mkfs', 'fdisk'
    ]
    
    command_lower = command.lower()
    return not any(pattern in command_lower for pattern in dangerous_patterns)