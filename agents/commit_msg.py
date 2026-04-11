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
    Generate intelligent commit messages based on git diff
    """
    cwd = state.get("cwd", "") or os.getcwd()
    command = state.get("command", "") or ""
    prompt = state.get("prompt", "") or ""
    
    # Check if this is a git commit command without a message
    if not _needs_commit_message(command, prompt):
        return state
    
    print(" Analyzing code changes to generate commit message...")
    
    try:
        # First, check if there are any staged changes
        staged_diff = _get_git_diff(cwd, staged=True)
        unstaged_diff = _get_git_diff(cwd, staged=False)
        
        # If no staged changes, check unstaged changes
        if not staged_diff.strip() and unstaged_diff.strip():
            print(" No staged changes found. Staging all changes...")
            # Stage all changes
            stage_result = subprocess.run(
                ["git", "add", "."],
                cwd=cwd,
                capture_output=True,
                text=True
            )
            if stage_result.returncode == 0:
                staged_diff = _get_git_diff(cwd, staged=True)
            else:
                print(f"  Failed to stage changes: {stage_result.stderr}")
        
        if not staged_diff.strip():
            state["error"] = "No changes to commit"
            print(" No changes found to commit")
            return state
        
        # Get git status for additional context
        status_output = _get_git_status(cwd)
        
        # Generate commit message based on diff
        commit_msg = _generate_intelligent_commit_message(staged_diff, status_output, prompt)
        
        if commit_msg:
            # Update the command to include the commit message
            updated_command = _update_command_with_message(command, commit_msg)
            state["command"] = updated_command
            state["generated_commit_msg"] = commit_msg
            print(f" Generated commit message: '{commit_msg}'")
        else:
            # Fallback to a simple message
            fallback_msg = "Update code changes"
            state["command"] = _update_command_with_message(command, fallback_msg)
            state["generated_commit_msg"] = fallback_msg
            print(f" Using fallback commit message: '{fallback_msg}'")
        
    except Exception as e:
        print(f"  Commit message generation error: {e}")
        # Fall back to simple commit without custom message
        fallback_msg = "Code update"
        state["command"] = _update_command_with_message(command, fallback_msg)
        state["generated_commit_msg"] = fallback_msg
    
    return state

def _needs_commit_message(command, prompt):
    """Check if the command needs a commit message generated"""
    command = command or ""
    prompt = prompt or ""
    
    # Check if it's a git commit command
    if "git commit" not in command.lower() and "commit" not in prompt.lower():
        return False
    
    # Check if message is already provided
    has_message = any(flag in command.lower() for flag in ['-m', '--message', '--file', '-F'])
    
    # If no message flag, we need to generate one
    return not has_message

def _get_git_diff(cwd, staged=True):
    """Get git diff output"""
    try:
        if staged:
            # Get staged changes
            result = subprocess.run(
                ["git", "diff", "--cached"],
                cwd=cwd,
                capture_output=True,
                text=True
            )
        else:
            # Get unstaged changes
            result = subprocess.run(
                ["git", "diff"],
                cwd=cwd,
                capture_output=True,
                text=True
            )
        
        if result.returncode == 0:
            return result.stdout
        else:
            print(f"Git diff error: {result.stderr}")
            return ""
            
    except Exception as e:
        print(f"Error getting git diff: {e}")
        return ""

def _get_git_status(cwd):
    """Get git status output"""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""

def _generate_intelligent_commit_message(diff_output, status_output, user_prompt):
    """Generate commit message using OpenAI based on git diff"""
    
    if not diff_output.strip():
        return None
    
    # Parse the diff to understand changes in detail
    analysis = _analyze_diff_content_detailed(diff_output)
    files_changed = _extract_changed_files_from_status(status_output)
    
    # Create a much more detailed and specific prompt for OpenAI
    prompt = f"""You are an expert developer writing commit messages. Analyze this git diff and create a SPECIFIC, detailed commit message that describes exactly what changed.

USER'S INTENT: "{user_prompt}"

FILES CHANGED: {', '.join(files_changed[:3])}{"..." if len(files_changed) > 3 else ""}

DETAILED ANALYSIS:
- Files: {analysis['files_modified']} modified
- Lines: +{analysis['lines_added']} -{analysis['lines_removed']}
- Code patterns detected: {', '.join(analysis['code_patterns'])}
- Functions/classes: {', '.join(analysis['functions_classes'][:3])}
- Key changes: {', '.join(analysis['specific_changes'][:3])}

ACTUAL CODE DIFF:
{diff_output[:2500]}

REQUIREMENTS:
1. Use conventional commit format: type(scope): description
2. Be SPECIFIC about what functionality was added/changed/fixed
3. Mention actual function/class/feature names when possible
4. Keep under 60 characters total
5. Use imperative mood ("add", "fix", "update", not "added", "fixed")

EXAMPLES of GOOD specific messages:
- "feat(auth): add JWT token validation middleware"
- "fix(api): resolve user registration email bug"
- "chore(deps): update axios to v1.4.0"
- "feat(ui): implement dark mode toggle component"
- "refactor(db): extract user queries to separate module"

EXAMPLES of BAD generic messages:
- "update setup.py"
- "fix bug"
- "add feature"
- "code changes"

