"""
Anti-flood / anti-spam tracker.
Tracks messages per user per chat in a rolling time window.
"""
from collections import defaultdict, deque
from time import time


class FloodTracker:
    def __init__(self, max_messages: int = 5, window_seconds: int = 5):
        self.max_messages = max_messages
        self.window = window_seconds
        # { (user_id, chat_id): deque of timestamps }
        self._history: dict[tuple, deque] = defaultdict(deque)

    def is_flood(self, user_id: int, chat_id: int) -> bool:
        key = (user_id, chat_id)
        now = time()
        q = self._history[key]

        # Evict old entries
        while q and now - q[0] > self.window:
            q.popleft()

        q.append(now)
        return len(q) > self.max_messages

    def reset(self, user_id: int, chat_id: int) -> None:
        key = (user_id, chat_id)
        self._history.pop(key, None)


# Singleton used across handlers
flood_tracker = FloodTracker()
