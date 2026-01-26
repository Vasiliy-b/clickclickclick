"""
AutonomousAgent - LLM-driven Instagram automation.

Executes complex tasks by using vision LLM to navigate and make decisions.
No hardcoded paths - the LLM figures out how to achieve the goal.
"""
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .navigator import VisionNavigator
from .session import AgentSession
from ..memory.store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result of a task execution."""
    success: bool
    task: str
    steps_taken: int
    duration_seconds: float
    progress: List[str]
    error: str = ""
    posts_viewed: List[str] = field(default_factory=list)
    comments_made: List[str] = field(default_factory=list)


class AutonomousAgent:
    """
    Autonomous Instagram agent powered by LLM vision.

    Usage:
        agent = AutonomousAgent(api_key="...", executor=executor)
        agent.load_persona("vera_lx")

        result = agent.execute_task(
            "Go to profile vk_artbox, follow if not following, "
            "view 5 posts and leave comments on each"
        )
    """

    def __init__(
        self,
        api_key: str,
        executor,
        model_name: str = "gemini-2.0-flash",
        mongo_uri: str = "mongodb://localhost:27017",
        db_name: str = "instagram_agents",
        device_serial: Optional[str] = None,
    ):
        self.api_key = api_key
        self.executor = executor
        self.device_serial = device_serial

        # Initialize navigator (the brain)
        self.navigator = VisionNavigator(api_key, model_name)

        # Initialize memory
        self.memory = MemoryStore(mongo_uri, db_name)
        self.memory.connect()

        # Session/persona
        self.session: Optional[AgentSession] = None
        self.persona_context = ""

        # Task state
        self._current_task = ""
        self._progress: List[str] = []
        self._step_count = 0
        self._max_steps = 100  # Safety limit

        logger.info("AutonomousAgent initialized")

    def load_persona(self, agent_name: str, config_dir: Optional[str] = None) -> bool:
        """Load persona configuration."""
        self.session = AgentSession(agent_name, config_dir)
        if not self.session.load():
            logger.error(f"Failed to load persona: {agent_name}")
            return False

        # Build persona context for LLM
        self.persona_context = self._build_persona_context()
        logger.info(f"Loaded persona: {agent_name}")
        return True

    def _build_persona_context(self) -> str:
        """Build persona context string for prompts."""
        if not self.session:
            return ""

        profile = self.session.profile
        comm = self.session.communication
        persona = self.session.persona

        lines = [
            "## PERSONA FOR COMMENTS",
            f"Name: {profile.get('name', 'Unknown')}",
            f"Profession: {profile.get('profession', {}).get('title', '')}",
            f"Tone: {comm.get('tone', 'neutral')}",
            f"Style: {comm.get('energy', 'medium')}",
            "",
            "Writing rules:",
        ]

        for rule in persona.get("writing_rules", [])[:5]:
            lines.append(f"- {rule}")

        never_use = comm.get("vocabulary", {}).get("never_use", [])
        if never_use:
            lines.append(f"\nNever use: {', '.join(never_use[:5])}")

        return "\n".join(lines)

    def _take_screenshot(self) -> Optional[str]:
        """Take screenshot and return path."""
        try:
            result = self.executor.screenshot(
                observation="autonomous_agent_screenshot",
                use_tempfile=True
            )
            if isinstance(result, tuple):
                return result[1]
            elif isinstance(result, str):
                return result
            return None
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    def _execute_action(self, action: Dict[str, Any]) -> bool:
        """Execute a single action from navigator."""
        action_type = action.get("action")

        try:
            if action_type == "tap":
                target = action.get("target", "")
                return self._tap_element(target)

            elif action_type == "type":
                text = action.get("text", "")
                self.executor.type_text(text, "autonomous_type")
                self._human_delay(200, 500)
                return True

            elif action_type == "scroll_down":
                self.executor.swipe_down("autonomous_scroll_down")
                self._human_delay(500, 1000)
                return True

            elif action_type == "scroll_up":
                self.executor.swipe_up("autonomous_scroll_up")
                self._human_delay(500, 1000)
                return True

            elif action_type == "back":
                self.executor.navigate_back("autonomous_back")
                self._human_delay(300, 600)
                return True

            elif action_type == "wait":
                seconds = action.get("seconds", 5)
                seconds = min(max(seconds, 1), 30)  # Clamp 1-30
                # Add some randomness for human-like behavior
                actual_wait = seconds + random.uniform(-1, 2)
                time.sleep(max(1, actual_wait))
                return True

            elif action_type == "screenshot":
                # Just observe, no action
                self._human_delay(500, 1000)
                return True

            elif action_type in ["complete", "failed"]:
                return True

            else:
                logger.warning(f"Unknown action type: {action_type}")
                return False

        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            return False

    def _tap_element(self, target: str) -> bool:
        """
        Tap on element by description using LLM to find coordinates.

        This uses a simplified approach - ask LLM for coordinates.
        """
        screenshot = self._take_screenshot()
        if not screenshot:
            return False

        # Use navigator to find element coordinates
        from PIL import Image
        img = Image.open(screenshot)

        prompt = f"""You are analyzing a mobile phone screenshot to find a UI element.

TASK: Find the UI element described as: "{target}"