Generate ONLY the commit message, no quotes or explanations:"""

    try:
        response = openai.ChatCompletion.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # Lower temperature for more consistent results
            max_tokens=60
        )
        
        commit_msg = response['choices'][0]['message']['content'].strip()
        
        # Clean up the message
        commit_msg = _clean_commit_message(commit_msg)
        
        # Validate specificity - reject if too generic
        if _is_too_generic(commit_msg):
            print(f"⚠️  Generated message too generic: '{commit_msg}', using rule-based approach")
            return _generate_specific_rule_based_message(analysis, files_changed, user_prompt)
        
        # Ensure proper length
        if len(commit_msg) > 60:
            commit_msg = commit_msg[:57] + "..."
        
        return commit_msg
        
    except Exception as e:
        print(f"OpenAI API error: {e}")
        # Fallback to enhanced rule-based message
        return _generate_specific_rule_based_message(analysis, files_changed, user_prompt)

def _analyze_diff_content_detailed(diff_output):
    """Enhanced analysis of git diff to extract specific details"""
    lines = diff_output.split('\n')
    
    analysis = {
        'files_modified': 0,
        'lines_added': 0,
        'lines_removed': 0,
        'code_patterns': [],
        'functions_classes': [],
        'specific_changes': [],
        'imports_added': [],
        'imports_removed': [],
        'file_types': set()
    }
    
    current_file = None
    
    for line in lines:
        if line.startswith('diff --git'):
            analysis['files_modified'] += 1
            # Extract filename and type
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].replace('b/', '').split('/')[-1]
                file_ext = current_file.split('.')[-1] if '.' in current_file else 'unknown'
                analysis['file_types'].add(file_ext)
                
        elif line.startswith('+') and not line.startswith('+++'):
            analysis['lines_added'] += 1
            content = line[1:].strip()
            
            # Detect specific patterns in added lines
            if content:
                # Function definitions
                if any(keyword in content for keyword in ['def ', 'function ', 'class ', 'interface ']):
                    func_name = _extract_function_name(content)
                    if func_name:
                        analysis['functions_classes'].append(f"added {func_name}")
                
                # Import statements
                if content.startswith(('import ', 'from ', '#include', 'require(')):
                    analysis['imports_added'].append(content[:50])
                
                # Configuration changes
                if any(keyword in content for keyword in ['=', ':', 'config', 'setting']):
                    if len(content) < 100:  # Only short config lines
                        analysis['specific_changes'].append(f"added {content[:40]}")
                
                # Comments or documentation
                if content.startswith(('#', '//', '/*', '"""', "'''")):
                    analysis['specific_changes'].append("added documentation")
                    
        elif line.startswith('-') and not line.startswith('---'):
            analysis['lines_removed'] += 1
            content = line[1:].strip()
            
            if content:
                # Function removals
                if any(keyword in content for keyword in ['def ', 'function ', 'class ']):
                    func_name = _extract_function_name(content)
                    if func_name:
                        analysis['functions_classes'].append(f"removed {func_name}")
                
                # Import removals
                if content.startswith(('import ', 'from ')):
                    analysis['imports_removed'].append(content[:50])
    
    # Determine code patterns
    if analysis['imports_added']:
        analysis['code_patterns'].append('new dependencies')
    if analysis['imports_removed']:
        analysis['code_patterns'].append('removed dependencies')
    if any('added' in fc for fc in analysis['functions_classes']):
        analysis['code_patterns'].append('new functions')
    if any('removed' in fc for fc in analysis['functions_classes']):
        analysis['code_patterns'].append('removed functions')
    if analysis['lines_added'] > analysis['lines_removed'] * 3:
        analysis['code_patterns'].append('major addition')
    elif analysis['lines_removed'] > analysis['lines_added'] * 3:
        analysis['code_patterns'].append('major cleanup')
    
    return analysis

def _extract_function_name(line):
    """Extract function/class name from code line"""
    line = line.strip()
    
    # Python function
    if line.startswith('def '):
        match = re.search(r'def\s+(\w+)', line)
        return match.group(1) if match else None
    
    # Python class
    if line.startswith('class '):
        match = re.search(r'class\s+(\w+)', line)
        return match.group(1) if match else None
    
    # JavaScript function
    if 'function ' in line:
        match = re.search(r'function\s+(\w+)', line)
        return match.group(1) if match else None
    
    # Arrow function or method
    if '=>' in line or ':' in line:
        match = re.search(r'(\w+)\s*[:=]', line)
        return match.group(1) if match else None
    
    return None

def _is_too_generic(commit_msg):
    """Check if commit message is too generic"""
    generic_patterns = [
        r'^(update|fix|add|change)\s+\w+\.(py|js|txt|md)$',
        r'^(update|fix|add|change)\s+(code|file|files)$',
        r'^(update|fix|add|change)\s+setup\.py$',
        r'^(code|file)\s+(update|change|fix)$',
        r'^(misc|general)\s+',
        r'^(updated?|fixed?|added?|changed?)\s*'
    ]

    msg_lower = commit_msg.lower().strip()
    return any(re.match(pattern, msg_lower) for pattern in generic_patterns)

        

