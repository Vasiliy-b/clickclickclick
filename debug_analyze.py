#!/usr/bin/env python3
import os
import sys
import yaml
import json
import google.generativeai as genai
from PIL import Image

sys.path.insert(0, '.')

api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=api_key)

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    generation_config={
        "temperature": 0.7,
        "max_output_tokens": 256,
        "response_mime_type": "application/json",
    },
)

# Load image
img = Image.open("/tmp/ig_screenshot.png")

# Simple test prompt
prompt = """Analyze this Instagram post screenshot.
Return JSON:
{
    "should_like": true/false,
    "should_comment": true/false,
    "post_type": "general" | "esoteric" | "skip",
    "reasoning": "brief explanation"
}"""

print("Sending to Gemini...")
response = model.generate_content([img, prompt])
print(f"\nRaw response text:\n{response.text}")
print(f"\nResponse type: {type(response.text)}")

# Try to parse
import json
try:
    parsed = json.loads(response.text)
    print(f"\nParsed: {parsed}")
    print(f"Type: {type(parsed)}")
except Exception as e:
    print(f"\nParse error: {e}")
