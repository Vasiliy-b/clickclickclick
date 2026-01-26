"""
Obstacle Detection and Learning System.

Detects unexpected UI states (popups, dialogs, errors) and learns how to handle them.
Uses accessibility tree patterns + optional LLM fallback for unknown obstacles.

Flow:
1. Check screen for known obstacle patterns
2. If known → apply learned solution
3. If unknown → try common dismissers OR call LLM
4. Record outcome for learning
"""
import logging
from dataclasses import dataclass
from typing import Optional, List, Callable, Dict, Any
from datetime import datetime

from .uiautomator import UIAutomatorParser, UIElement
from ..memory.models import KnownObstacle
from ..memory.store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class ObstacleDetection:
    """Result of obstacle detection."""
    detected: bool
    obstacle_type: str = ""
    screen_hash: str = ""
    confidence: float = 0.0
    known_solution: Optional[KnownObstacle] = None
    matched_text: str = ""


class ObstacleHandler:
    """
    Handles obstacle detection and resolution.

    Usage:
        handler = ObstacleHandler(parser, memory_store, executor)

        # Check and handle obstacles
        result = handler.check_and_handle()
        if result.detected and result.resolved:
            continue_with_task()
    """

    # Known obstacle patterns (text-based detection)
    OBSTACLE_PATTERNS = {
        # Login/Authentication
        "login_required": [
            "Log In", "Log in", "Sign Up", "Sign in",
            "Create New Account", "Login", "log in to continue"
        ],

        # Rate limiting
        "rate_limit": [
            "Try Again Later", "Action Blocked", "Please wait",
            "You're Temporarily Blocked", "We limit how often"
        ],

        # Notifications
        "notification_prompt": [
            "Turn On Notifications", "Enable Notifications",
            "Get Notifications", "Allow Notifications"
        ],

        # Save login
        "save_login": [
            "Save Your Login Info", "Save Login Info",
            "Save your login info", "Remember Login"
        ],

        # App update
        "update_required": [
            "Update Available", "Update Now", "Update Instagram",
            "New Version Available"
        ],

        # Consent/Privacy
        "cookie_consent": [
            "Accept All", "Accept Cookies", "Cookie",
            "privacy policy", "Privacy Policy"
        ],

        # Account status
        "account_warning": [
            "Your Account May Be Compromised",
            "Unusual Login Attempt", "Was This You",
            "Confirm Your Identity"
        ],

        # Connection issues
        "connection_error": [
            "No Internet Connection", "Couldn't refresh feed",
            "Something went wrong", "Tap to retry"
        ],

        # Age verification
        "age_verification": [
            "Enter Your Birthday", "Date of Birth",
            "How Old Are You"
        ],

        # Generic dialogs
        "generic_dialog": [
            "Cancel", "OK", "Dismiss", "Close",
            "Not Now", "Skip", "Later"
        ]
    }

    # Common dismisser texts (in priority order)
    DISMISSERS = [
        "Not Now", "Not now", "Cancel", "Skip", "Later",
        "Close", "Dismiss", "No Thanks", "No, Thanks",
        "Maybe Later", "X", "×"
    ]

    def __init__(
        self,
        parser: UIAutomatorParser,
        memory_store: Optional[MemoryStore] = None,
        executor=None,
        llm_fallback: Optional[Callable] = None
    ):
        self.parser = parser
        self.memory = memory_store
        self.executor = executor
        self.llm_fallback = llm_fallback  # function(screen_xml) -> solution

    def detect(self) -> ObstacleDetection:
        """
        Detect if current screen shows an obstacle.
        Returns detection result with obstacle type if found.
        """
        # Refresh UI tree
        self.parser.dump_and_parse()
        screen_hash = self.parser.screen_hash

        # Check memory for known obstacle
        if self.memory:
            known = self.memory.get_obstacle_solution(screen_hash)
            if known:
                logger.info(f"Known obstacle detected: {known.obstacle_type}")
                return ObstacleDetection(
                    detected=True,
                    obstacle_type=known.obstacle_type,
                    screen_hash=screen_hash,
                    confidence=known.confidence,
                    known_solution=known,
                )

        # Pattern-based detection
        for obstacle_type, patterns in self.OBSTACLE_PATTERNS.items():
            for pattern in patterns:
                element = self.parser.find_by_text(pattern)
                if element:
                    logger.info(f"Obstacle detected by pattern: {obstacle_type} ('{pattern}')")
                    return ObstacleDetection(
                        detected=True,
                        obstacle_type=obstacle_type,
                        screen_hash=screen_hash,
                        confidence=0.8,
                        matched_text=pattern,
                    )

        # No obstacle detected
        return ObstacleDetection(detected=False, screen_hash=screen_hash)

    def find_dismisser(self) -> Optional[UIElement]:
        """Find a dismisser button on current screen."""
        for dismisser_text in self.DISMISSERS:
            element = self.parser.find_by_text(dismisser_text, partial=False)
            if element and element.clickable:
                return element

            # Try content description
            element = self.parser.find_by_content_desc(dismisser_text, partial=False)
            if element and element.clickable:
                return element

        return None

    def handle(self, detection: ObstacleDetection) -> bool:
        """
        Handle detected obstacle.
        Returns True if successfully resolved.
        """
        if not detection.detected:
            return True  # No obstacle to handle

        if not self.executor:
            logger.warning("No executor available to handle obstacle")
            return False

        logger.info(f"Handling obstacle: {detection.obstacle_type}")

        # Strategy 1: Use known solution
        if detection.known_solution:
            success = self._apply_known_solution(detection.known_solution)
            if success and self.memory:
                self.memory.record_obstacle_solved(detection.screen_hash)
            return success

        # Strategy 2: Try common dismissers
        dismisser = self.find_dismisser()
        if dismisser:
            success = self._tap_element(dismisser)
            if success:
                self._learn_solution(detection, "tap_text", dismisser.text or dismisser.content_desc)
            return success

        # Strategy 3: Press back button (for dialogs)
        if detection.obstacle_type in ["generic_dialog", "notification_prompt", "save_login"]:
            try:
                self.executor.navigate_back()
                self._learn_solution(detection, "press_back", "")
                return True
            except Exception as e:
                logger.error(f"Back button failed: {e}")

        # Strategy 4: LLM fallback for unknown obstacles
        if self.llm_fallback:
            logger.info("Using LLM fallback for unknown obstacle")
            solution = self.llm_fallback(self.parser.raw_xml)
            if solution:
                success = self._apply_llm_solution(solution)
                if success:
                    self._learn_solution(detection, solution.get("action", ""), solution.get("text", ""))
                return success

        logger.warning(f"Could not handle obstacle: {detection.obstacle_type}")
        return False

    def check_and_handle(self) -> Dict[str, Any]:
        """
        Convenience method: detect and handle in one call.
        Returns result dict.
        """
        detection = self.detect()

        result = {
            "detected": detection.detected,
            "obstacle_type": detection.obstacle_type,
            "screen_hash": detection.screen_hash,
            "resolved": False,
        }

        if detection.detected:
            result["resolved"] = self.handle(detection)

        return result

    def _tap_element(self, element: UIElement) -> bool:
        """Tap an element using executor."""
        if not self.executor:
            return False

        try:
            x, y = element.center
            self.executor.click_at_a_point(x, y)
            return True
        except Exception as e:
            logger.error(f"Tap failed: {e}")
            return False

    def _apply_known_solution(self, solution: KnownObstacle) -> bool:
        """Apply a previously learned solution."""
        if not self.executor:
            return False

        try:
            if solution.solution_action == "tap_text":
                element = self.parser.find_by_text(solution.solution_text)
                if element:
                    return self._tap_element(element)

            elif solution.solution_action == "tap_coords":
                x, y = solution.solution_coords
                self.executor.click_at_a_point(x, y)
                return True

            elif solution.solution_action == "press_back":
                self.executor.navigate_back()
                return True

            elif solution.solution_action == "wait":
                import time
                time.sleep(2)
                return True

        except Exception as e:
            logger.error(f"Failed to apply solution: {e}")

        return False

    def _apply_llm_solution(self, solution: Dict[str, Any]) -> bool:
        """Apply solution suggested by LLM."""
        if not self.executor:
            return False

        action = solution.get("action", "")

        try:
            if action == "tap_text":
                text = solution.get("text", "")
                element = self.parser.find_by_text(text)
                if element:
                    return self._tap_element(element)

            elif action == "tap_coords":
                x = solution.get("x", 0)
                y = solution.get("y", 0)
                self.executor.click_at_a_point(x, y)
                return True

            elif action == "press_back":
                self.executor.navigate_back()
                return True

            elif action == "swipe_down":
                # Dismiss by swiping down (for bottom sheets)
                self.executor.swipe(540, 1500, 540, 2200, 300)
                return True

        except Exception as e:
            logger.error(f"LLM solution failed: {e}")

        return False

    def _learn_solution(self, detection: ObstacleDetection, action: str, text: str):
        """Save learned solution to memory."""
        if not self.memory:
            return

        obstacle = KnownObstacle(
            obstacle_type=detection.obstacle_type,
            screen_hash=detection.screen_hash,
            solution_action=action,
            solution_text=text,
            learned_from="runtime",
            confidence=0.7,
        )

        self.memory.save_obstacle(obstacle)
        logger.info(f"Learned solution for {detection.obstacle_type}: {action} '{text}'")