def _analyze_diff_content(diff_output):
    """Analyze git diff to understand the nature of changes"""
    lines = diff_output.split('\n')
    
    analysis = {
        'files_modified': 0,
        'lines_added': 0,
        'lines_removed': 0,
        'change_type': 'modify',
        'change_summary': []
    }
    
    current_file = None
    file_changes = {}
    
    for line in lines:
        if line.startswith('diff --git'):
            analysis['files_modified'] += 1
            # Extract filename
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].split('/')[-1]  # Get just filename
                file_changes[current_file] = {'added': 0, 'removed': 0}
                
        elif line.startswith('+') and not line.startswith('+++'):
            analysis['lines_added'] += 1
            if current_file:
                file_changes[current_file]['added'] += 1
                
        elif line.startswith('-') and not line.startswith('---'):
            analysis['lines_removed'] += 1
            if current_file:
                file_changes[current_file]['removed'] += 1
    
    # Generate change summary
    for filename, changes in file_changes.items():
        if changes['added'] > 0 and changes['removed'] == 0:
            analysis['change_summary'].append(f"Added content to {filename}")
        elif changes['added'] == 0 and changes['removed'] > 0:
            analysis['change_summary'].append(f"Removed content from {filename}")
        else:
            analysis['change_summary'].append(f"Modified {filename}")
    
    # Determine overall change type
    total_added = analysis['lines_added']
    total_removed = analysis['lines_removed']
    
    if total_added > 0 and total_removed == 0:
        analysis['change_type'] = 'add'
    elif total_added == 0 and total_removed > 0:
        analysis['change_type'] = 'remove'
    elif total_added > total_removed * 2:
        analysis['change_type'] = 'feature'
    elif total_removed > total_added * 2:
        analysis['change_type'] = 'cleanup'
    else:
        analysis['change_type'] = 'modify'
    
    return analysis

def _extract_changed_files_from_status(status_output):
    """Extract list of changed files from git status --porcelain"""
    files = []
    for line in status_output.split('\n'):
        if line.strip() and len(line) > 3:
            # Git status --porcelain format: XY filename
            filename = line[3:].strip()
            if filename:
                files.append(filename)
    return files

def _generate_rule_based_commit_message(analysis, files_changed, user_prompt):
    """Generate commit message using rules when AI fails"""
    
    # Extract intent from user prompt
    prompt_lower = user_prompt.lower()
    
    # Determine prefix based on changes and intent
    if any('bug' in word or 'fix' in word for word in prompt_lower.split()):
        prefix = "fix"
    elif any('new' in word or 'add' in word or 'create' in word for word in prompt_lower.split()):
        prefix = "feat"
    elif any('doc' in word or 'readme' in word for word in prompt_lower.split()):
        prefix = "docs"
    elif any('test' in word for word in prompt_lower.split()):
        prefix = "test"
    elif 'setup.py' in files_changed or 'requirements.txt' in files_changed:
        prefix = "chore"
    elif analysis['code_patterns']:
        if 'new functions' in analysis['code_patterns']:
            prefix = "feat"
        elif 'major cleanup' in analysis['code_patterns']:
            prefix = "refactor"
        else:
            prefix = "feat"
    else:
        prefix = "chore"
    
    # Generate specific description
    if analysis['functions_classes']:
        # Use actual function/class names
        main_change = analysis['functions_classes'][0]
        if len(files_changed) == 1:
            scope = files_changed[0].replace('.py', '').replace('.js', '')
            description = main_change.replace('added ', '').replace('removed ', '')
            return f"{prefix}({scope}): {main_change}"
        else:
            return f"{prefix}: {main_change} in {len(files_changed)} files"
    
    elif analysis['imports_added']:
        # Mention specific imports
        import_name = analysis['imports_added'][0].split()[-1].replace(',', '')
        return f"{prefix}: add {import_name} dependency"
    
    elif len(files_changed) == 1:
        # Single file - be specific about the file
        filename = files_changed[0]
        if filename == 'setup.py':
            return f"{prefix}: update package configuration"
        elif filename == 'requirements.txt':
            return f"{prefix}: update dependencies"
        elif filename.endswith('.md'):
            return f"docs: update {filename.replace('.md', '')} documentation"
        elif filename.endswith(('.py', '.js', '.ts')):
            module_name = filename.split('.')[0]
            return f"{prefix}({module_name}): enhance functionality"
        else:
            return f"{prefix}: update {filename}"
    
    else:
        # Multiple files
        file_types = list(analysis['file_types'])
        if len(file_types) == 1:
            return f"{prefix}: update {file_types[0]} files"
        else:
            return f"{prefix}: update {len(files_changed)} files"

def _clean_commit_message(message):
    """Clean up commit message"""
    # Remove quotes
    message = message.replace('"', '').replace("'", "")
    
    # Remove common prefixes that might be added
    message = re.sub(r'^(commit message:|message:)\s*', '', message, flags=re.IGNORECASE)
    
    # Ensure first letter is lowercase (except for proper nouns)
    if message and not message[0].isupper():
        message = message[0].lower() + message[1:]
    
    return message.strip()

def _update_command_with_message(command, commit_msg):
    """Update git command to include the commit message"""
    command = command.strip()
    
    # Escape the commit message for shell
    escaped_msg = commit_msg.replace('"', '\\"').replace("'", "\\'")
    
    if "git commit" in command.lower():
        # Add -m flag if not present
        if "-m" not in command.lower() and "--message" not in command.lower():
            command = command + f' -m "{escaped_msg}"'
        else:
            # Replace existing message
            command = re.sub(r'-m\s+"[^"]*"', f'-m "{escaped_msg}"', command)
            command = re.sub(r"-m\s+'[^']*'", f'-m "{escaped_msg}"', command)
    else:
        # If it's just "commit", make it a full git commit command
        if command.lower() == "commit":
            command = f'git commit -m "{escaped_msg}"'
        else:
            command = f'{command} -m "{escaped_msg}"'
    
    return command,  # "update file.py"


