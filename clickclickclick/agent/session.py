"""
AgentSession - Manages Instagram agent with personality configuration.

Loads personality from YAML, injects context into planner prompts,
tracks session state, and coordinates with scheduler/limiter.
"""
import os
import yaml
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Tracks current session metrics."""
    session_start: datetime = field(default_factory=datetime.now)
    actions_this_session: int = 0
    likes_today: int = 0
    comments_today: int = 0
    follows_today: int = 0
    last_action_time: Optional[datetime] = None
    current_activity: str = "idle"  # idle, scrolling, engaging, resting

    def reset_daily(self):
        """Reset daily counters (call at midnight)."""
        self.likes_today = 0
        self.comments_today = 0
        self.follows_today = 0


class AgentSession:
    """
    Manages an Instagram agent session with personality-driven behavior.

    Usage:
        session = AgentSession("vera_lx")
        session.load()

        # Get persona context for planner
        context = session.get_persona_context()

        # Generate comment in character
        comment = session.generate_comment(post_context)

        # Check if action is allowed
        if session.can_like():
            session.record_like()
    """

    def __init__(self, agent_name: str, config_dir: Optional[str] = None):
        self.agent_name = agent_name
        self.config_dir = config_dir or os.path.join(
            os.path.dirname(__file__), "..", "config", "agents"
        )
        self.config: Dict[str, Any] = {}
        self.state = SessionState()
        self._loaded = False

    def load(self) -> bool:
        """Load agent personality configuration from YAML."""
        config_path = os.path.join(self.config_dir, f"{self.agent_name}.yaml")

        if not os.path.exists(config_path):
            logger.error(f"Agent config not found: {config_path}")
            return False

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
            self._loaded = True
            logger.info(f"Loaded agent config: {self.agent_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to load agent config: {e}")
            return False

    @property
    def profile(self) -> Dict[str, Any]:
        """Get user profile section."""
        return self.config.get("user_profile", {})

    @property
    def communication(self) -> Dict[str, Any]:
        """Get communication style section."""
        return self.config.get("communication_style", {})

    @property
    def limits(self) -> Dict[str, Any]:
        """Get rate limits section."""
        return self.config.get("limits", {})

    @property
    def scheduling(self) -> Dict[str, Any]:
        """Get scheduling section."""
        return self.config.get("scheduling", {})

    @property
    def persona(self) -> Dict[str, Any]:
        """Get AI persona section."""
        return self.config.get("ai_persona", {})

    @property
    def engagement(self) -> Dict[str, Any]:
        """Get content engagement section."""
        return self.config.get("content_engagement", {})

    # =========================================================================
    # PERSONA CONTEXT FOR PLANNER
    # =========================================================================

    def get_persona_context(self) -> str:
        """
        Generate persona context to inject into planner system prompt.
        Returns condensed personality description for LLM.
        """
        if not self._loaded:
            return ""

        profile = self.profile
        comm = self.communication
        persona = self.persona

        # Build persona context
        lines = [
            f"# Agent Persona: {profile.get('name', self.agent_name)}",
            f"Instagram: @{profile.get('instagram', 'unknown')}",
            f"Age: {profile.get('age', '?')}, Location: {profile.get('location', '?')}",
            f"Profession: {profile.get('profession', {}).get('title', 'unknown')}",
            "",
            "## Personality",
            f"MBTI: {profile.get('personality', {}).get('mbti', '?')}",
            f"Core traits: {', '.join(profile.get('personality', {}).get('core_traits', []))}",
            "",
            "## Communication Style",
            f"Tone: {comm.get('tone', 'neutral')}",
            f"Energy: {comm.get('energy', 'medium')}",
            f"Emoji usage: {comm.get('characteristics', {}).get('emoji_usage', 'normal')}",
            "",
            "## Writing Rules",
        ]

        for rule in persona.get("writing_rules", []):
            lines.append(f"- {rule}")

        lines.extend([
            "",
            "## Never Use",
            ", ".join(comm.get("vocabulary", {}).get("never_use", [])),
        ])

        return "\n".join(lines)

    def get_comment_context(self, post_type: str = "general") -> str:
        """
        Get comment generation context based on post type.

        Args:
            post_type: One of 'esoteric', 'bar_content', 'general'
        """
        templates = self.engagement.get("templates", {})
        examples = self.config.get("examples", {}).get("good", [])

        context_lines = [
            "## Comment Guidelines",
            f"Message length: {self.communication.get('message_length', {}).get('comments', {})}",
            "",
            "## Template Patterns",
        ]

        # Add relevant templates
        for category, patterns in templates.items():
            if isinstance(patterns, list) and patterns:
                context_lines.append(f"### {category}")
                for p in patterns[:3]:  # limit to 3 per category
                    context_lines.append(f"- {p}")

        context_lines.extend(["", "## Good Examples"])
        for ex in examples[:4]:
            context_lines.append(f"- Context: {ex.get('context', '')}")
            context_lines.append(f"  Comment: \"{ex.get('comment', '')}\"")

        return "\n".join(context_lines)

    # =========================================================================
    # RATE LIMITING
    # =========================================================================

    def can_like(self) -> bool:
        """Check if like action is allowed within limits."""
        daily = self.limits.get("daily", {})
        hourly = self.limits.get("hourly", {})

        if self.state.likes_today >= daily.get("likes", 40):
            logger.info("Daily like limit reached")
            return False

        # TODO: Add hourly tracking
        return True

    def can_comment(self) -> bool:
        """Check if comment action is allowed within limits."""
        daily = self.limits.get("daily", {})

        if self.state.comments_today >= daily.get("comments", 8):
            logger.info("Daily comment limit reached")
            return False

        return True

    def can_follow(self) -> bool:
        """Check if follow action is allowed within limits."""
        daily = self.limits.get("daily", {})

        if self.state.follows_today >= daily.get("follows", 10):
            logger.info("Daily follow limit reached")
            return False

        return True

    def record_like(self):
        """Record a like action."""
        self.state.likes_today += 1
        self.state.actions_this_session += 1
        self.state.last_action_time = datetime.now()
        logger.debug(f"Like recorded. Today: {self.state.likes_today}")

    def record_comment(self):
        """Record a comment action."""
        self.state.comments_today += 1
        self.state.actions_this_session += 1
        self.state.last_action_time = datetime.now()
        logger.debug(f"Comment recorded. Today: {self.state.comments_today}")

    def record_follow(self):
        """Record a follow action."""
        self.state.follows_today += 1
        self.state.actions_this_session += 1
        self.state.last_action_time = datetime.now()
        logger.debug(f"Follow recorded. Today: {self.state.follows_today}")

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def is_work_session(self) -> bool:
        """
        Check if currently in work session mode (quick phone checks).
        During work: 40-60 min intervals, 10-15 min sessions, 2-4 actions.
        """
        sched = self.scheduling
        work_pattern = sched.get("work_session_pattern", {})

        if not work_pattern:
            return False

        # Check actions per session limit
        max_actions = work_pattern.get("actions_per_session", [2, 4])
        if isinstance(max_actions, list):
            max_actions = max_actions[1]  # use upper bound

        return self.state.actions_this_session >= max_actions

    def should_take_break(self) -> bool:
        """Check if agent should take a break based on session state."""
        if self.is_work_session():
            return True

        # Random breaks
        breaks = self.limits.get("breaks", {}).get("random", {})
        if breaks.get("enabled", False):
            # TODO: Implement random break logic
            pass

        return False

    def get_status(self) -> Dict[str, Any]:
        """Get current session status for monitoring."""
        return {
            "agent": self.agent_name,
            "session_start": self.state.session_start.isoformat(),
            "actions_this_session": self.state.actions_this_session,
            "likes_today": self.state.likes_today,
            "comments_today": self.state.comments_today,
            "follows_today": self.state.follows_today,
            "last_action": self.state.last_action_time.isoformat() if self.state.last_action_time else None,
            "limits": {
                "likes": f"{self.state.likes_today}/{self.limits.get('daily', {}).get('likes', 40)}",
                "comments": f"{self.state.comments_today}/{self.limits.get('daily', {}).get('comments', 8)}",
                "follows": f"{self.state.follows_today}/{self.limits.get('daily', {}).get('follows', 10)}",
            }
        }
