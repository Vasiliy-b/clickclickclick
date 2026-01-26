"""
VisionReasoner - LLM-powered reasoning for Instagram engagement decisions.

Uses Gemini vision model to analyze screenshots and generate
personality-driven engagement decisions and comments.
"""
import json
import logging
import os
from typing import Any, Dict, Optional

import google.generativeai as genai
from PIL import Image

logger = logging.getLogger(__name__)


class VisionReasoner:
    """
    LLM-powered reasoning for Instagram engagement.

    Uses Gemini vision model to:
    - Analyze posts and decide engagement (like/comment)
    - Generate personality-driven comments
    - Solve unknown obstacles

    Usage:
        reasoner = VisionReasoner(api_key="...", model_name="gemini-3-flash-preview")

        # Analyze post for engagement decision
        decision = reasoner.analyze_post(screenshot_path, personality_config)
        # Returns: {"should_like": bool, "should_comment": bool, "post_type": str}

        # Generate comment
        comment = reasoner.generate_comment(screenshot_path, personality_config)
        # Returns: str or None
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.0-flash",
        max_output_tokens: int = 256,
    ):
        """
        Initialize VisionReasoner.

        Args:
            api_key: Gemini API key
            model_name: Model to use (default: gemini-2.0-flash)
            max_output_tokens: Max tokens for response
        """
        self.api_key = api_key
        self.model_name = model_name

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": max_output_tokens,
                "response_mime_type": "application/json",
            },
        )
        logger.info(f"VisionReasoner initialized with model: {model_name}")

    def _load_image(self, screenshot_path: str, max_size: int = 1024) -> Optional[Image.Image]:
        """Load and resize image for API."""
        if not screenshot_path or not os.path.exists(screenshot_path):
            logger.warning(f"Screenshot not found: {screenshot_path}")
            return None

        try:
            img = Image.open(screenshot_path)
            # Resize if too large
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            return None

    def _build_persona_prompt(self, config: Dict[str, Any]) -> str:
        """Build persona context from config for prompts."""
        profile = config.get("user_profile", {})
        comm = config.get("communication_style", {})
        persona = config.get("ai_persona", {})
        examples = config.get("examples", {})

        lines = [
            f"## Agent Persona: {profile.get('name', 'Unknown')}",
            f"Profession: {profile.get('profession', {}).get('title', 'unknown')}",
            f"Tone: {comm.get('tone', 'neutral')}",
            f"Energy: {comm.get('energy', 'medium')}",
            "",
            "## Writing Rules",
        ]

        for rule in persona.get("writing_rules", []):
            lines.append(f"- {rule}")

        lines.extend([
            "",
            "## Never Use These Words/Phrases",
            ", ".join(comm.get("vocabulary", {}).get("never_use", [])),
            "",
            "## Good Comment Examples",
        ])

        for ex in examples.get("good", [])[:5]:
            lines.append(f"- Context: {ex.get('context', '')}")
            lines.append(f"  Comment: \"{ex.get('comment', '')}\"")

        lines.extend([
            "",
            "## Comments to Avoid",
        ])
        for bad in examples.get("avoid", [])[:5]:
            lines.append(f"- \"{bad}\"")

        return "\n".join(lines)

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from response text."""
        try:
            parsed = json.loads(text)
            # Handle array response - take first element
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0]
            return parsed
        except json.JSONDecodeError:
            # Try to find JSON in text
            import re
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning(f"Failed to parse JSON from: {text[:200]}")
            return None

    def analyze_post(
        self,
        screenshot_path: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyze post screenshot to decide engagement.

        Args:
            screenshot_path: Path to screenshot image
            config: Full personality config (vera_lx.yaml contents)

        Returns:
            {
                "should_like": bool,
                "should_comment": bool,
                "post_type": str,  # "esoteric", "bar_content", "general", "skip"
                "reasoning": str
            }
        """
        default_result = {
            "should_like": False,
            "should_comment": False,
            "post_type": "unknown",
            "reasoning": "analysis failed",
        }

        image = self._load_image(screenshot_path)
        if not image:
            return default_result

        persona_context = self._build_persona_prompt(config)
        engagement = config.get("content_engagement", {})

        prompt = f"""Analyze this Instagram post screenshot to decide if this persona should engage.

{persona_context}

## Content Preferences
High engagement triggers: {engagement.get('triggers', {}).get('high', [])}
Medium engagement triggers: {engagement.get('triggers', {}).get('medium', [])}
Skip these: {engagement.get('triggers', {}).get('skip', [])}

## Instructions
1. Identify the post type and content
2. Check if it matches persona's interests
3. Decide engagement based on persona style (quality > quantity)

Return JSON:
{{
    "should_like": true/false,
    "should_comment": true/false,
    "post_type": "esoteric" | "bar_content" | "general" | "skip",
    "reasoning": "brief explanation"
}}

Be selective - this persona doesn't engage with everything."""

        try:
            response = self.model.generate_content([image, prompt])
            result = self._extract_json(response.text)

            if result:
                logger.debug(f"Post analysis: {result}")
                return {
                    "should_like": result.get("should_like", False),
                    "should_comment": result.get("should_comment", False),
                    "post_type": result.get("post_type", "unknown"),
                    "reasoning": result.get("reasoning", ""),
                }
        except Exception as e:
            logger.error(f"Post analysis failed: {e}")

        return default_result

    def generate_comment(
        self,
        screenshot_path: str,
        config: Dict[str, Any],
    ) -> Optional[str]:
        """
        Generate personality-driven comment for post.

        Args:
            screenshot_path: Path to screenshot image
            config: Full personality config

        Returns:
            Generated comment string or None if generation fails
        """
        image = self._load_image(screenshot_path)
        if not image:
            return None

        persona_context = self._build_persona_prompt(config)
        comm = config.get("communication_style", {})
        msg_length = comm.get("message_length", {}).get("comments", {})

        prompt = f"""Generate a comment for this Instagram post as this persona.

{persona_context}

## Comment Length
Minimum: {msg_length.get('min', 3)} words
Ideal: {msg_length.get('ideal', 8)} words
Maximum: {msg_length.get('max', 20)} words

## Instructions
1. Analyze the post content
2. Find something specific to comment on
3. Write in persona's voice - dry, observant, specific
4. No generic praise, no emojis at start
5. If nothing substantive to say, return null

Return JSON:
{{
    "comment": "your comment here" or null,
    "reasoning": "why this comment fits"
}}"""

        try:
            response = self.model.generate_content([image, prompt])
            result = self._extract_json(response.text)

            if result and result.get("comment"):
                comment = result["comment"]
                # Validate comment
                if self._validate_comment(comment, config):
                    logger.info(f"Generated comment: {comment}")
                    return comment
                else:
                    logger.warning(f"Comment failed validation: {comment}")
        except Exception as e:
            logger.error(f"Comment generation failed: {e}")

        return None

    def _validate_comment(self, comment: str, config: Dict[str, Any]) -> bool:
        """Validate comment against persona rules."""
        if not comment or comment.lower() in ["null", "none", ""]:
            return False

        comm = config.get("communication_style", {})
        never_use = comm.get("vocabulary", {}).get("never_use", [])

        # Check forbidden words
        comment_lower = comment.lower()
        for forbidden in never_use:
            if forbidden.lower() in comment_lower:
                logger.debug(f"Comment contains forbidden word: {forbidden}")
                return False

        # Check length
        word_count = len(comment.split())
        msg_length = comm.get("message_length", {}).get("comments", {})
        min_words = msg_length.get("min", 2)
        max_words = msg_length.get("max", 25)

        if word_count < min_words or word_count > max_words:
            logger.debug(f"Comment length {word_count} outside range [{min_words}, {max_words}]")
            return False

        # Check doesn't start with emoji
        if comment[0] in "🌙🖤♠️🥃❤️😀😊💕✨🙏":
            logger.debug("Comment starts with emoji")
            return False

        return True

    def solve_obstacle(
        self,
        screenshot_path: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze obstacle screen and suggest resolution.

        Args:
            screenshot_path: Path to screenshot of obstacle

        Returns:
            {
                "obstacle_type": str,
                "action": "tap" | "back" | "wait" | "dismiss",
                "target": str,  # element description
                "confidence": float
            }
            or None if can't determine action
        """
        image = self._load_image(screenshot_path)
        if not image:
            return None

        prompt = """Analyze this Instagram screen that may show an obstacle (popup, dialog, error, etc).

Identify:
1. What type of obstacle is shown (if any)
2. What action should resolve it

Common obstacles:
- Rate limit warning
- Login required
- Cookie consent
- Notification permission
- Story/Reel popup
- Connection error

Return JSON:
{
    "obstacle_type": "description of obstacle" or "none",
    "action": "tap" | "back" | "wait" | "dismiss" | "none",
    "target": "button or element to tap" or null,
    "confidence": 0.0-1.0
}

If no obstacle visible, return obstacle_type "none"."""

        try:
            response = self.model.generate_content([image, prompt])
            result = self._extract_json(response.text)

            if result and result.get("obstacle_type") != "none":
                logger.info(f"Obstacle detected: {result}")
                return result
        except Exception as e:
            logger.error(f"Obstacle analysis failed: {e}")

        return None