def _analyze_diff_content(diff_output):
    """Analyze git diff to understand the nature of changes"""
    lines = diff_output.split('\n')
    
    analysis = {
        'files_modified': 0,
        'lines_added': 0,
        'lines_removed': 0,
        'change_type': 'modify',
        'change_summary': []
    }
    
    current_file = None
    file_changes = {}
    
    for line in lines:
        if line.startswith('diff --git'):
            analysis['files_modified'] += 1
            # Extract filename
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].split('/')[-1]  # Get just filename
                file_changes[current_file] = {'added': 0, 'removed': 0}
                
        elif line.startswith('+') and not line.startswith('+++'):
            analysis['lines_added'] += 1
            if current_file:
                file_changes[current_file]['added'] += 1
                
        elif line.startswith('-') and not line.startswith('---'):
            analysis['lines_removed'] += 1
            if current_file:
                file_changes[current_file]['removed'] += 1
    
    # Generate change summary
    for filename, changes in file_changes.items():
        if changes['added'] > 0 and changes['removed'] == 0:
            analysis['change_summary'].append(f"Added content to {filename}")
        elif changes['added'] == 0 and changes['removed'] > 0:
            analysis['change_summary'].append(f"Removed content from {filename}")
        else:
            analysis['change_summary'].append(f"Modified {filename}")
    
    # Determine overall change type
    total_added = analysis['lines_added']
    total_removed = analysis['lines_removed']
    
    if total_added > 0 and total_removed == 0:
        analysis['change_type'] = 'add'
    elif total_added == 0 and total_removed > 0:
        analysis['change_type'] = 'remove'
    elif total_added > total_removed * 2:
        analysis['change_type'] = 'feature'
    elif total_removed > total_added * 2:
        analysis['change_type'] = 'cleanup'
    else:
        analysis['change_type'] = 'modify'
    
    return analysis

def _extract_changed_files_from_status(status_output):
    """Extract list of changed files from git status --porcelain"""
    files = []
    for line in status_output.split('\n'):
        if line.strip() and len(line) > 3:
            # Git status --porcelain format: XY filename
            filename = line[3:].strip()
            if filename:
                files.append(filename)
    return files

def _generate_rule_based_commit_message(analysis, files_changed, user_prompt):
    """Generate commit message using rules when AI fails"""
    change_type = analysis['change_type']
    file_count = analysis['files_modified']
    
    # Try to infer from user prompt
    prompt_lower = user_prompt.lower()
    
    if 'fix' in prompt_lower or 'bug' in prompt_lower:
        prefix = "fix:"
    elif 'add' in prompt_lower or 'new' in prompt_lower or 'create' in prompt_lower:
        prefix = "feat:"
    elif 'update' in prompt_lower or 'change' in prompt_lower:
        prefix = "chore:"
    elif 'doc' in prompt_lower or 'readme' in prompt_lower:
        prefix = "docs:"
    elif 'test' in prompt_lower:
        prefix = "test:"
    else:
        # Use analysis to determine prefix
        if change_type == 'add' or change_type == 'feature':
            prefix = "feat:"
        elif 'fix' in ' '.join(analysis['change_summary']).lower():
            prefix = "fix:"
        else:
            prefix = "chore:"
    
    # Generate main message
    if file_count == 1 and files_changed:
        main_msg = f"update {files_changed[0]}"
    elif file_count <= 3:
        main_msg = f"update {file_count} files"
    else:
        main_msg = "update multiple files"
    
    return f"{prefix} {main_msg}"

def _clean_commit_message(message):
    """Clean up commit message"""
    # Remove quotes
    message = message.replace('"', '').replace("'", "")
    
    # Remove common prefixes that might be added
    message = re.sub(r'^(commit message:|message:)\s*', '', message, flags=re.IGNORECASE)
    
    # Ensure first letter is lowercase (except for proper nouns)
    if message and not message[0].isupper():
        message = message[0].lower() + message[1:]
    
    return message.strip()

def _update_command_with_message(command, commit_msg):
    """Update git command to include the commit message"""
    command = command.strip()
    
    # Escape the commit message for shell
    escaped_msg = commit_msg.replace('"', '\\"').replace("'", "\\'")
    
    if "git commit" in command.lower():
        # Add -m flag if not present
        if "-m" not in command.lower() and "--message" not in command.lower():
            command = command + f' -m "{escaped_msg}"'
        else:
            # Replace existing message
            command = re.sub(r'-m\s+"[^"]*"', f'-m "{escaped_msg}"', command)
            command = re.sub(r"-m\s+'[^']*'", f'-m "{escaped_msg}"', command)
    else:
        # If it's just "commit", make it a full git commit command
        if command.lower() == "commit":
            command = f'git commit -m "{escaped_msg}"'
        else:
            command = f'{command} -m "{escaped_msg}"'
    
    return command,    # "update code"


