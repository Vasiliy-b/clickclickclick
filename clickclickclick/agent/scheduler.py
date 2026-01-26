"""
Scheduler - Manages agent activity timing based on personality config.

Handles:
- Activity windows (high/medium/low/zero)
- Work shift constraints
- Sleep schedule
- Lunar/astrological modifiers
"""
import logging
from datetime import datetime, time
from typing import Optional, Tuple, List
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Manages when the agent should be active based on personality schedule.

    Usage:
        scheduler = Scheduler(session.scheduling)

        if scheduler.is_active_now():
            activity_level = scheduler.get_activity_level()
            # activity_level: 'high', 'medium', 'low', 'zero'
    """

    def __init__(self, schedule_config: dict):
        self.config = schedule_config
        self.timezone = ZoneInfo(schedule_config.get("timezone", "UTC"))

    def now(self) -> datetime:
        """Get current time in agent's timezone."""
        return datetime.now(self.timezone)

    def current_time(self) -> time:
        """Get current time (without date) in agent's timezone."""
        return self.now().time()

    def _parse_time_range(self, time_range: str) -> Tuple[time, time]:
        """
        Parse time range string like '12:00-13:00' into (start, end) times.
        """
        try:
            start_str, end_str = time_range.split("-")
            start = datetime.strptime(start_str.strip(), "%H:%M").time()
            end = datetime.strptime(end_str.strip(), "%H:%M").time()
            return start, end
        except ValueError:
            logger.error(f"Invalid time range format: {time_range}")
            return time(0, 0), time(0, 0)

    def _time_in_range(self, check_time: time, start: time, end: time) -> bool:
        """
        Check if time is within range. Handles overnight ranges (e.g., 22:00-06:00).
        """
        if start <= end:
            return start <= check_time <= end
        else:
            # Overnight range
            return check_time >= start or check_time <= end

    def is_sleep_time(self) -> bool:
        """Check if current time is during sleep hours."""
        breaks = self.config.get("breaks", {}).get("sleep", {})
        if not breaks:
            activity = self.config.get("activity_windows", {}).get("zero", [])
            if activity:
                for window in activity:
                    start, end = self._parse_time_range(window)
                    if self._time_in_range(self.current_time(), start, end):
                        return True
            return False

        start_str = breaks.get("start", "05:00")
        end_str = breaks.get("end", "11:00")
        start = datetime.strptime(start_str, "%H:%M").time()
        end = datetime.strptime(end_str, "%H:%M").time()

        return self._time_in_range(self.current_time(), start, end)

    def is_work_shift(self) -> bool:
        """Check if current time is during work shift (limited activity)."""
        breaks = self.config.get("breaks", {}).get("work_shift", {})
        if not breaks:
            return False

        start_str = breaks.get("start", "19:00")
        end_str = breaks.get("end", "03:00")
        start = datetime.strptime(start_str, "%H:%M").time()
        end = datetime.strptime(end_str, "%H:%M").time()

        return self._time_in_range(self.current_time(), start, end)

    def get_activity_level(self) -> str:
        """
        Get current activity level based on time of day.

        Returns:
            'zero' - sleeping, no activity
            'low' - working or resting, minimal activity
            'medium' - moderate activity
            'high' - peak activity window
        """
        if self.is_sleep_time():
            return "zero"

        if self.is_work_shift():
            return "low"

        current = self.current_time()
        windows = self.config.get("activity_windows", {})

        # Check high activity windows
        for window in windows.get("high", []):
            start, end = self._parse_time_range(window)
            if self._time_in_range(current, start, end):
                return "high"

        # Check medium activity windows
        for window in windows.get("medium", []):
            start, end = self._parse_time_range(window)
            if self._time_in_range(current, start, end):
                return "medium"

        # Check low activity windows
        for window in windows.get("low", []):
            start, end = self._parse_time_range(window)
            if self._time_in_range(current, start, end):
                return "low"

        # Default to medium if no specific window matched
        return "medium"

    def is_active_now(self) -> bool:
        """Check if agent should be active at current time."""
        level = self.get_activity_level()
        return level != "zero"

    def get_activity_multiplier(self) -> float:
        """
        Get activity multiplier for rate limiting.
        Combines time-based level with modifiers (moon phase, etc.)
        """
        level = self.get_activity_level()

        base_multipliers = {
            "zero": 0.0,
            "low": 0.1,
            "medium": 0.5,
            "high": 1.0
        }

        multiplier = base_multipliers.get(level, 0.5)

        # Apply modifiers
        modifiers = self.config.get("modifiers", {})

        # TODO: Integrate with actual moon phase API
        # For now, these would need external data
        # full_moon_boost = modifiers.get("full_moon", {}).get("activity_boost", 1.0)
        # new_moon_reduction = modifiers.get("new_moon", {}).get("activity_reduction", 1.0)

        return multiplier

    def get_session_duration(self) -> Tuple[int, int]:
        """
        Get recommended session duration range in minutes.
        During work: shorter sessions (10-15 min)
        Otherwise: longer sessions possible
        """
        if self.is_work_shift():
            pattern = self.config.get("work_session_pattern", {})
            duration = pattern.get("session_duration_minutes", [10, 15])
            if isinstance(duration, list) and len(duration) == 2:
                return tuple(duration)
            return (10, 15)

        # Default session duration for off-work hours
        return (20, 45)

    def get_actions_per_session(self) -> Tuple[int, int]:
        """
        Get recommended number of actions per session.
        During work: 2-4 actions
        Otherwise: more flexible
        """
        if self.is_work_shift():
            pattern = self.config.get("work_session_pattern", {})
            actions = pattern.get("actions_per_session", [2, 4])
            if isinstance(actions, list) and len(actions) == 2:
                return tuple(actions)
            return (2, 4)

        # Off-work hours: more actions allowed
        return (5, 15)

    def get_next_activity_window(self) -> Optional[str]:
        """
        Get the next activity window if currently in zero/low activity.
        Returns time string like '12:00' or None if already active.
        """
        if self.get_activity_level() in ["medium", "high"]:
            return None

        current = self.current_time()
        windows = self.config.get("activity_windows", {})

        # Find next high or medium window
        all_windows = []
        for window in windows.get("high", []):
            start, _ = self._parse_time_range(window)
            all_windows.append((start, "high"))
        for window in windows.get("medium", []):
            start, _ = self._parse_time_range(window)
            all_windows.append((start, "medium"))

        all_windows.sort(key=lambda x: x[0])

        # Find next window after current time
        for start_time, level in all_windows:
            if start_time > current:
                return start_time.strftime("%H:%M")

        # If none found, return first window (next day)
        if all_windows:
            return all_windows[0][0].strftime("%H:%M")

        return None

    def get_status(self) -> dict:
        """Get current scheduler status."""
        return {
            "timezone": str(self.timezone),
            "current_time": self.current_time().strftime("%H:%M:%S"),
            "activity_level": self.get_activity_level(),
            "is_work_shift": self.is_work_shift(),
            "is_sleep_time": self.is_sleep_time(),
            "activity_multiplier": self.get_activity_multiplier(),
            "session_duration": self.get_session_duration(),
            "actions_per_session": self.get_actions_per_session(),
            "next_activity_window": self.get_next_activity_window(),
        }
