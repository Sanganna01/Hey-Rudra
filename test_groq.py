import openai
import os

from session_context import get_api_key
openai.api_key = get_api_key()
openai.api_base = "https://api.groq.com/openai/v1"

print("testing groq key:", openai.api_key)

try:
    response = openai.ChatCompletion.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=5
    )
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {e}")