def _analyze_diff_content(diff_output):
    """Analyze git diff to understand the nature of changes"""
    lines = diff_output.split('\n')
    
    analysis = {
        'files_modified': 0,
        'lines_added': 0,
        'lines_removed': 0,
        'change_type': 'modify',
        'change_summary': []
    }
    
    current_file = None
    file_changes = {}
    
    for line in lines:
        if line.startswith('diff --git'):
            analysis['files_modified'] += 1
            # Extract filename
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].split('/')[-1]  # Get just filename
                file_changes[current_file] = {'added': 0, 'removed': 0}
                
        elif line.startswith('+') and not line.startswith('+++'):
            analysis['lines_added'] += 1
            if current_file:
                file_changes[current_file]['added'] += 1
                
        elif line.startswith('-') and not line.startswith('---'):
            analysis['lines_removed'] += 1
            if current_file:
                file_changes[current_file]['removed'] += 1
    
    # Generate change summary
    for filename, changes in file_changes.items():
        if changes['added'] > 0 and changes['removed'] == 0:
            analysis['change_summary'].append(f"Added content to {filename}")
        elif changes['added'] == 0 and changes['removed'] > 0:
            analysis['change_summary'].append(f"Removed content from {filename}")
        else:
            analysis['change_summary'].append(f"Modified {filename}")
    
    # Determine overall change type
    total_added = analysis['lines_added']
    total_removed = analysis['lines_removed']
    
    if total_added > 0 and total_removed == 0:
        analysis['change_type'] = 'add'
    elif total_added == 0 and total_removed > 0:
        analysis['change_type'] = 'remove'
    elif total_added > total_removed * 2:
        analysis['change_type'] = 'feature'
    elif total_removed > total_added * 2:
        analysis['change_type'] = 'cleanup'
    else:
        analysis['change_type'] = 'modify'
    
    return analysis

def _extract_changed_files_from_status(status_output):
    """Extract list of changed files from git status --porcelain"""
    files = []
    for line in status_output.split('\n'):
        if line.strip() and len(line) > 3:
            # Git status --porcelain format: XY filename
            filename = line[3:].strip()
            if filename:
                files.append(filename)
    return files

def _generate_rule_based_commit_message(analysis, files_changed, user_prompt):
    """Generate commit message using rules when AI fails"""
    change_type = analysis['change_type']
    file_count = analysis['files_modified']
    
    # Try to infer from user prompt
    prompt_lower = user_prompt.lower()
    
    if 'fix' in prompt_lower or 'bug' in prompt_lower:
        prefix = "fix:"
    elif 'add' in prompt_lower or 'new' in prompt_lower or 'create' in prompt_lower:
        prefix = "feat:"
    elif 'update' in prompt_lower or 'change' in prompt_lower:
        prefix = "chore:"
    elif 'doc' in prompt_lower or 'readme' in prompt_lower:
        prefix = "docs:"
    elif 'test' in prompt_lower:
        prefix = "test:"
    else:
        # Use analysis to determine prefix
        if change_type == 'add' or change_type == 'feature':
            prefix = "feat:"
        elif 'fix' in ' '.join(analysis['change_summary']).lower():
            prefix = "fix:"
        else:
            prefix = "chore:"
    
    # Generate main message
    if file_count == 1 and files_changed:
        main_msg = f"update {files_changed[0]}"
    elif file_count <= 3:
        main_msg = f"update {file_count} files"
    else:
        main_msg = "update multiple files"
    
    return f"{prefix} {main_msg}"

def _clean_commit_message(message):
    """Clean up commit message"""
    # Remove quotes
    message = message.replace('"', '').replace("'", "")
    
    # Remove common prefixes that might be added
    message = re.sub(r'^(commit message:|message:)\s*', '', message, flags=re.IGNORECASE)
    
    # Ensure first letter is lowercase (except for proper nouns)
    if message and not message[0].isupper():
        message = message[0].lower() + message[1:]
    
    return message.strip()

def _update_command_with_message(command, commit_msg):
    """Update git command to include the commit message"""
    command = command.strip()
    
    # Escape the commit message for shell
    escaped_msg = commit_msg.replace('"', '\\"').replace("'", "\\'")
    
    if "git commit" in command.lower():
        # Add -m flag if not present
        if "-m" not in command.lower() and "--message" not in command.lower():
            command = command + f' -m "{escaped_msg}"'
        else:
            # Replace existing message
            command = re.sub(r'-m\s+"[^"]*"', f'-m "{escaped_msg}"', command)
            command = re.sub(r"-m\s+'[^']*'", f'-m "{escaped_msg}"', command)
    else:
        # If it's just "commit", make it a full git commit command
        if command.lower() == "commit":
            command = f'git commit -m "{escaped_msg}"'
        else:
            command = f'{command} -m "{escaped_msg}"'
    
    return command

