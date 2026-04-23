"""Pydantic DTOs for the database layer and scheduler."""

from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DueTrackItem(BaseModel):
    """A tracked product row with user interval for the price poll / scheduler."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    user_id: int
    platform: str
    item_id: str
    url: str
    title: str | None
    last_price: Decimal
    initial_price: Decimal
    threshold: Decimal
    check_interval: int
    last_threshold_notified_at: datetime.datetime | None = None
    last_drop5_notified_at: datetime.datetime | None = None
    last_approach_notified_at: datetime.datetime | None = None


class UserTrackListItem(BaseModel):
    """One row in /mytrack list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    platform: str
    item_id: str
    url: str
    title: str | None
    last_price: Decimal
    threshold: Decimal
    created_at: datetime.datetime


class PendingTrackDraft(BaseModel):
    """In-memory data while the user adds a product (before the row is saved)."""

    model_config = ConfigDict(extra="forbid")

    platform: str
    item_id: str
    url: str
    name: str
    price: Decimal


class UserSettings(BaseModel):
    """Per-user row used by /settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: int
    check_interval: int
    subscribed_until: datetime.datetime | None
    created_at: datetime.datetime
