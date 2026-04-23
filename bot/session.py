"""In-memory registration / dialog state (single process; not persistent)."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.schemas import PendingTrackDraft


@dataclass
class RegistrationFlow:
    """Per-user flags and draft data for the «add track» wizard."""

    selected_platform: dict[int, str] = field(default_factory=dict)
    awaiting_link: set[int] = field(default_factory=set)
    awaiting_threshold: set[int] = field(default_factory=set)
    awaiting_price_input: set[int] = field(default_factory=set)
    pending_track: dict[int, PendingTrackDraft] = field(default_factory=dict)

    def clear(self, user_id: int) -> None:
        """Reset all registration state (e.g. /start, «Назад»)."""
        self.selected_platform.pop(user_id, None)
        self.awaiting_link.discard(user_id)
        self.awaiting_threshold.discard(user_id)
        self.awaiting_price_input.discard(user_id)
        self.pending_track.pop(user_id, None)

    def enter_platform_menu(self, user_id: int, platform: str) -> None:
        """User chose a marketplace; drop wizard draft but keep platform."""
        self.awaiting_link.discard(user_id)
        self.awaiting_threshold.discard(user_id)
        self.awaiting_price_input.discard(user_id)
        self.pending_track.pop(user_id, None)
        self.selected_platform[user_id] = platform


flow = RegistrationFlow()
