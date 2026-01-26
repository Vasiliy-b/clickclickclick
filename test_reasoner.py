#!/usr/bin/env python3
"""Quick test for VisionReasoner."""
import os
import sys
import yaml

# Add to path
sys.path.insert(0, '.')

from clickclickclick.agent.reasoner import VisionReasoner

def load_persona_config():
    """Load vera_lx.yaml config."""
    config_path = "clickclickclick/config/agents/vera_lx.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def test_reasoner():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set")
        return False
    
    print("=== VisionReasoner Test ===\n")
    
    # Initialize
    print("1. Initializing VisionReasoner...")
    reasoner = VisionReasoner(api_key, model_name="gemini-2.0-flash")
    print("   OK\n")
    
    # Load config
    print("2. Loading vera_lx.yaml config...")
    config = load_persona_config()
    print(f"   Loaded persona: {config.get('user_profile', {}).get('name', 'unknown')}\n")
    
    # Test without screenshot (should handle gracefully)
    print("3. Testing analyze_post with no screenshot...")
    result = reasoner.analyze_post("/nonexistent/path.png", config)
    print(f"   Result: {result}")
    print(f"   Handled missing file: {'OK' if not result['should_like'] else 'UNEXPECTED'}\n")
    
    # Test comment validation
    print("4. Testing comment validation...")
    test_comments = [
        ("4 of pentacles interesting here", True),
        ("love it! amazing!", False),  # contains forbidden words
        ("ok", False),  # too short
        ("❤️ great post", False),  # starts with emoji
        ("saturn 8th house energy right there", True),
    ]
    
    for comment, expected in test_comments:
        valid = reasoner._validate_comment(comment, config)
        status = "✓" if valid == expected else "✗"
        print(f"   {status} '{comment[:40]}...' -> valid={valid} (expected={expected})")
    
    print("\n=== Test Complete ===")
    return True

if __name__ == "__main__":
    test_reasoner()