def _analyze_diff_content(diff_output):
    """Analyze git diff to understand the nature of changes"""
    lines = diff_output.split('\n')
    
    analysis = {
        'files_modified': 0,
        'lines_added': 0,
        'lines_removed': 0,
        'change_type': 'modify',
        'change_summary': []
    }
    
    current_file = None
    file_changes = {}
    
    for line in lines:
        if line.startswith('diff --git'):
            analysis['files_modified'] += 1
            # Extract filename
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].split('/')[-1]  # Get just filename
                file_changes[current_file] = {'added': 0, 'removed': 0}
                
        elif line.startswith('+') and not line.startswith('+++'):
            analysis['lines_added'] += 1
            if current_file:
                file_changes[current_file]['added'] += 1
                
        elif line.startswith('-') and not line.startswith('---'):
            analysis['lines_removed'] += 1
            if current_file:
                file_changes[current_file]['removed'] += 1
    
    # Generate change summary
    for filename, changes in file_changes.items():
        if changes['added'] > 0 and changes['removed'] == 0:
            analysis['change_summary'].append(f"Added content to {filename}")
        elif changes['added'] == 0 and changes['removed'] > 0:
            analysis['change_summary'].append(f"Removed content from {filename}")
        else:
            analysis['change_summary'].append(f"Modified {filename}")
    
    # Determine overall change type
    total_added = analysis['lines_added']
    total_removed = analysis['lines_removed']
    
    if total_added > 0 and total_removed == 0:
        analysis['change_type'] = 'add'
    elif total_added == 0 and total_removed > 0:
        analysis['change_type'] = 'remove'
    elif total_added > total_removed * 2:
        analysis['change_type'] = 'feature'
    elif total_removed > total_added * 2:
        analysis['change_type'] = 'cleanup'
    else:
        analysis['change_type'] = 'modify'
    
    return analysis

def _extract_changed_files_from_status(status_output):
    """Extract list of changed files from git status --porcelain"""
    files = []
    for line in status_output.split('\n'):
        if line.strip() and len(line) > 3:
            # Git status --porcelain format: XY filename
            filename = line[3:].strip()
            if filename:
                files.append(filename)
    return files

def _generate_rule_based_commit_message(analysis, files_changed, user_prompt):
    """Generate commit message using rules when AI fails"""
    change_type = analysis['change_type']
    file_count = analysis['files_modified']
    
    # Try to infer from user prompt
    prompt_lower = user_prompt.lower()
    
    if 'fix' in prompt_lower or 'bug' in prompt_lower:
        prefix = "fix:"
    elif 'add' in prompt_lower or 'new' in prompt_lower or 'create' in prompt_lower:
        prefix = "feat:"
    elif 'update' in prompt_lower or 'change' in prompt_lower:
        prefix = "chore:"
    elif 'doc' in prompt_lower or 'readme' in prompt_lower:
        prefix = "docs:"
    elif 'test' in prompt_lower:
        prefix = "test:"
    else:
        # Use analysis to determine prefix
        if change_type == 'add' or change_type == 'feature':
            prefix = "feat:"
        elif 'fix' in ' '.join(analysis['change_summary']).lower():
            prefix = "fix:"
        else:
            prefix = "chore:"
    
    # Generate main message
    if file_count == 1 and files_changed:
        main_msg = f"update {files_changed[0]}"
    elif file_count <= 3:
        main_msg = f"update {file_count} files"
    else:
        main_msg = "update multiple files"
    
    return f"{prefix} {main_msg}"

def _clean_commit_message(message):
    """Clean up commit message"""
    # Remove quotes
    message = message.replace('"', '').replace("'", "")
    
    # Remove common prefixes that might be added
    message = re.sub(r'^(commit message:|message:)\s*', '', message, flags=re.IGNORECASE)
    
    # Ensure first letter is lowercase (except for proper nouns)
    if message and not message[0].isupper():
        message = message[0].lower() + message[1:]
    
    return message.strip()

def _update_command_with_message(command, commit_msg):
    """Update git command to include the commit message"""
    command = command.strip()
    
    # Escape the commit message for shell
    escaped_msg = commit_msg.replace('"', '\\"').replace("'", "\\'")
    
    if "git commit" in command.lower():
        # Add -m flag if not present
        if "-m" not in command.lower() and "--message" not in command.lower():
            command = command + f' -m "{escaped_msg}"'
        else:
            # Replace existing message
            command = re.sub(r'-m\s+"[^"]*"', f'-m "{escaped_msg}"', command)
            command = re.sub(r"-m\s+'[^']*'", f'-m "{escaped_msg}"', command)
    else:
        # If it's just "commit", make it a full git commit command
        if command.lower() == "commit":
            command = f'git commit -m "{escaped_msg}"'
        else:
            command = f'{command} -m "{escaped_msg}"'
    
    return command

def _analyze_diff_content(diff_output):
    """Analyze git diff to understand the nature of changes"""
    lines = diff_output.split('\n')
    
    analysis = {
        'files_modified': 0,
        'lines_added': 0,
        'lines_removed': 0,
        'change_type': 'modify',
        'change_summary': []
    }
    
    current_file = None
    file_changes = {}
    
    for line in lines:
        if line.startswith('diff --git'):
            analysis['files_modified'] += 1
            # Extract filename
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].split('/')[-1]  # Get just filename
                file_changes[current_file] = {'added': 0, 'removed': 0}
                
        elif line.startswith('+') and not line.startswith('+++'):
            analysis['lines_added'] += 1
            if current_file:
                file_changes[current_file]['added'] += 1
                
        elif line.startswith('-') and not line.startswith('---'):
            analysis['lines_removed'] += 1
            if current_file:
                file_changes[current_file]['removed'] += 1
    
    # Generate change summary
    for filename, changes in file_changes.items():
        if changes['added'] > 0 and changes['removed'] == 0:
            analysis['change_summary'].append(f"Added content to {filename}")
        elif changes['added'] == 0 and changes['removed'] > 0:
            analysis['change_summary'].append(f"Removed content from {filename}")
        else:
            analysis['change_summary'].append(f"Modified {filename}")
    
    # Determine overall change type
    total_added = analysis['lines_added']
    total_removed = analysis['lines_removed']
    
    if total_added > 0 and total_removed == 0:
        analysis['change_type'] = 'add'
    elif total_added == 0 and total_removed > 0:
        analysis['change_type'] = 'remove'
    elif total_added > total_removed * 2:
        analysis['change_type'] = 'feature'
    elif total_removed > total_added * 2:
        analysis['change_type'] = 'cleanup'
    else:
        analysis['change_type'] = 'modify'
    
    return analysis

