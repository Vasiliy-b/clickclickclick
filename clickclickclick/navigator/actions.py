"""
Instagram Scripted Actions - 90% of navigation without LLM.

Each action:
1. Dumps accessibility tree
2. Finds target element
3. Executes tap/swipe with jitter
4. Logs action for learning

Usage:
    actions = InstagramActions(executor)

    # Navigate to home feed
    actions.go_home()

    # Like current post
    actions.like_post()

    # Scroll feed
    actions.scroll_feed()

    # Open profile tab
    actions.open_profile()
"""
import random
import time
import logging
from typing import Optional, Tuple, Callable, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

from .uiautomator import UIAutomatorParser, UIElement

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result of an action execution."""
    success: bool
    action_name: str
    element: Optional[UIElement] = None
    coords: Tuple[int, int] = (0, 0)
    duration_ms: int = 0
    error: str = ""
    screen_hash: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action_name,
            "element": self.element.to_dict() if self.element else None,
            "coords": self.coords,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "screen_hash": self.screen_hash,
            "timestamp": self.timestamp.isoformat(),
        }


class InstagramActions:
    """
    Scripted Instagram actions using accessibility tree navigation.

    No LLM calls - pure deterministic navigation with jitter for human-like behavior.
    """

    def __init__(self, executor, device_serial: Optional[str] = None):
        """
        Args:
            executor: AndroidExecutor instance for ADB commands
            device_serial: Optional device serial for multi-device setup
        """
        self.executor = executor
        self.parser = UIAutomatorParser(device_serial)
        self.action_log: list = []

        # Jitter settings for human-like behavior
        self.jitter_enabled = True
        self.tap_jitter_px = 5  # random offset in pixels
        self.delay_jitter_ms = (50, 200)  # random delay range

        # Callback for action logging (can be overridden)
        self.on_action: Optional[Callable[[ActionResult], None]] = None

    def _add_jitter(self, x: int, y: int) -> Tuple[int, int]:
        """Add small random offset to coordinates."""
        if not self.jitter_enabled:
            return x, y
        jx = random.randint(-self.tap_jitter_px, self.tap_jitter_px)
        jy = random.randint(-self.tap_jitter_px, self.tap_jitter_px)
        return x + jx, y + jy

    def _delay(self, base_ms: int = 0):
        """Add human-like delay with jitter."""
        min_j, max_j = self.delay_jitter_ms
        jitter = random.randint(min_j, max_j)
        total_ms = base_ms + jitter
        time.sleep(total_ms / 1000)

    def _tap(self, x: int, y: int) -> bool:
        """Execute tap with jitter and delay."""
        x, y = self._add_jitter(x, y)
        self._delay(50)

        try:
            self.executor.click_at_a_point(x, y)
            return True
        except Exception as e:
            logger.error(f"Tap failed: {e}")
            return False

    def _swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        """Execute swipe with jitter."""
        x1, y1 = self._add_jitter(x1, y1)
        x2, y2 = self._add_jitter(x2, y2)

        try:
            self.executor.swipe(x1, y1, x2, y2, duration_ms)
            return True
        except Exception as e:
            logger.error(f"Swipe failed: {e}")
            return False

    def _log_action(self, result: ActionResult):
        """Log action result."""
        self.action_log.append(result)

        if self.on_action:
            self.on_action(result)

        level = logging.INFO if result.success else logging.WARNING
        logger.log(level, f"Action: {result.action_name} -> {'OK' if result.success else result.error}")

    def _execute_action(
        self,
        action_name: str,
        finder: Callable[[], Optional[UIElement]],
        fallback_coords: Optional[Tuple[int, int]] = None
    ) -> ActionResult:
        """
        Generic action executor.

        1. Refresh accessibility tree
        2. Find element using finder function
        3. Tap element center (or fallback coords)
        4. Log result
        """
        start = time.time()

        # Refresh UI tree
        self.parser.dump_and_parse()
        screen_hash = self.parser.screen_hash

        # Find element
        element = finder()

        if element:
            x, y = element.center
            success = self._tap(x, y)
            duration = int((time.time() - start) * 1000)

            result = ActionResult(
                success=success,
                action_name=action_name,
                element=element,
                coords=(x, y),
                duration_ms=duration,
                screen_hash=screen_hash,
            )
        elif fallback_coords:
            x, y = fallback_coords
            success = self._tap(x, y)
            duration = int((time.time() - start) * 1000)

            result = ActionResult(
                success=success,
                action_name=action_name,
                coords=(x, y),
                duration_ms=duration,
                error="element_not_found_used_fallback",
                screen_hash=screen_hash,
            )
        else:
            duration = int((time.time() - start) * 1000)
            result = ActionResult(
                success=False,
                action_name=action_name,
                duration_ms=duration,
                error="element_not_found",
                screen_hash=screen_hash,
            )

        self._log_action(result)
        return result

    # =========================================================================
    # NAVIGATION ACTIONS
    # =========================================================================

    def go_home(self) -> ActionResult:
        """Navigate to Instagram home feed."""
        return self._execute_action(
            "go_home",
            lambda: self.parser.find_instagram_element("home_tab"),
            fallback_coords=(108, 2280)  # typical home tab location
        )

    def open_search(self) -> ActionResult:
        """Open search/explore tab."""
        return self._execute_action(
            "open_search",
            lambda: self.parser.find_instagram_element("search_tab"),
            fallback_coords=(324, 2280)
        )

    def open_reels(self) -> ActionResult:
        """Open Reels tab."""
        return self._execute_action(
            "open_reels",
            lambda: self.parser.find_instagram_element("reels_tab"),
            fallback_coords=(540, 2280)
        )

    def open_profile(self) -> ActionResult:
        """Open profile tab."""
        return self._execute_action(
            "open_profile",
            lambda: self.parser.find_instagram_element("profile_tab"),
            fallback_coords=(972, 2280)
        )

    def press_back(self) -> ActionResult:
        """Press Android back button."""
        start = time.time()
        try:
            self.executor.navigate_back()
            success = True
            error = ""
        except Exception as e:
            success = False
            error = str(e)

        result = ActionResult(
            success=success,
            action_name="press_back",
            duration_ms=int((time.time() - start) * 1000),
            error=error,
        )
        self._log_action(result)
        return result

    # =========================================================================
    # FEED ACTIONS
    # =========================================================================

    def scroll_feed(self, distance: int = 800) -> ActionResult:
        """Scroll feed down by distance pixels."""
        start = time.time()

        # Get screen center
        screen_width = 1080  # TODO: get from device
        screen_height = 2400

        start_x = screen_width // 2
        start_y = screen_height // 2 + distance // 2
        end_y = screen_height // 2 - distance // 2

        success = self._swipe(start_x, start_y, start_x, end_y, duration_ms=400)

        result = ActionResult(
            success=success,
            action_name="scroll_feed",
            coords=(start_x, start_y),
            duration_ms=int((time.time() - start) * 1000),
        )
        self._log_action(result)
        return result

    def scroll_up(self, distance: int = 500) -> ActionResult:
        """Scroll up (to see previous content)."""
        start = time.time()

        screen_width = 1080
        screen_height = 2400

        start_x = screen_width // 2
        start_y = screen_height // 2 - distance // 2
        end_y = screen_height // 2 + distance // 2

        success = self._swipe(start_x, start_y, start_x, end_y, duration_ms=400)

        result = ActionResult(
            success=success,
            action_name="scroll_up",
            coords=(start_x, start_y),
            duration_ms=int((time.time() - start) * 1000),
        )
        self._log_action(result)
        return result

    # =========================================================================
    # ENGAGEMENT ACTIONS
    # =========================================================================

    def like_post(self) -> ActionResult:
        """Like current post (tap heart icon)."""
        return self._execute_action(
            "like_post",
            lambda: self.parser.find_instagram_element("like"),
        )

    def unlike_post(self) -> ActionResult:
        """Unlike current post (same button as like)."""
        return self.like_post()  # same action, toggles state

    def double_tap_like(self) -> ActionResult:
        """Double tap on post image to like."""
        start = time.time()

        self.parser.dump_and_parse()
        post_image = self.parser.find_instagram_element("post_image")

        if post_image:
            x, y = post_image.center
            x, y = self._add_jitter(x, y)

            # Double tap
            self._tap(x, y)
            time.sleep(0.1)
            self._tap(x, y)

            result = ActionResult(
                success=True,
                action_name="double_tap_like",
                element=post_image,
                coords=(x, y),
                duration_ms=int((time.time() - start) * 1000),
                screen_hash=self.parser.screen_hash,
            )
        else:
            # Fallback: double tap screen center
            x, y = 540, 1000
            self._tap(x, y)
            time.sleep(0.1)
            self._tap(x, y)

            result = ActionResult(
                success=True,
                action_name="double_tap_like",
                coords=(x, y),
                duration_ms=int((time.time() - start) * 1000),
                error="used_fallback_coords",
            )

        self._log_action(result)
        return result

    def open_comments(self) -> ActionResult:
        """Open comments section."""
        return self._execute_action(
            "open_comments",
            lambda: self.parser.find_instagram_element("comment"),
        )

    def tap_save(self) -> ActionResult:
        """Save/bookmark post."""
        return self._execute_action(
            "tap_save",
            lambda: self.parser.find_instagram_element("save"),
        )

    def tap_share(self) -> ActionResult:
        """Open share menu."""
        return self._execute_action(
            "tap_share",
            lambda: self.parser.find_instagram_element("share"),
        )

    # =========================================================================
    # PROFILE ACTIONS
    # =========================================================================

    def tap_follow(self) -> ActionResult:
        """Tap follow button."""
        return self._execute_action(
            "tap_follow",
            lambda: self.parser.find_by_text("Follow", partial=False),
        )

    def tap_username(self) -> ActionResult:
        """Tap username to open profile."""
        return self._execute_action(
            "tap_username",
            lambda: self.parser.find_instagram_element("username"),
        )

    # =========================================================================
    # TEXT INPUT
    # =========================================================================

    def type_text(self, text: str) -> ActionResult:
        """Type text (for comments, search, etc.)."""
        start = time.time()

        try:
            self.executor.type_text(text)
            success = True
            error = ""
        except Exception as e:
            success = False
            error = str(e)

        result = ActionResult(
            success=success,
            action_name="type_text",
            duration_ms=int((time.time() - start) * 1000),
            error=error,
        )
        self._log_action(result)
        return result

    def tap_send_comment(self) -> ActionResult:
        """Tap send/post button for comment."""
        return self._execute_action(
            "tap_send_comment",
            lambda: self.parser.find_by_text("Post") or self.parser.find_by_content_desc("Post"),
        )

    # =========================================================================
    # POPUP HANDLING
    # =========================================================================

    def dismiss_popup(self) -> ActionResult:
        """Try to dismiss common popups (Not Now, Cancel, X, etc.)."""
        dismissers = [
            lambda: self.parser.find_by_text("Not Now"),
            lambda: self.parser.find_by_text("Not now"),
            lambda: self.parser.find_by_text("Cancel"),
            lambda: self.parser.find_by_text("Skip"),
            lambda: self.parser.find_by_content_desc("Close"),
            lambda: self.parser.find_by_content_desc("Dismiss"),
        ]

        self.parser.dump_and_parse()

        for finder in dismissers:
            element = finder()
            if element:
                return self._execute_action("dismiss_popup", finder)

        # No popup found
        return ActionResult(
            success=True,
            action_name="dismiss_popup",
            error="no_popup_found",
            screen_hash=self.parser.screen_hash,
        )

    def check_for_obstacles(self) -> Optional[str]:
        """
        Check current screen for known obstacles.
        Returns obstacle type or None.
        """
        self.parser.dump_and_parse()

        # Check for common obstacles
        obstacles = {
            "login_required": ["Log In", "Sign Up", "Log in"],
            "rate_limit": ["Try Again Later", "Action Blocked"],
            "notification_popup": ["Turn On Notifications", "Enable Notifications"],
            "save_login": ["Save Your Login Info", "Save Login Info"],
            "update_app": ["Update Available", "Update Now"],
        }

        for obstacle_type, texts in obstacles.items():
            for text in texts:
                if self.parser.find_by_text(text):
                    logger.warning(f"Obstacle detected: {obstacle_type}")
                    return obstacle_type

        return None

    # =========================================================================
    # UTILITY
    # =========================================================================

    def refresh_screen(self) -> Dict[str, Any]:
        """Refresh and return screen summary."""
        self.parser.dump_and_parse()
        return self.parser.get_screen_summary()

    def get_screenshot_path(self) -> Optional[str]:
        """
        Take a screenshot and return the temporary file path.

        Used by VisionReasoner for LLM analysis.
        Returns None if screenshot fails.
        """
        try:
            result = self.executor.screenshot(use_tempfile=True)
            if isinstance(result, tuple):
                # (Image, path) tuple returned
                return result[1]
            elif isinstance(result, str):
                return result
            return None
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return None

    def get_action_log(self, last_n: int = 10) -> list:
        """Get recent action log entries."""
        return [a.to_dict() for a in self.action_log[-last_n:]]

    def clear_action_log(self):
        """Clear action log."""
        self.action_log = []