# ═══════════════════════════════════════════════════════════════════════════════
# PREDEFINED OBSTACLE SOLUTIONS (manual knowledge)
# ═══════════════════════════════════════════════════════════════════════════════

PREDEFINED_SOLUTIONS = [
    KnownObstacle(
        obstacle_type="notification_prompt",
        screen_hash="",  # matches by type, not hash
        solution_action="tap_text",
        solution_text="Not Now",
        learned_from="predefined",
        confidence=0.95,
    ),
    KnownObstacle(
        obstacle_type="save_login",
        screen_hash="",
        solution_action="tap_text",
        solution_text="Not Now",
        learned_from="predefined",
        confidence=0.95,
    ),
    KnownObstacle(
        obstacle_type="cookie_consent",
        screen_hash="",
        solution_action="tap_text",
        solution_text="Accept All",  # or customize per preference
        learned_from="predefined",
        confidence=0.9,
    ),
    KnownObstacle(
        obstacle_type="rate_limit",
        screen_hash="",
        solution_action="wait",
        solution_text="",
        learned_from="predefined",
        confidence=0.9,
    ),
]


def seed_predefined_solutions(memory: MemoryStore):
    """Seed memory with predefined obstacle solutions."""
    for solution in PREDEFINED_SOLUTIONS:
        # Only save if not already exists
        existing = memory.get_obstacle_by_type(solution.obstacle_type)
        if not existing:
            memory.save_obstacle(solution)
            logger.info(f"Seeded solution for: {solution.obstacle_type}")
