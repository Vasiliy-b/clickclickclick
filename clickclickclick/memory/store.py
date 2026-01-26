"""
MemoryStore - MongoDB persistence layer for agent memory.

Collections:
- viewed_posts: Posts the agent has seen
- sent_comments: Comments the agent has posted
- known_obstacles: Learned obstacle handling
- session_states: Agent session persistence
- action_logs: Raw action logs for analysis

Usage:
    store = MemoryStore("mongodb://localhost:27017", "instagram_agents")
    store.connect()

    # Save viewed post
    store.save_viewed_post(viewed_post)

    # Check if post was seen
    if store.has_seen_post(post_id):
        skip()

    # Get obstacle solution
    solution = store.get_obstacle_solution(screen_hash)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from pymongo import MongoClient, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database

from .models import ViewedPost, SentComment, KnownObstacle, SessionState

logger = logging.getLogger(__name__)


class MemoryStore:
    """
    MongoDB-backed memory store for Instagram agents.
    """

    def __init__(self, connection_string: str = "mongodb://localhost:27017", db_name: str = "instagram_agents"):
        self.connection_string = connection_string
        self.db_name = db_name
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None

    def connect(self) -> bool:
        """Connect to MongoDB."""
        try:
            self.client = MongoClient(self.connection_string)
            self.db = self.client[self.db_name]

            # Test connection
            self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB: {self.db_name}")

            # Create indexes
            self._ensure_indexes()

            return True
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
            self.client = None
            self.db = None

    def _ensure_indexes(self):
        """Create necessary indexes for performance."""
        if not self.db:
            return

        # viewed_posts indexes
        self.db.viewed_posts.create_index([("post_id", 1), ("agent_id", 1)], unique=True, sparse=True)
        self.db.viewed_posts.create_index([("username", 1)])
        self.db.viewed_posts.create_index([("timestamp", DESCENDING)])
        self.db.viewed_posts.create_index([("image_hash", 1)])

        # sent_comments indexes
        self.db.sent_comments.create_index([("agent_id", 1), ("timestamp", DESCENDING)])
        self.db.sent_comments.create_index([("target_username", 1)])
        self.db.sent_comments.create_index([("comment_text", 1)])  # for dedup

        # known_obstacles indexes
        self.db.known_obstacles.create_index([("screen_hash", 1)], unique=True)
        self.db.known_obstacles.create_index([("obstacle_type", 1)])

        # session_states indexes
        self.db.session_states.create_index([("agent_id", 1)], unique=True)

        # action_logs indexes
        self.db.action_logs.create_index([("agent_id", 1), ("timestamp", DESCENDING)])
        self.db.action_logs.create_index([("action", 1)])

        logger.debug("MongoDB indexes ensured")

    # =========================================================================
    # VIEWED POSTS
    # =========================================================================

    def save_viewed_post(self, post: ViewedPost) -> bool:
        """Save or update viewed post record."""
        if not self.db:
            return False

        try:
            self.db.viewed_posts.update_one(
                {"post_id": post.post_id, "agent_id": post.agent_id},
                {"$set": post.to_dict()},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save viewed post: {e}")
            return False

    def has_seen_post(self, post_id: str, agent_id: str) -> bool:
        """Check if agent has seen this post."""
        if not self.db:
            return False

        return self.db.viewed_posts.find_one(
            {"post_id": post_id, "agent_id": agent_id}
        ) is not None

    def has_seen_image(self, image_hash: str, agent_id: str) -> bool:
        """Check if agent has seen post with this image hash."""
        if not self.db:
            return False

        return self.db.viewed_posts.find_one(
            {"image_hash": image_hash, "agent_id": agent_id}
        ) is not None

    def get_recent_viewed(self, agent_id: str, limit: int = 100) -> List[ViewedPost]:
        """Get recently viewed posts."""
        if not self.db:
            return []

        docs = self.db.viewed_posts.find(
            {"agent_id": agent_id}
        ).sort("timestamp", DESCENDING).limit(limit)

        return [ViewedPost.from_dict(d) for d in docs]

    def get_engagement_stats(self, agent_id: str, days: int = 7) -> Dict[str, int]:
        """Get engagement statistics for last N days."""
        if not self.db:
            return {}

        since = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"agent_id": agent_id, "timestamp": {"$gte": since}}},
            {"$group": {
                "_id": None,
                "total_viewed": {"$sum": 1},
                "total_liked": {"$sum": {"$cond": ["$liked", 1, 0]}},
                "total_commented": {"$sum": {"$cond": ["$commented", 1, 0]}},
                "total_saved": {"$sum": {"$cond": ["$saved", 1, 0]}},
            }}
        ]

        result = list(self.db.viewed_posts.aggregate(pipeline))
        if result:
            return {
                "viewed": result[0].get("total_viewed", 0),
                "liked": result[0].get("total_liked", 0),
                "commented": result[0].get("total_commented", 0),
                "saved": result[0].get("total_saved", 0),
            }
        return {"viewed": 0, "liked": 0, "commented": 0, "saved": 0}

    # =========================================================================
    # SENT COMMENTS
    # =========================================================================

    def save_sent_comment(self, comment: SentComment) -> bool:
        """Save sent comment record."""
        if not self.db:
            return False

        try:
            self.db.sent_comments.insert_one(comment.to_dict())
            return True
        except Exception as e:
            logger.error(f"Failed to save sent comment: {e}")
            return False

    def has_commented_similar(self, comment_text: str, agent_id: str, hours: int = 24) -> bool:
        """Check if agent has posted similar comment recently."""
        if not self.db:
            return False

        since = datetime.utcnow() - timedelta(hours=hours)

        # Simple check: exact match
        # TODO: Add fuzzy matching for similar comments
        return self.db.sent_comments.find_one({
            "comment_text": comment_text,
            "agent_id": agent_id,
            "timestamp": {"$gte": since}
        }) is not None

    def get_recent_comments(self, agent_id: str, limit: int = 50) -> List[SentComment]:
        """Get recently sent comments."""
        if not self.db:
            return []

        docs = self.db.sent_comments.find(
            {"agent_id": agent_id}
        ).sort("timestamp", DESCENDING).limit(limit)

        return [SentComment.from_dict(d) for d in docs]

    def get_comments_to_user(self, target_username: str, agent_id: str) -> List[SentComment]:
        """Get all comments sent to specific user."""
        if not self.db:
            return []

        docs = self.db.sent_comments.find({
            "target_username": target_username,
            "agent_id": agent_id
        }).sort("timestamp", DESCENDING)

        return [SentComment.from_dict(d) for d in docs]

    # =========================================================================
    # KNOWN OBSTACLES
    # =========================================================================

    def save_obstacle(self, obstacle: KnownObstacle) -> bool:
        """Save or update known obstacle."""
        if not self.db:
            return False

        try:
            existing = self.db.known_obstacles.find_one({"screen_hash": obstacle.screen_hash})

            if existing:
                # Update existing - increment counter
                self.db.known_obstacles.update_one(
                    {"screen_hash": obstacle.screen_hash},
                    {
                        "$set": {
                            "last_seen": obstacle.last_seen,
                            "solution_action": obstacle.solution_action,
                            "solution_coords": list(obstacle.solution_coords),
                            "solution_text": obstacle.solution_text,
                            "confidence": obstacle.confidence,
                        },
                        "$inc": {"times_encountered": 1}
                    }
                )
            else:
                self.db.known_obstacles.insert_one(obstacle.to_dict())

            return True
        except Exception as e:
            logger.error(f"Failed to save obstacle: {e}")
            return False

    def get_obstacle_solution(self, screen_hash: str) -> Optional[KnownObstacle]:
        """Get known solution for obstacle by screen hash."""
        if not self.db:
            return None

        doc = self.db.known_obstacles.find_one({"screen_hash": screen_hash})
        if doc:
            return KnownObstacle.from_dict(doc)
        return None

    def get_obstacle_by_type(self, obstacle_type: str) -> List[KnownObstacle]:
        """Get all known obstacles of specific type."""
        if not self.db:
            return []

        docs = self.db.known_obstacles.find({"obstacle_type": obstacle_type})
        return [KnownObstacle.from_dict(d) for d in docs]

    def record_obstacle_solved(self, screen_hash: str) -> bool:
        """Record that obstacle was successfully solved."""
        if not self.db:
            return False

        result = self.db.known_obstacles.update_one(
            {"screen_hash": screen_hash},
            {
                "$inc": {"times_solved": 1},
                "$set": {"confidence": 0.9}  # increase confidence on success
            }
        )
        return result.modified_count > 0

    # =========================================================================
    # SESSION STATE
    # =========================================================================

    def get_session_state(self, agent_id: str) -> Optional[SessionState]:
        """Get persisted session state for agent."""
        if not self.db:
            return None

        doc = self.db.session_states.find_one({"agent_id": agent_id})
        if doc:
            state = SessionState.from_dict(doc)
            state.reset_daily_if_needed()
            return state
        return None

    def save_session_state(self, state: SessionState) -> bool:
        """Save session state."""
        if not self.db:
            return False

        try:
            state.last_active = datetime.utcnow()
            self.db.session_states.update_one(
                {"agent_id": state.agent_id},
                {"$set": state.to_dict()},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save session state: {e}")
            return False

    def increment_session_counter(self, agent_id: str, counter: str, amount: int = 1) -> bool:
        """Increment a session counter (likes_today, comments_today, etc.)."""
        if not self.db:
            return False

        valid_counters = ["likes_today", "comments_today", "follows_today",
                        "unfollows_today", "total_actions"]

        if counter not in valid_counters:
            return False

        result = self.db.session_states.update_one(
            {"agent_id": agent_id},
            {
                "$inc": {counter: amount},
                "$set": {"last_active": datetime.utcnow()}
            }
        )
        return result.modified_count > 0

    # =========================================================================
    # ACTION LOGS
    # =========================================================================

    def log_action(self, agent_id: str, action_data: Dict[str, Any]) -> bool:
        """Log an action for analysis."""
        if not self.db:
            return False

        try:
            action_data["agent_id"] = agent_id
            action_data["timestamp"] = datetime.utcnow()
            self.db.action_logs.insert_one(action_data)
            return True
        except Exception as e:
            logger.error(f"Failed to log action: {e}")
            return False

    def get_action_logs(self, agent_id: str, limit: int = 100,
                       action_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent action logs."""
        if not self.db:
            return []

        query = {"agent_id": agent_id}
        if action_filter:
            query["action"] = action_filter

        docs = self.db.action_logs.find(query).sort("timestamp", DESCENDING).limit(limit)
        return list(docs)

    # =========================================================================
    # UTILITY
    # =========================================================================

    def get_agent_summary(self, agent_id: str) -> Dict[str, Any]:
        """Get summary of agent's memory/activity."""
        if not self.db:
            return {}

        state = self.get_session_state(agent_id)
        stats = self.get_engagement_stats(agent_id, days=7)

        comments_count = self.db.sent_comments.count_documents({"agent_id": agent_id})
        obstacles_count = self.db.known_obstacles.count_documents({})

        return {
            "agent_id": agent_id,
            "session_state": state.to_dict() if state else None,
            "engagement_7d": stats,
            "total_comments": comments_count,
            "known_obstacles": obstacles_count,
        }
