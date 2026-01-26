"""
Instagram Agent Orchestrator - Main controller.

Combines:
- Personality (vera_lx.yaml)
- Scheduler (when to act)
- Navigator (90% scripted actions)
- Memory (MongoDB persistence)
- Reasoning (10% LLM calls)

Usage:
    orchestrator = Orchestrator(
        agent_name="vera_lx",
        device_serial="emulator-5554"
    )
    orchestrator.start_session()

    # Run one activity cycle
    orchestrator.run_cycle()

    # Or run continuously
    orchestrator.run_loop()
"""
import logging
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

from .session import AgentSession
from .scheduler import Scheduler
from .reasoner import VisionReasoner
from ..navigator.uiautomator import UIAutomatorParser
from ..navigator.actions import InstagramActions, ActionResult
from ..navigator.obstacles import ObstacleHandler
from ..memory.store import MemoryStore
from ..memory.models import ViewedPost, SentComment, SessionState

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    """Result of one activity cycle."""
    success: bool
    actions_taken: int
    duration_seconds: float
    error: str = ""
    obstacle_encountered: str = ""


class Orchestrator:
    """
    Main Instagram agent orchestrator.

    Architecture:
    - 90% scripted navigation via accessibility tree
    - 10% LLM reasoning for content analysis & comments
    """

    def __init__(
        self,
        agent_name: str,
        device_serial: Optional[str] = None,
        mongo_uri: str = "mongodb://localhost:27017",
        db_name: str = "instagram_agents",
        config_dir: Optional[str] = None,
        reasoning_callback: Optional[Callable] = None,
    ):
        """
        Args:
            agent_name: Name of agent config (e.g., "vera_lx")
            device_serial: ADB device serial for multi-device
            mongo_uri: MongoDB connection string
            db_name: MongoDB database name
            config_dir: Custom config directory
            reasoning_callback: LLM function for reasoning (screenshot → decision)
        """
        self.agent_name = agent_name
        self.device_serial = device_serial
        self.reasoning_callback = reasoning_callback

        # Initialize components
        self.session = AgentSession(agent_name, config_dir)
        self.memory = MemoryStore(mongo_uri, db_name)
        self.scheduler: Optional[Scheduler] = None
        self.parser: Optional[UIAutomatorParser] = None
        self.actions: Optional[InstagramActions] = None
        self.obstacle_handler: Optional[ObstacleHandler] = None
        self.reasoner: Optional[VisionReasoner] = None

        # State
        self._initialized = False
        self._session_start: Optional[datetime] = None
        self._cycle_count = 0

    def initialize(self) -> bool:
        """Initialize all components."""
        # Load personality
        if not self.session.load():
            logger.error(f"Failed to load agent config: {self.agent_name}")
            return False

        # Initialize scheduler
        self.scheduler = Scheduler(self.session.scheduling)

        # Connect to memory
        if not self.memory.connect():
            logger.warning("MongoDB connection failed, running without persistence")

        # Initialize navigator components
        # Note: executor needs to be injected from clickclickclick
        self.parser = UIAutomatorParser(self.device_serial)

        self._initialized = True
        logger.info(f"Orchestrator initialized for agent: {self.agent_name}")
        return True

    def set_executor(self, executor):
        """Set the executor (AndroidExecutor) for actions."""
        self.actions = InstagramActions(executor, self.device_serial)
        self.actions.on_action = self._on_action  # hook action logging

        self.obstacle_handler = ObstacleHandler(
            self.parser,
            self.memory,
            executor,
            llm_fallback=self._llm_obstacle_solver if (self.reasoning_callback or self.reasoner) else None
        )

    def set_reasoner(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        """
        Set up the VisionReasoner for LLM-powered engagement decisions.

        Args:
            api_key: Gemini API key
            model_name: Model to use (default: gemini-2.0-flash)
        """
        self.reasoner = VisionReasoner(api_key, model_name)
        logger.info(f"VisionReasoner configured with model: {model_name}")

    def _on_action(self, result: ActionResult):
        """Callback for action logging."""
        if self.memory:
            self.memory.log_action(self.agent_name, result.to_dict())

    def _llm_obstacle_solver(self, screen_xml: str) -> Optional[Dict[str, Any]]:
        """Use LLM to solve unknown obstacle."""
        # Try VisionReasoner first
        if self.reasoner and self.actions:
            screenshot = self.actions.get_screenshot_path()
            if screenshot:
                result = self.reasoner.solve_obstacle(screenshot)
                if result and result.get("action") != "none":
                    return result

        # Fallback to legacy reasoning_callback
        if self.reasoning_callback:
            return self.reasoning_callback(screen_xml)

        return None

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def start_session(self) -> bool:
        """Start a new activity session."""
        if not self._initialized:
            if not self.initialize():
                return False

        # Check scheduler
        if self.scheduler and not self.scheduler.is_active_now():
            activity = self.scheduler.get_activity_level()
            next_window = self.scheduler.get_next_activity_window()
            logger.info(f"Not active now (level={activity}). Next window: {next_window}")
            return False

        # Load/create session state
        state = self.memory.get_session_state(self.agent_name) if self.memory else None
        if state:
            if state.is_in_cooldown():
                logger.warning(f"Agent in cooldown until {state.cooldown_until}")
                return False
            state.reset_daily_if_needed()
        else:
            state = SessionState(agent_id=self.agent_name)
            state.date = datetime.utcnow().strftime("%Y-%m-%d")

        state.total_sessions += 1
        state.current_task = "starting"

        if self.memory:
            self.memory.save_session_state(state)

        self._session_start = datetime.now()
        self._cycle_count = 0

        logger.info(f"Session started for {self.agent_name}")
        return True

    def end_session(self):
        """End current session."""
        if self.memory:
            state = self.memory.get_session_state(self.agent_name)
            if state:
                state.current_task = "idle"
                self.memory.save_session_state(state)

        duration = (datetime.now() - self._session_start).seconds if self._session_start else 0
        logger.info(f"Session ended. Duration: {duration}s, Cycles: {self._cycle_count}")

        self._session_start = None
        self._cycle_count = 0

    # =========================================================================
    # ACTIVITY CYCLES
    # =========================================================================

    def run_cycle(self) -> CycleResult:
        """
        Run one activity cycle.

        A cycle consists of:
        1. Check for obstacles
        2. Scroll feed
        3. Analyze visible content (may use LLM)
        4. Engage if appropriate (like/comment)
        5. Random delay
        """
        start_time = time.time()
        actions_taken = 0

        if not self.actions:
            return CycleResult(False, 0, 0, error="No executor set")

        # Check limits
        if not self._check_limits():
            return CycleResult(False, 0, 0, error="Limits reached")

        try:
            # Step 1: Check for obstacles
            if self.obstacle_handler:
                obstacle_result = self.obstacle_handler.check_and_handle()
                if obstacle_result["detected"]:
                    if not obstacle_result["resolved"]:
                        return CycleResult(
                            False, 0, time.time() - start_time,
                            obstacle_encountered=obstacle_result["obstacle_type"]
                        )

            # Step 2: Ensure we're on home feed
            screen = self.actions.refresh_screen()
            if not screen.get("is_instagram"):
                logger.warning("Instagram not in foreground")
                return CycleResult(False, 0, time.time() - start_time, error="Instagram not open")

            # Step 3: Scroll feed
            self._human_delay(500, 1500)
            self.actions.scroll_feed(random.randint(600, 1000))
            actions_taken += 1

            # Step 4: Analyze and maybe engage
            engagement = self._decide_engagement()

            if engagement["should_like"]:
                self._human_delay(300, 800)
                result = self.actions.like_post()
                if result.success:
                    actions_taken += 1
                    self._record_like()

            if engagement["should_comment"] and engagement["comment_text"]:
                self._human_delay(500, 1200)
                self.actions.open_comments()
                self._human_delay(300, 600)
                self.actions.type_text(engagement["comment_text"])
                self._human_delay(200, 400)
                self.actions.tap_send_comment()
                actions_taken += 3
                self._record_comment(
                    engagement["comment_text"],
                    engagement.get("target_username", ""),
                    engagement.get("post_type", ""),
                )

            # Step 5: Random pause
            self._human_delay(1000, 3000)

            self._cycle_count += 1
            duration = time.time() - start_time

            return CycleResult(True, actions_taken, duration)

        except Exception as e:
            logger.error(f"Cycle error: {e}")
            return CycleResult(False, actions_taken, time.time() - start_time, error=str(e))

    def run_loop(self, max_cycles: int = 0):
        """
        Run activity loop until session should end.

        Args:
            max_cycles: Stop after N cycles (0 = unlimited)
        """
        if not self.start_session():
            return

        try:
            cycle = 0
            while True:
                cycle += 1

                # Check if should continue
                if max_cycles and cycle > max_cycles:
                    logger.info(f"Max cycles ({max_cycles}) reached")
                    break

                if self.scheduler and not self.scheduler.is_active_now():
                    logger.info("Activity window ended")
                    break

                if self._should_take_break():
                    break_duration = random.randint(5 * 60, 15 * 60)  # 5-15 min
                    logger.info(f"Taking break for {break_duration}s")
                    time.sleep(break_duration)
                    continue

                # Run cycle
                result = self.run_cycle()

                if not result.success:
                    if result.obstacle_encountered == "rate_limit":
                        logger.warning("Rate limit hit, ending session")
                        self._enter_cooldown(hours=2)
                        break

                    # Consecutive errors check
                    # TODO: Track and handle consecutive errors

                # Inter-cycle delay
                min_delay, max_delay = self._get_inter_cycle_delay()
                delay = random.randint(min_delay, max_delay)
                logger.debug(f"Inter-cycle delay: {delay}s")
                time.sleep(delay)

        finally:
            self.end_session()

    # =========================================================================
    # DECISION MAKING (10% LLM)
    # =========================================================================

    def _decide_engagement(self) -> Dict[str, Any]:
        """
        Decide whether to engage with current post.

        Uses VisionReasoner for LLM-powered decisions when available.
        Falls back to random heuristics otherwise.
        """
        should_like = False
        should_comment = False
        comment_text = ""
        target_username = ""

        # Get session limits check
        can_like = self.session.can_like() if self.session else True
        can_comment = self.session.can_comment() if self.session else True

        if not can_like and not can_comment:
            return {"should_like": False, "should_comment": False, "comment_text": ""}

        # Use VisionReasoner if available
        if self.reasoner and self.actions:
            screenshot = self.actions.get_screenshot_path()
            if screenshot and self.session:
                analysis = self.reasoner.analyze_post(screenshot, self.session.config)

                should_like = can_like and analysis.get("should_like", False)
                should_comment = can_comment and analysis.get("should_comment", False)

                logger.debug(
                    f"LLM engagement decision: like={should_like}, comment={should_comment}, "
                    f"type={analysis.get('post_type')}, reason={analysis.get('reasoning')}"
                )

                if should_comment:
                    comment_text = self._generate_comment()

                return {
                    "should_like": should_like,
                    "should_comment": should_comment,
                    "comment_text": comment_text,
                    "target_username": target_username,
                    "post_type": analysis.get("post_type", "unknown"),
                }

        # Fallback: simple heuristic (random engagement)
        if can_like and random.random() < 0.3:  # 30% like rate
            should_like = True

        if can_comment and random.random() < 0.1:  # 10% comment rate
            should_comment = True
            comment_text = self._generate_comment_simple()

        return {
            "should_like": should_like,
            "should_comment": should_comment,
            "comment_text": comment_text,
            "target_username": target_username,
        }

    def _generate_comment(self) -> str:
        """
        Generate comment using VisionReasoner.

        Falls back to _generate_comment_simple if reasoner unavailable.
        """
        if self.reasoner and self.actions and self.session:
            screenshot = self.actions.get_screenshot_path()
            if screenshot:
                comment = self.reasoner.generate_comment(screenshot, self.session.config)
                if comment:
                    logger.info(f"LLM generated comment: {comment}")
                    return comment

        # Fallback to simple generation
        return self._generate_comment_simple()

    def _generate_comment_simple(self) -> str:
        """
        Generate simple comment without LLM.
        Used as fallback when VisionReasoner is unavailable.
        """
        # Get templates from personality
        templates = self.session.engagement.get("templates", {})
        esoteric = templates.get("esoteric", [])
        dry_humor = templates.get("dry_humor", [])
        all_templates = esoteric + dry_humor

        if all_templates:
            template = random.choice(all_templates)
            # Simple template - in production would fill variables
            return template.split("{")[0].strip()  # Remove unfilled vars

        # Fallback
        return "interesting"

    # =========================================================================
    # LIMITS & TIMING
    # =========================================================================

    def _check_limits(self) -> bool:
        """Check if we can continue acting."""
        if not self.memory:
            return True

        state = self.memory.get_session_state(self.agent_name)
        if not state:
            return True

        limits = self.session.limits.get("daily", {})

        if state.likes_today >= limits.get("likes", 40):
            logger.info("Daily like limit reached")
            return False

        if state.comments_today >= limits.get("comments", 8):
            logger.info("Daily comment limit reached")

        return True

    def _record_like(self):
        """Record a like action."""
        self.session.record_like()
        if self.memory:
            self.memory.increment_session_counter(self.agent_name, "likes_today")

    def _record_comment(self, text: str, username: str, post_type: str = ""):
        """Record a comment action."""
        self.session.record_comment()
        if self.memory:
            self.memory.increment_session_counter(self.agent_name, "comments_today")
            comment = SentComment(
                comment_text=text,
                target_username=username,
                agent_id=self.agent_name,
                trigger_type=post_type,  # esoteric, bar_content, general, etc.
            )
            self.memory.save_sent_comment(comment)

    def _should_take_break(self) -> bool:
        """Check if should take a break."""
        if self.session.should_take_break():
            return True

        # Random break probability
        breaks = self.session.limits.get("breaks", {}).get("random", {})
        if breaks.get("enabled", False):
            # Small chance per cycle
            if random.random() < 0.05:
                return True

        return False

    def _enter_cooldown(self, hours: int = 2):
        """Enter cooldown period."""
        if self.memory:
            state = self.memory.get_session_state(self.agent_name)
            if state:
                from datetime import timedelta
                state.cooldown_until = datetime.utcnow() + timedelta(hours=hours)
                state.cooldown_reason = "rate_limit"
                self.memory.save_session_state(state)

    def _get_inter_cycle_delay(self) -> tuple:
        """Get delay between cycles based on activity level."""
        if self.scheduler:
            level = self.scheduler.get_activity_level()
            if level == "high":
                return (10, 30)
            elif level == "medium":
                return (30, 60)
            elif level == "low":
                return (60, 180)

        return (20, 60)  # default

    def _human_delay(self, min_ms: int, max_ms: int):
        """Add human-like delay."""
        delay = random.randint(min_ms, max_ms) / 1000
        time.sleep(delay)

    # =========================================================================
    # STATUS & MONITORING
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get current orchestrator status."""
        return {
            "agent": self.agent_name,
            "initialized": self._initialized,
            "session_active": self._session_start is not None,
            "session_start": self._session_start.isoformat() if self._session_start else None,
            "cycles_completed": self._cycle_count,
            "scheduler": self.scheduler.get_status() if self.scheduler else None,
            "session_state": self.session.get_status() if self.session else None,
        }
