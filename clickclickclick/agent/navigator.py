"""
VisionNavigator - LLM-driven navigation for Instagram.

Uses Gemini vision to understand current screen state and decide next action.
This is the "brain" that enables autonomous task execution.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from PIL import Image

logger = logging.getLogger(__name__)


class VisionNavigator:
    """
    LLM-powered navigator that decides actions based on screen state.

    Instead of hardcoded navigation paths, the LLM sees the screen
    and decides what to do next to achieve the goal.
    """

    # Available actions the agent can take
    ACTIONS = [
        "tap",           # Tap on element by description
        "type",          # Type text
        "scroll_down",   # Scroll down
        "scroll_up",     # Scroll up
        "back",          # Press back button
        "wait",          # Wait/watch (for videos)
        "screenshot",    # Just observe, no action
        "complete",      # Task is complete
        "failed",        # Task cannot be completed
    ]

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.0-flash",
    ):
        self.api_key = api_key
        self.model_name = model_name

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            generation_config={
                "temperature": 0.3,  # Lower for more deterministic navigation
                "max_output_tokens": 512,
                "response_mime_type": "application/json",
            },
        )
        logger.info(f"VisionNavigator initialized with {model_name}")

    def _load_image(self, screenshot_path: str, max_size: int = 1024) -> Optional[Image.Image]:
        """Load and resize image."""
        if not screenshot_path or not os.path.exists(screenshot_path):
            return None
        try:
            img = Image.open(screenshot_path)
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            return None

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from response."""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0]
            return parsed
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
            return None

    def decide_action(
        self,
        screenshot_path: str,
        task: str,
        progress: List[str],
        persona_context: str = "",
    ) -> Dict[str, Any]:
        """
        Decide next action based on current screen and task.

        Args:
            screenshot_path: Current screen screenshot
            task: Natural language task description
            progress: List of completed steps so far
            persona_context: Optional persona info for comments

        Returns:
            {
                "action": "tap" | "type" | "scroll_down" | "back" | "wait" | "complete" | "failed",
                "target": "element description" (for tap),
                "text": "text to type" (for type),
                "seconds": 5 (for wait),
                "reasoning": "why this action",
                "progress_note": "what was accomplished" (optional)
            }
        """
        image = self._load_image(screenshot_path)
        if not image:
            return {"action": "failed", "reasoning": "Could not load screenshot"}

        progress_text = "\n".join(f"- {p}" for p in progress[-10:]) if progress else "Nothing yet"

        prompt = f"""You are an Instagram navigation agent. Analyze the screen and decide the next action.

## YOUR TASK
{task}

## PROGRESS SO FAR
{progress_text}

## AVAILABLE ACTIONS
- tap: Tap on a UI element (specify target description)
- type: Type text (specify text)
- scroll_down: Scroll the screen down
- scroll_up: Scroll the screen up
- back: Press back/close button
- wait: Wait and watch (for videos, specify seconds 1-20)
- complete: Task is fully complete
- failed: Task cannot be completed (explain why)

## RULES
1. Look at the screenshot carefully
2. Identify what screen you're on (home feed, search, profile, post view, etc.)
3. Decide the SINGLE next action to progress toward the task
4. Handle popups/modals by dismissing them (tap "Not Now", "Cancel", X, etc.)
5. If you see a video playing, use "wait" with appropriate seconds
6. Be specific about tap targets (e.g., "search icon in bottom nav", "Follow button")

{persona_context}

## RESPONSE FORMAT (JSON)
{{
    "action": "tap|type|scroll_down|scroll_up|back|wait|complete|failed",
    "target": "element to tap (required for tap action)",
    "text": "text to type (required for type action)",
    "seconds": 10 (required for wait action),
    "reasoning": "brief explanation of why this action",
    "screen_state": "what screen/state you see",
    "progress_note": "what this action accomplishes toward the goal"
}}"""

        try:
            response = self.model.generate_content([image, prompt])
            result = self._extract_json(response.text)

            if result and result.get("action") in self.ACTIONS:
                logger.info(f"Navigator decision: {result.get('action')} - {result.get('reasoning', '')[:50]}")
                return result
            else:
                logger.warning(f"Invalid navigator response: {response.text[:200]}")
                return {"action": "screenshot", "reasoning": "Invalid response, observing"}

        except Exception as e:
            logger.error(f"Navigator error: {e}")
            return {"action": "failed", "reasoning": str(e)}

    def analyze_for_comment(
        self,
        screenshot_path: str,
        persona_context: str,
        existing_comments: List[str] = None,
    ) -> Optional[str]:
        """
        Generate a contextual comment for the current post.

        Args:
            screenshot_path: Screenshot of the post
            persona_context: Persona rules and style
            existing_comments: Other comments on the post for context

        Returns:
            Generated comment or None
        """
        image = self._load_image(screenshot_path)
        if not image:
            return None

        comments_context = ""
        if existing_comments:
            comments_context = f"\n\n## EXISTING COMMENTS ON THIS POST\n" + "\n".join(f"- {c}" for c in existing_comments[:5])

        prompt = f"""Generate a comment for this Instagram post.

{persona_context}

{comments_context}

## RULES
1. Analyze the post visual and any visible text/caption
2. Write a comment that fits the persona's voice
3. Keep it 3-20 words
4. Be specific, not generic
5. If nothing meaningful to say, return null

## RESPONSE (JSON)
{{
    "comment": "your comment" or null,
    "post_type": "what kind of post this is",
    "reasoning": "why this comment fits"
}}"""

        try:
            response = self.model.generate_content([image, prompt])
            result = self._extract_json(response.text)

            if result and result.get("comment"):
                comment = result["comment"]
                if comment.lower() not in ["null", "none", ""]:
                    return comment
            return None

        except Exception as e:
            logger.error(f"Comment generation error: {e}")
            return None

    def extract_screen_info(
        self,
        screenshot_path: str,
    ) -> Dict[str, Any]:
        """
        Extract structured info from current screen.

        Useful for:
        - Getting username from profile
        - Checking if following
        - Getting post ID/details
        - Detecting video vs image
        """
        image = self._load_image(screenshot_path)
        if not image:
            return {}

        prompt = """Analyze this Instagram screen and extract information.

## RESPONSE (JSON)
{
    "screen_type": "home_feed|search|profile|post_view|story|reels|dm|other",
    "username": "visible username if on profile or post" or null,
    "is_following": true/false/null (if Follow/Following button visible),
    "is_video": true/false (if current post is video),
    "has_stories": true/false (if profile has story ring),
    "post_caption_preview": "first ~50 chars of caption if visible" or null,
    "visible_comments": ["comment 1", "comment 2"] or [],
    "popup_or_modal": "description of popup" or null,
    "error_state": "description of error" or null
}"""

        try:
            response = self.model.generate_content([image, prompt])
            result = self._extract_json(response.text)
            return result or {}
        except Exception as e:
            logger.error(f"Screen info extraction error: {e}")
            return {}
