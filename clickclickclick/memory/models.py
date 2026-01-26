"""
Memory Models - Data structures for agent memory.

These models define what the agent remembers:
- Viewed posts (to avoid re-engaging)
- Sent comments (for deduplication and style analysis)
- Known obstacles (learned popup handling)
- Session state (persistence across restarts)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class ViewedPost:
    """
    Record of a viewed Instagram post.
    Used to avoid re-engaging with same content.
    """
    post_id: str  # Instagram post ID if available
    username: str  # Post author
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Engagement record
    liked: bool = False
    commented: bool = False
    saved: bool = False

    # Content analysis (from LLM)
    content_type: str = ""  # esoteric, bar, general
    relevance_score: float = 0.0  # 0-1, how relevant to agent's interests

    # For deduplication
    image_hash: str = ""  # perceptual hash of post image
    caption_preview: str = ""  # first 100 chars of caption

    agent_id: str = ""  # which agent viewed this

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "username": self.username,
            "timestamp": self.timestamp,
            "liked": self.liked,
            "commented": self.commented,
            "saved": self.saved,
            "content_type": self.content_type,
            "relevance_score": self.relevance_score,
            "image_hash": self.image_hash,
            "caption_preview": self.caption_preview,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ViewedPost":
        return cls(
            post_id=data.get("post_id", ""),
            username=data.get("username", ""),
            timestamp=data.get("timestamp", datetime.utcnow()),
            liked=data.get("liked", False),
            commented=data.get("commented", False),
            saved=data.get("saved", False),
            content_type=data.get("content_type", ""),
            relevance_score=data.get("relevance_score", 0.0),
            image_hash=data.get("image_hash", ""),
            caption_preview=data.get("caption_preview", ""),
            agent_id=data.get("agent_id", ""),
        )


@dataclass
class SentComment:
    """
    Record of a comment sent by agent.
    Used for style consistency and deduplication.
    """
    comment_text: str
    target_username: str
    target_post_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Context
    post_context: str = ""  # what the post was about
    trigger_type: str = ""  # what made agent comment (esoteric, bar, etc)

    # Quality tracking
    engagement_received: int = 0  # likes on comment
    reply_received: bool = False

    agent_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comment_text": self.comment_text,
            "target_username": self.target_username,
            "target_post_id": self.target_post_id,
            "timestamp": self.timestamp,
            "post_context": self.post_context,
            "trigger_type": self.trigger_type,
            "engagement_received": self.engagement_received,
            "reply_received": self.reply_received,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SentComment":
        return cls(
            comment_text=data.get("comment_text", ""),
            target_username=data.get("target_username", ""),
            target_post_id=data.get("target_post_id", ""),
            timestamp=data.get("timestamp", datetime.utcnow()),
            post_context=data.get("post_context", ""),
            trigger_type=data.get("trigger_type", ""),
            engagement_received=data.get("engagement_received", 0),
            reply_received=data.get("reply_received", False),
            agent_id=data.get("agent_id", ""),
        )


@dataclass
class KnownObstacle:
    """
    Record of a learned obstacle and how to handle it.
    Obstacle = unexpected popup, dialog, error state.
    """
    obstacle_type: str  # login_popup, rate_limit, notification_prompt, etc
    screen_hash: str  # hash of accessibility tree when obstacle appeared

    # Solution
    solution_action: str  # tap_not_now, press_back, wait, etc
    solution_coords: tuple = (0, 0)  # coordinates if needed
    solution_text: str = ""  # text to tap if text-based

    # Stats
    times_encountered: int = 1
    times_solved: int = 0
    last_seen: datetime = field(default_factory=datetime.utcnow)

    # Learning
    learned_from: str = ""  # manual, llm_suggestion, trial_and_error
    confidence: float = 0.5  # 0-1, how confident we are in solution

    def to_dict(self) -> Dict[str, Any]:
        return {
            "obstacle_type": self.obstacle_type,
            "screen_hash": self.screen_hash,
            "solution_action": self.solution_action,
            "solution_coords": list(self.solution_coords),
            "solution_text": self.solution_text,
            "times_encountered": self.times_encountered,
            "times_solved": self.times_solved,
            "last_seen": self.last_seen,
            "learned_from": self.learned_from,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnownObstacle":
        return cls(
            obstacle_type=data.get("obstacle_type", ""),
            screen_hash=data.get("screen_hash", ""),
            solution_action=data.get("solution_action", ""),
            solution_coords=tuple(data.get("solution_coords", [0, 0])),
            solution_text=data.get("solution_text", ""),
            times_encountered=data.get("times_encountered", 1),
            times_solved=data.get("times_solved", 0),
            last_seen=data.get("last_seen", datetime.utcnow()),
            learned_from=data.get("learned_from", ""),
            confidence=data.get("confidence", 0.5),
        )


@dataclass
class SessionState:
    """
    Persistent session state for agent.
    Survives restarts.
    """
    agent_id: str
    last_active: datetime = field(default_factory=datetime.utcnow)

    # Daily counters (reset at midnight)
    date: str = ""  # YYYY-MM-DD
    likes_today: int = 0
    comments_today: int = 0
    follows_today: int = 0
    unfollows_today: int = 0

    # Session counters
    total_sessions: int = 0
    total_actions: int = 0

    # Current state
    current_task: str = ""  # what agent is doing
    last_error: str = ""
    consecutive_errors: int = 0

    # Cooldown
    cooldown_until: Optional[datetime] = None
    cooldown_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "last_active": self.last_active,
            "date": self.date,
            "likes_today": self.likes_today,
            "comments_today": self.comments_today,
            "follows_today": self.follows_today,
            "unfollows_today": self.unfollows_today,
            "total_sessions": self.total_sessions,
            "total_actions": self.total_actions,
            "current_task": self.current_task,
            "last_error": self.last_error,
            "consecutive_errors": self.consecutive_errors,
            "cooldown_until": self.cooldown_until,
            "cooldown_reason": self.cooldown_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(
            agent_id=data.get("agent_id", ""),
            last_active=data.get("last_active", datetime.utcnow()),
            date=data.get("date", ""),
            likes_today=data.get("likes_today", 0),
            comments_today=data.get("comments_today", 0),
            follows_today=data.get("follows_today", 0),
            unfollows_today=data.get("unfollows_today", 0),
            total_sessions=data.get("total_sessions", 0),
            total_actions=data.get("total_actions", 0),
            current_task=data.get("current_task", ""),
            last_error=data.get("last_error", ""),
            consecutive_errors=data.get("consecutive_errors", 0),
            cooldown_until=data.get("cooldown_until"),
            cooldown_reason=data.get("cooldown_reason", ""),
        )

    def reset_daily_if_needed(self):
        """Reset daily counters if date changed."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self.date != today:
            self.date = today
            self.likes_today = 0
            self.comments_today = 0
            self.follows_today = 0
            self.unfollows_today = 0

    def is_in_cooldown(self) -> bool:
        """Check if agent is in cooldown period."""
        if not self.cooldown_until:
            return False
        return datetime.utcnow() < self.cooldown_until
