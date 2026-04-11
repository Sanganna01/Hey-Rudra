import re
import os
import subprocess

def verifier_agent(state):
    """
    Verify command safety before execution
    """
    command = state.get("command", "")
    risk_level = state.get("risk_level", "safe")
    cwd = state.get("cwd", os.getcwd())
    
    if not command:
        state["verification_error"] = "No command to verify"
        return state
    
    # Perform safety checks
    safety_result = _check_command_safety(command, cwd)
    
    state["verification_result"] = safety_result
    state["safety_score"] = safety_result["score"]
    state["safety_warnings"] = safety_result["warnings"]
    
    # Check if command should be blocked
    if safety_result["score"] < 30:  # Very dangerous
        state["verification_error"] = f"Command blocked: {safety_result['reason']}"
        state["status"] = "blocked"
        print(f"🚫 Command blocked: {safety_result['reason']}")
        return state
    
    # Check for syntax errors (where possible)
    syntax_check = _check_syntax(command)
    if not syntax_check["valid"]:
        state["verification_error"] = f"Syntax error: {syntax_check['error']}"
        state["status"] = "syntax_error"
        print(f"❌ Syntax error: {syntax_check['error']}")
        return state
    
    # Warnings for moderate risk commands
    if safety_result["score"] < 70:
        print(f"⚠️  Safety warnings: {', '.join(safety_result['warnings'])}")
        if not _confirm_risky_command(command, safety_result["warnings"]):
            state["verification_error"] = "Command execution cancelled by user"
            state["status"] = "cancelled"
            return state
    
    # Command passed verification
    state["verification_passed"] = True
    state["status"] = "verified"
    print(f"✅ Command verified (safety score: {safety_result['score']}/100)")
    
    return state

def _check_command_safety(command, cwd):
    """
    Comprehensive safety check for commands
    Returns safety score (0-100) and warnings
    """
    score = 100
    warnings = []
    reason = ""
    
    command_lower = command.lower()
    
    # Critical danger patterns (block immediately)
    critical_patterns = [
        (r'\brm\s+-rf\s+/', "Attempting to delete root directory"),
        (r'\bformat\s+c:', "Attempting to format system drive"),
        (r'\bdel\s+/s\s+/q\s+c:\\', "Attempting to delete system files"),
        (r'\bdd\s+if=/dev/zero\s+of=/dev/', "Attempting to overwrite disk"),
        (r'\bmkfs\b', "Attempting to format filesystem"),
        (r'\bfdisk\b.*\b/dev/', "Attempting to modify disk partitions"),
    ]
    
    for pattern, description in critical_patterns:
        if re.search(pattern, command_lower):
            return {
                "score": 0,
                "warnings": [description],
                "reason": description,
                "blocked": True
            }
    
    # High risk patterns
    high_risk_patterns = [
        (r'\brm\s+-rf', "Recursive deletion", 30),
        (r'\bshutdown\b', "System shutdown", 40),
        (r'\breboot\b', "System reboot", 40),
        (r'\bhalt\b', "System halt", 40),
        (r'\bkillall\b', "Killing all processes", 35),
        (r'\bsudo\s+rm', "Root deletion", 25),
        (r'\bchmod\s+777', "Overly permissive permissions", 50),
    ]
    
    for pattern, description, penalty in high_risk_patterns:
        if re.search(pattern, command_lower):
            score -= penalty
            warnings.append(description)
    
    # Medium risk patterns
    medium_risk_patterns = [
        (r'\bsudo\b', "Running as root", 15),
        (r'\brm\b', "File deletion", 10),
        (r'\bmv\b.*\s+/', "Moving to root", 20),
        (r'\bcp\b.*\s+/', "Copying to root", 15),
        (r'\bchmod\b', "Changing permissions", 10),
        (r'\bchown\b', "Changing ownership", 10),
    ]
    
    for pattern, description, penalty in medium_risk_patterns:
        if re.search(pattern, command_lower):
            score -= penalty
            warnings.append(description)
    
    # Check for suspicious file operations in system directories
    system_dirs = ['/bin', '/sbin', '/usr', '/etc', '/boot', '/sys', '/proc']
    for sys_dir in system_dirs:
        if sys_dir in command:
            score -= 20
            warnings.append(f"Operating on system directory: {sys_dir}")
    
    # Check for network operations that might be risky
    network_patterns = [
        (r'\bcurl\b.*\|\s*sh', "Downloading and executing script", 30),
        (r'\bwget\b.*\|\s*sh', "Downloading and executing script", 30),
        (r'\bnc\b.*-e', "Netcat with command execution", 25),
    ]
    
    for pattern, description, penalty in network_patterns:
        if re.search(pattern, command_lower):
            score -= penalty
            warnings.append(description)
    
    return {
        "score": max(0, score),
        "warnings": warnings,
        "reason": warnings[0] if warnings else "",
        "blocked": score <= 0
    }

def _check_syntax(command):
    """
    Basic syntax checking for common command patterns
    """
    try:
        # Check for balanced quotes
        single_quotes = command.count("'")
        double_quotes = command.count('"')
        
        if single_quotes % 2 != 0:
            return {"valid": False, "error": "Unmatched single quote"}
        
        if double_quotes % 2 != 0:
            return {"valid": False, "error": "Unmatched double quote"}
        
        # Check for balanced parentheses
        paren_count = 0
        for char in command:
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
                if paren_count < 0:
                    return {"valid": False, "error": "Unmatched closing parenthesis"}
        
        if paren_count != 0:
            return {"valid": False, "error": "Unmatched opening parenthesis"}
        
        # Check for some common syntax errors
        if re.search(r'&&\s*$', command):
            return {"valid": False, "error": "Command ends with &&"}
        
        if re.search(r'\|\s*$', command):
            return {"valid": False, "error": "Command ends with pipe"}
        
        return {"valid": True, "error": None}
        
    except Exception as e:
        return {"valid": False, "error": f"Syntax check failed: {e}"}

def _confirm_risky_command(command, warnings):
    """Ask user to confirm risky commands"""
    print(f"\n⚠️  RISKY COMMAND DETECTED:")
    print(f"Command: {command}")
    print(f"Warnings: {', '.join(warnings)}")
    
    try:
        response = input("\nDo you want to proceed? (yes/no): ").strip().lower()
        return response in ['yes', 'y']
    except (EOFError, KeyboardInterrupt):
        return False