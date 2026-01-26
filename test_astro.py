#!/usr/bin/env python3
import os, sys, yaml, json
sys.path.insert(0, '.')
from clickclickclick.agent.reasoner import VisionReasoner

api_key = os.environ.get("GEMINI_API_KEY")
with open("clickclickclick/config/agents/vera_lx.yaml", "r") as f:
    config = yaml.safe_load(f)

reasoner = VisionReasoner(api_key, model_name="gemini-2.0-flash")

print("=== Astrology Post Test ===\n")
print(f"Vera's sign: Gemini ascendant, Aries sun, Virgo moon")
print(f"Screenshot: /tmp/ig_astro.png\n")

print("1. Analyzing post...")
analysis = reasoner.analyze_post("/tmp/ig_astro.png", config)
print(f"   {json.dumps(analysis, indent=2)}\n")

print("2. Generating comment...")
comment = reasoner.generate_comment("/tmp/ig_astro.png", config)
print(f"   '{comment}'\n")

print("=== Done ===")
