"""
file_writer.py
==============
Handles file write/create operations:
  1. Generates content with the LLM
  2. Writes directly via Python (no PowerShell — avoids multiline escaping issues)
  3. Records the action in the HeyRudra history store for future revert
"""

import openai
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from session_context import get_api_key
from history.history_store import record_event, create_group

openai.api_key = get_api_key()
openai.api_base = "https://api.groq.com/openai/v1"


# ─── Agent entry-point ────────────────────────────────────────────────────────

def file_writer_agent(state: dict) -> dict:
    """
    Generates file content via LLM and writes it directly with Python.
    Records before/after state for the revert engine.
    """
    prompt = state.get("prompt", "") or ""
    cwd = state.get("cwd", "") or os.getcwd()

    filename = _extract_filename(prompt)
    if not filename:
        state["error"] = "Could not determine the target filename from your request."
        state["status"] = "error"
        return state

    filepath = os.path.join(cwd, filename)

    # Read existing content (for revert) ─────────────────────────────────────
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content_before = f.read()
            event_type = "file_edit"
        except Exception:
            content_before = None
            event_type = "file_edit"
    else:
        content_before = None
        event_type = "file_create"

    # Generate content ────────────────────────────────────────────────────────
    print(f" Generating content for '{filename}'...")
    content_after = _generate_file_content(prompt, filename)
    if content_after is None:
        state["error"] = "Failed to generate file content."
        state["status"] = "error"
        return state

    # Write file ──────────────────────────────────────────────────────────────
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content_after)
    except Exception as e:
        state["error"] = f"Failed to write '{filename}': {e}"
        state["status"] = "error"
        return state

    # Record event ────────────────────────────────────────────────────────────
    label = f"{event_type.replace('_', ' ')} '{filename}'"
    group_id = create_group(f"Write {filename}")
    record_event(
        type_=event_type,
        filename=filename,
        content_before=content_before,
        content_after=content_after,
        label=label,
        group_id=group_id,
        cwd=cwd,
    )

    n_lines = len(content_after.splitlines())
    print(f" '{filename}' written ({n_lines} lines) — event recorded.")

    state["stdout"] = (
        f"Successfully wrote {n_lines} lines to '{filename}'.\n\n"
        f"--- Content ---\n{content_after}"
    )
    state["status"] = "success"
    state["return_code"] = 0
    state["command"] = f"write to {filename}"
    return state


# ─── Filename extraction ──────────────────────────────────────────────────────

# Map language keywords in prompts → file extensions
_LANG_TO_EXT = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts",
    "c++": ".cpp", "cpp": ".cpp",
    "c": ".c",
    "java": ".java",
    "go": ".go", "golang": ".go",
    "rust": ".rs",
    "ruby": ".rb",
    "html": ".html",
    "css": ".css",
    "sql": ".sql",
    "php": ".php",
    "bash": ".sh", "shell": ".sh",
    "markdown": ".md",
    "json": ".json",
    "yaml": ".yaml",
    "text": ".txt", "txt": ".txt",
}


def _extract_filename(prompt: str):
    """
    Extract filename from prompt. If no extension is provided,
    infer it from language keywords (e.g. 'c++ file named rcb' → 'rcb.cpp').
    """
    # 1. Dotted filename: "named foo.py", "file bar.cpp", "in hello.js"
    m = re.search(r'(?:named?|called?|file)\s+([\w.\-]+\.\w+)', prompt, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'\bin\s+([\w.\-]+\.\w+)', prompt, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'(?:create|write|make|open|edit|update)\s+([\w.\-]+\.\w+)', prompt, re.IGNORECASE)
    if m:
        return m.group(1)
    # Bare dotted filename anywhere
    m = re.search(r'\b([\w\-]+\.\w{1,5})\b', prompt)
    if m:
        return m.group(1)

    # 2. No extension — try to infer from language keyword + bare name
    #    e.g. "create a c++ file named rcb" → rcb.cpp
    ext = _infer_extension(prompt)
    name = _extract_bare_name(prompt)
    if name:
        return f"{name}{ext}"

    return None


def _infer_extension(prompt: str) -> str:
    """Detect language keyword in prompt and return extension."""
    p = prompt.lower()
    # Check multi-word first ("c++") then single-word
    for lang, ext in sorted(_LANG_TO_EXT.items(), key=lambda x: -len(x[0])):
        if lang in p:
            return ext
    return ".txt"   # safe fallback


def _extract_bare_name(prompt: str):
    """Extract a bare name from 'named X' / 'called X' patterns."""
    m = re.search(r'(?:named?|called?)\s+(\w+)', prompt, re.IGNORECASE)
    if m:
        candidate = m.group(1).lower()
        # Skip if it's a language keyword itself
        if candidate not in _LANG_TO_EXT:
            return candidate
    return None


# ─── LLM content generation ──────────────────────────────────────────────────

_LANG_MAP = {
    "py": "Python", "js": "JavaScript", "ts": "TypeScript",
    "html": "HTML", "css": "CSS", "java": "Java", "cpp": "C++",
    "c": "C", "go": "Go", "rs": "Rust", "rb": "Ruby",
    "sh": "Bash", "txt": "plain text", "md": "Markdown",
    "json": "JSON", "yaml": "YAML", "yml": "YAML",
    "sql": "SQL", "php": "PHP",
}


def _generate_file_content(prompt: str, filename: str):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    language = _LANG_MAP.get(ext, ext)

    llm_prompt = f"""The user wants to write content to a file named '{filename}' ({language}).

User request: "{prompt}"

Generate ONLY the file content. Rules:
- Do NOT include markdown code fences (no ``` blocks).
- Do NOT add explanations, preamble, or trailing comments.
- Write complete, working {language} code/content.
- The output is written to the file as-is.

File content:"""

    try:
        resp = openai.ChatCompletion.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": llm_prompt}],
            temperature=0.1,
            max_tokens=1500,
        )
        raw = (resp["choices"][0]["message"]["content"] or "").strip()
        # Strip accidental markdown fences
        raw = re.sub(r"^```[\w]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())
        return raw.strip()
    except Exception as e:
        print(f"  LLM content generation error: {e}")
        return None