def _extract_changed_files_from_status(status_output):
    """Extract list of changed files from git status --porcelain"""
    files = []
    for line in status_output.split('\n'):
        if line.strip() and len(line) > 3:
            # Git status --porcelain format: XY filename
            filename = line[3:].strip()
            if filename:
                files.append(filename)
    return files

def _generate_rule_based_commit_message(analysis, files_changed, user_prompt):
    """Generate commit message using rules when AI fails"""
    change_type = analysis['change_type']
    file_count = analysis['files_modified']
    
    # Try to infer from user prompt
    prompt_lower = user_prompt.lower()
    
    if 'fix' in prompt_lower or 'bug' in prompt_lower:
        prefix = "fix:"
    elif 'add' in prompt_lower or 'new' in prompt_lower or 'create' in prompt_lower:
        prefix = "feat:"
    elif 'update' in prompt_lower or 'change' in prompt_lower:
        prefix = "chore:"
    elif 'doc' in prompt_lower or 'readme' in prompt_lower:
        prefix = "docs:"
    elif 'test' in prompt_lower:
        prefix = "test:"
    else:
        # Use analysis to determine prefix
        if change_type == 'add' or change_type == 'feature':
            prefix = "feat:"
        elif 'fix' in ' '.join(analysis['change_summary']).lower():
            prefix = "fix:"
        else:
            prefix = "chore:"
    
    # Generate main message
    if file_count == 1 and files_changed:
        main_msg = f"update {files_changed[0]}"
    elif file_count <= 3:
        main_msg = f"update {file_count} files"
    else:
        main_msg = "update multiple files"
    
    return f"{prefix} {main_msg}"

def _clean_commit_message(message):
    """Clean up commit message"""
    # Remove quotes
    message = message.replace('"', '').replace("'", "")
    
    # Remove common prefixes that might be added
    message = re.sub(r'^(commit message:|message:)\s*', '', message, flags=re.IGNORECASE)
    
    # Ensure first letter is lowercase (except for proper nouns)
    if message and not message[0].isupper():
        message = message[0].lower() + message[1:]
    
    return message.strip()

def _update_command_with_message(command, commit_msg):
    """Update git command to include the commit message"""
    command = command.strip()
    
    # Escape the commit message for shell
    escaped_msg = commit_msg.replace('"', '\\"').replace("'", "\\'")
    
    if "git commit" in command.lower():
        # Add -m flag if not present
        if "-m" not in command.lower() and "--message" not in command.lower():
            command = command + f' -m "{escaped_msg}"'
        else:
            # Replace existing message
            command = re.sub(r'-m\s+"[^"]*"', f'-m "{escaped_msg}"', command)
            command = re.sub(r"-m\s+'[^']*'", f'-m "{escaped_msg}"', command)
    else:
        # If it's just "commit", make it a full git commit command
        if command.lower() == "commit":
            command = f'git commit -m "{escaped_msg}"'
        else:
            command = f'{command} -m "{escaped_msg}"'
    
    return command
    
    msg_lower = commit_msg.lower()
    return any(re.match(pattern, msg_lower) for pattern in generic_patterns)

def _generate_specific_rule_based_message(analysis, files_changed, user_prompt):
    """Generate specific commit message using rules when AI fails"""
    
    # Extract intent from user prompt
    prompt_lower = user_prompt.lower()
    
    # Determine prefix based on changes and intent
    if any('bug' in word or 'fix' in word for word in prompt_lower.split()):
        prefix = "fix"
    elif any('new' in word or 'add' in word or 'create' in word for word in prompt_lower.split()):
        prefix = "feat"
    elif any('doc' in word or 'readme' in word for word in prompt_lower.split()):
        prefix = "docs"
    elif any('test' in word for word in prompt_lower.split()):
        prefix = "test"
    elif 'setup.py' in files_changed or 'requirements.txt' in files_changed:
        prefix = "chore"
    elif analysis['code_patterns']:
        if 'new functions' in analysis['code_patterns']:
            prefix = "feat"
        elif 'major cleanup' in analysis['code_patterns']:
            prefix = "refactor"
        else:
            prefix = "feat"
    else:
        prefix = "chore"
    
    # Generate specific description
    if analysis['functions_classes']:
        # Use actual function/class names
        main_change = analysis['functions_classes'][0]
        if len(files_changed) == 1:
            scope = files_changed[0].replace('.py', '').replace('.js', '')
            description = main_change.replace('added ', '').replace('removed ', '')
            return f"{prefix}({scope}): {main_change}"
        else:
            return f"{prefix}: {main_change} in {len(files_changed)} files"
    
    elif analysis['imports_added']:
        # Mention specific imports
        import_name = analysis['imports_added'][0].split()[-1].replace(',', '')
        return f"{prefix}: add {import_name} dependency"
    
    elif len(files_changed) == 1:
        # Single file - be specific about the file
        filename = files_changed[0]
        if filename == 'setup.py':
            return f"{prefix}: update package configuration"
        elif filename == 'requirements.txt':
            return f"{prefix}: update dependencies"
        elif filename.endswith('.md'):
            return f"docs: update {filename.replace('.md', '')} documentation"
        elif filename.endswith(('.py', '.js', '.ts')):
            module_name = filename.split('.')[0]
            return f"{prefix}({module_name}): enhance functionality"
        else:
            return f"{prefix}: update {filename}"
    
    else:
        # Multiple files
        file_types = list(analysis['file_types'])
        if len(file_types) == 1:
            return f"{prefix}: update {file_types[0]} files"
        else:
            return f"{prefix}: update {len(files_changed)} files"