This could be:
- An app icon (look for the app's distinctive icon, it may have the name below it or just the icon)
- A button or tab (look for clickable UI elements)
- A text link or label
- An icon without text

Screen dimensions: {img.width} x {img.height} pixels

IMPORTANT:
- Look carefully at the entire screen
- For app icons, they are usually in a grid layout
- The Instagram icon is a camera-shaped icon with gradient colors (pink/purple/orange)
- Return the CENTER point of the element

Response (JSON only):
{{
    "found": true or false,
    "x": center x coordinate in pixels,
    "y": center y coordinate in pixels,
    "confidence": 0.0 to 1.0,
    "element_description": "what you found"
}}"""

        try:
            import google.generativeai as genai
            model = genai.GenerativeModel(
                model_name=self.navigator.model_name,
                generation_config={"temperature": 0.1, "response_mime_type": "application/json"},
            )
            response = model.generate_content([img, prompt])
            result = self.navigator._extract_json(response.text)

            logger.debug(f"Element find result for '{target}': {result}")

            if result and result.get("found"):
                confidence = result.get("confidence", 0)
                # Accept any positive identification with confidence > 0.3
                if confidence > 0.3:
                    x = int(result.get("x", 0))
                    y = int(result.get("y", 0))

                    # Validate coordinates are within screen bounds
                    if 0 < x < img.width and 0 < y < img.height:
                        # Add jitter for human-like taps
                        x += random.randint(-5, 5)
                        y += random.randint(-5, 5)

                        logger.info(f"Tapping '{target}' at ({x}, {y}) conf={confidence:.2f}")
                        self.executor.click_at_a_point(x, y, f"tap_{target[:20]}")
                        self._human_delay(200, 500)
                        return True
                    else:
                        logger.warning(f"Invalid coordinates ({x}, {y}) for screen {img.width}x{img.height}")
                else:
                    logger.warning(f"Low confidence ({confidence}) for element: {target}")
            else:
                logger.warning(f"Could not find element: {target}")
            return False

        except Exception as e:
            logger.error(f"Element finding failed: {e}")
            return False

    def _human_delay(self, min_ms: int, max_ms: int):
        """Add human-like delay."""
        delay = random.randint(min_ms, max_ms) / 1000
        time.sleep(delay)

    def execute_task(
        self,
        task: str,
        max_steps: int = 50,
        step_delay: tuple = (1, 3),
    ) -> TaskResult:
        """
        Execute a complex task using LLM navigation.

        Args:
            task: Natural language task description
            max_steps: Maximum steps before giving up
            step_delay: (min, max) seconds between steps

        Returns:
            TaskResult with success status and details
        """
        logger.info(f"Starting task: {task}")

        self._current_task = task
        self._progress = []
        self._step_count = 0
        self._max_steps = max_steps

        start_time = time.time()
        posts_viewed = []
        comments_made = []

        try:
            while self._step_count < max_steps:
                self._step_count += 1

                # Take screenshot
                screenshot = self._take_screenshot()
                if not screenshot:
                    self._progress.append("Failed to take screenshot")
                    continue

                # Get navigator decision
                action = self.navigator.decide_action(
                    screenshot_path=screenshot,
                    task=task,
                    progress=self._progress,
                    persona_context=self.persona_context,
                )

                action_type = action.get("action")
                reasoning = action.get("reasoning", "")
                progress_note = action.get("progress_note", "")

                logger.info(f"Step {self._step_count}: {action_type} - {reasoning[:60]}")

                # Check for completion
                if action_type == "complete":
                    self._progress.append(f"✓ Task complete: {reasoning}")
                    return TaskResult(
                        success=True,
                        task=task,
                        steps_taken=self._step_count,
                        duration_seconds=time.time() - start_time,
                        progress=self._progress,
                        posts_viewed=posts_viewed,
                        comments_made=comments_made,
                    )

                if action_type == "failed":
                    self._progress.append(f"✗ Task failed: {reasoning}")
                    return TaskResult(
                        success=False,
                        task=task,
                        steps_taken=self._step_count,
                        duration_seconds=time.time() - start_time,
                        progress=self._progress,
                        error=reasoning,
                    )

                # Execute action
                success = self._execute_action(action)

                # Record progress
                if progress_note:
                    self._progress.append(progress_note)
                elif success:
                    self._progress.append(f"{action_type}: {action.get('target', action.get('text', ''))[:30]}")

                # Track specific achievements
                if "viewed post" in progress_note.lower() or "opened post" in progress_note.lower():
                    posts_viewed.append(progress_note)

                if action_type == "type" and "comment" in self._current_task.lower():
                    comments_made.append(action.get("text", ""))

                # Human-like delay between steps
                delay = random.uniform(step_delay[0], step_delay[1])
                time.sleep(delay)

            # Max steps reached
            return TaskResult(
                success=False,
                task=task,
                steps_taken=self._step_count,
                duration_seconds=time.time() - start_time,
                progress=self._progress,
                error="Max steps reached",
                posts_viewed=posts_viewed,
                comments_made=comments_made,
            )

        except KeyboardInterrupt:
            logger.info("Task interrupted by user")
            return TaskResult(
                success=False,
                task=task,
                steps_taken=self._step_count,
                duration_seconds=time.time() - start_time,
                progress=self._progress,
                error="Interrupted by user",
            )

        except Exception as e:
            logger.exception("Task execution error")
            return TaskResult(
                success=False,
                task=task,
                steps_taken=self._step_count,
                duration_seconds=time.time() - start_time,
                progress=self._progress,
                error=str(e),
            )

    def save_task_result(self, result: TaskResult):
        """Save task result to MongoDB."""
        if not self.memory:
            return

        doc = {
            "agent_id": self.session.agent_name if self.session else "unknown",
            "task": result.task,
            "success": result.success,
            "steps_taken": result.steps_taken,
            "duration_seconds": result.duration_seconds,
            "progress": result.progress,
            "error": result.error,
            "posts_viewed": result.posts_viewed,
            "comments_made": result.comments_made,
            "timestamp": datetime.utcnow(),
        }

        try:
            self.memory.db.task_results.insert_one(doc)
            logger.info(f"Saved task result to MongoDB")
        except Exception as e:
            logger.error(f"Failed to save task result: {e}")
