#!/usr/bin/env python3
"""Test VisionReasoner with real Instagram screenshot."""
import os
import sys
import yaml
import json

sys.path.insert(0, '.')

from clickclickclick.agent.reasoner import VisionReasoner

def load_config():
    with open("clickclickclick/config/agents/vera_lx.yaml", "r") as f:
        return yaml.safe_load(f)

def test_with_screenshot():
    api_key = os.environ.get("GEMINI_API_KEY")
    screenshot = "/tmp/ig_screenshot.png"
    
    print("=== Real Screenshot Test ===\n")
    
    # Initialize
    reasoner = VisionReasoner(api_key, model_name="gemini-2.0-flash")
    config = load_config()
    
    print(f"Persona: {config['user_profile']['name']}")
    print(f"Screenshot: {screenshot}\n")
    
    # Test analyze_post
    print("1. Analyzing post for engagement decision...")
    analysis = reasoner.analyze_post(screenshot, config)
    print(f"   Result: {json.dumps(analysis, indent=2)}\n")
    
    # Test generate_comment (only if should_comment)
    print("2. Generating comment...")
    comment = reasoner.generate_comment(screenshot, config)
    print(f"   Generated: {comment}\n")
    
    print("=== Test Complete ===")

if __name__ == "__main__":
    test_with_screenshot()