def _analyze_diff_content(diff_output):
    """Analyze git diff to understand the nature of changes"""
    lines = diff_output.split('\n')
    
    analysis = {
        'files_modified': 0,
        'lines_added': 0,
        'lines_removed': 0,
        'change_type': 'modify',
        'change_summary': []
    }
    
    current_file = None
    file_changes = {}
    
    for line in lines:
        if line.startswith('diff --git'):
            analysis['files_modified'] += 1
            # Extract filename
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].split('/')[-1]  # Get just filename
                file_changes[current_file] = {'added': 0, 'removed': 0}
                
        elif line.startswith('+') and not line.startswith('+++'):
            analysis['lines_added'] += 1
            if current_file:
                file_changes[current_file]['added'] += 1
                
        elif line.startswith('-') and not line.startswith('---'):
            analysis['lines_removed'] += 1
            if current_file:
                file_changes[current_file]['removed'] += 1
    
    # Generate change summary
    for filename, changes in file_changes.items():
        if changes['added'] > 0 and changes['removed'] == 0:
            analysis['change_summary'].append(f"Added content to {filename}")
        elif changes['added'] == 0 and changes['removed'] > 0:
            analysis['change_summary'].append(f"Removed content from {filename}")
        else:
            analysis['change_summary'].append(f"Modified {filename}")
    
    # Determine overall change type
    total_added = analysis['lines_added']
    total_removed = analysis['lines_removed']
    
    if total_added > 0 and total_removed == 0:
        analysis['change_type'] = 'add'
    elif total_added == 0 and total_removed > 0:
        analysis['change_type'] = 'remove'
    elif total_added > total_removed * 2:
        analysis['change_type'] = 'feature'
    elif total_removed > total_added * 2:
        analysis['change_type'] = 'cleanup'
    else:
        analysis['change_type'] = 'modify'
    
    return analysis

def _extract_changed_files_from_status(status_output):
    """Extract list of changed files from git status --porcelain"""
    files = []
    for line in status_output.split('\n'):
        if line.strip() and len(line) > 3:
            # Git status --porcelain format: XY filename
            filename = line[3:].strip()
            if filename:
                files.append(filename)
    return files

def _generate_rule_based_commit_message(analysis, files_changed, user_prompt):
    """Generate commit message using rules when AI fails"""
    change_type = analysis['change_type']
    file_count = analysis['files_modified']
    
    # Try to infer from user prompt
    prompt_lower = user_prompt.lower()
    
    if 'fix' in prompt_lower or 'bug' in prompt_lower:
        prefix = "fix:"
    elif 'add' in prompt_lower or 'new' in prompt_lower or 'create' in prompt_lower:
        prefix = "feat:"
    elif 'update' in prompt_lower or 'change' in prompt_lower:
        prefix = "chore:"
    elif 'doc' in prompt_lower or 'readme' in prompt_lower:
        prefix = "docs:"
    elif 'test' in prompt_lower:
        prefix = "test:"
    else:
        # Use analysis to determine prefix
        if change_type == 'add' or change_type == 'feature':
            prefix = "feat:"
        elif 'fix' in ' '.join(analysis['change_summary']).lower():
            prefix = "fix:"
        else:
            prefix = "chore:"
    
    # Generate main message
    if file_count == 1 and files_changed:
        main_msg = f"update {files_changed[0]}"
    elif file_count <= 3:
        main_msg = f"update {file_count} files"
    else:
        main_msg = "update multiple files"
    
    return f"{prefix} {main_msg}"

def _clean_commit_message(message):
    """Clean up commit message"""
    # Remove quotes
    message = message.replace('"', '').replace("'", "")
    
    # Remove common prefixes that might be added
    message = re.sub(r'^(commit message:|message:)\s*', '', message, flags=re.IGNORECASE)
    
    # Ensure first letter is lowercase (except for proper nouns)
    if message and not message[0].isupper():
        message = message[0].lower() + message[1:]
    
    return message.strip()

def _update_command_with_message(command, commit_msg):
    """Update git command to include the commit message"""
    command = command.strip()
    
    # Escape the commit message for shell
    escaped_msg = commit_msg.replace('"', '\\"').replace("'", "\\'")
    
    if "git commit" in command.lower():
        # Add -m flag if not present
        if "-m" not in command.lower() and "--message" not in command.lower():
            command = command + f' -m "{escaped_msg}"'
        else:
            # Replace existing message
            command = re.sub(r'-m\s+"[^"]*"', f'-m "{escaped_msg}"', command)
            command = re.sub(r"-m\s+'[^']*'", f'-m "{escaped_msg}"', command)
    else:
        # If it's just "commit", make it a full git commit command
        if command.lower() == "commit":
            command = f'git commit -m "{escaped_msg}"'
        else:
            command = f'{command} -m "{escaped_msg}"'
    
    return command