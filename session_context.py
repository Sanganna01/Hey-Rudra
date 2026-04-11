# session_context.py

import os
import json

SESSION_FILE = os.path.expanduser("~/.heyrudra/session.json")

def get_api_key():
    key = os.environ.get("GROQ_API_KEY")
    if key: return key
    # Fallback to local file to avoid git leaks
    try:
        key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".groq_key")
        with open(key_path, "r") as f:
            return f.read().strip()
    except Exception:
        return None

def _load_session():
    if not os.path.exists(SESSION_FILE):
        return {"cwd": os.getcwd()}
    try:
        with open(SESSION_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"cwd": os.getcwd()}

def _save_session(data):
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)

def get_current_context():
    return _load_session()

def set_cwd(new_path):
    if os.path.isdir(new_path):
        data = _load_session()
        data["cwd"] = os.path.abspath(new_path)
        _save_session(data)
        return True
    return False
