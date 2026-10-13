"""In-app notification helpers.

CONVENTION (follow this for any new notification type):
- Each notifier is a plain function `notify_<event>(user_id: str, **kwargs) -> None`.
- On failure to deliver it raises `NotificationError(event=..., message=...)`.
- Register the notifier in the `NOTIFIERS` dict at the bottom so the event
  dispatcher picks it up automatically.  Do NOT call notifiers directly from
  the dispatcher; it iterates `NOTIFIERS`.
"""

from __future__ import annotations


class NotificationError(Exception):
    def __init__(self, event: str, message: str) -> None:
        super().__init__(message)
        self.event = event
        self.message = message


def notify_welcome(user_id: str, **kwargs) -> None:
    """Send a welcome notification when a new account is created."""
    if not user_id:
        raise NotificationError(event="welcome", message="user_id is required.")
    # Stubbed: in production this would queue a delivery task.
    print(f"[NOTIFY] welcome -> {user_id}")


# The event dispatcher iterates this registry.  Add new notifiers here.
NOTIFIERS = {
    "welcome": notify_welcome,
}
