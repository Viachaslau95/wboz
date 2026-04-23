from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Row
from sqlalchemy.sql.selectable import Select

from app.db import Session, engine, transaction
from app.db.models import TrackedItems, Users
from bot.schemas import DueTrackItem, UserSettings, UserTrackListItem


def _select_due_tracks() -> Select[Any]:
    """Join active tracks with users; use table columns for static typing with Pyright."""
    t = TrackedItems.__table__.c
    u = Users.__table__.c
    return (
        select(
            t.id,
            t.user_id,
            t.platform,
            t.item_id,
            t.url,
            t.title,
            t.api_price,
            t.api_baseline_price,
            t.threshold_price,
            t.last_checked_at,
            t.last_threshold_notified_at,
            t.last_drop5_notified_at,
            t.last_approach_notified_at,
            u.check_interval,
        )
        .select_from(TrackedItems)
        .join(Users, Users.user_id == t.user_id)
        .where(t.is_active.is_(True))
    )


def is_track_due(
    last_checked_at: datetime.datetime | None,
    interval_minutes: int,
    now: datetime.datetime,
) -> bool:
    if last_checked_at is None:
        return True
    if last_checked_at.tzinfo is None:
        now_for_compare = now.replace(tzinfo=None)
    else:
        now_for_compare = now
    return last_checked_at + datetime.timedelta(minutes=interval_minutes) <= now_for_compare


def _due_item_from_row(row: Row) -> DueTrackItem:
    return DueTrackItem(
        id=row.id,
        user_id=row.user_id,
        platform=row.platform,
        item_id=row.item_id,
        url=row.url,
        title=row.title,
        api_price=row.api_price,
        api_baseline_price=row.api_baseline_price,
        threshold_price=row.threshold_price,
        check_interval=int(row.check_interval),
        last_threshold_notified_at=row.last_threshold_notified_at,
        last_drop5_notified_at=row.last_drop5_notified_at,
        last_approach_notified_at=row.last_approach_notified_at,
    )


class Database:
    async def init(self) -> None:
        pass

    async def close(self) -> None:
        await engine.dispose()

    async def ensure_user(self, user_id: int, username: str | None, default_interval: int) -> None:
        async with transaction() as session:
            query = Users.insert().values(
                user_id=user_id,
                username=username,
                check_interval=default_interval,
            )
            query = query.on_conflict_do_update(
                index_elements=[Users.user_id],
                set_={"username": query.excluded.username},
            )
            await session.execute(query)

    async def add_tracking(
        self,
        user_id: int,
        platform: str,
        item_id: str,
        url: str,
        title: str,
        manual_price: Decimal,
        threshold_price: Decimal,
    ) -> int:
        async with transaction() as session:
            q = (
                TrackedItems.insert()
                .values(
                    user_id=user_id,
                    platform=platform,
                    item_id=item_id,
                    url=url,
                    title=title,
                    api_price=manual_price,
                    manual_price=manual_price,
                    threshold_price=threshold_price,
                )
                .returning(TrackedItems.id)
            )
            result = await session.execute(q)
            return int(result.scalar_one())

    async def list_user_tracks(self, user_id: int) -> list[UserTrackListItem]:
        async with Session() as session:
            stmt = (
                select(
                    TrackedItems.id,
                    TrackedItems.platform,
                    TrackedItems.item_id,
                    TrackedItems.url,
                    TrackedItems.title,
                    TrackedItems.api_price,
                    TrackedItems.manual_price,
                    TrackedItems.api_baseline_price,
                    TrackedItems.threshold_price,
                    TrackedItems.created_at,
                )
                .where(TrackedItems.user_id == user_id, TrackedItems.is_active.is_(True))
                .order_by(TrackedItems.created_at.desc())
            )
            rows = (await session.execute(stmt)).all()
        return [UserTrackListItem.model_validate(row._mapping) for row in rows]

    async def remove_tracking(self, user_id: int, track_id: int) -> int:
        async with transaction() as session:
            q = (
                update(TrackedItems)
                .where(
                    TrackedItems.user_id == user_id,
                    TrackedItems.id == track_id,
                    TrackedItems.is_active.is_(True),
                )
                .values(is_active=False)
                .returning(TrackedItems.id)
            )
            result = await session.execute(q)
            return len(result.scalars().all())

    async def set_threshold(self, user_id: int, track_id: int, threshold_price: Decimal) -> int:
        async with transaction() as session:
            q = (
                update(TrackedItems)
                .where(
                    TrackedItems.user_id == user_id,
                    TrackedItems.id == track_id,
                    TrackedItems.is_active.is_(True),
                )
                .values(
                    threshold_price=threshold_price,
                    last_threshold_notified_at=None,
                    last_drop5_notified_at=None,
                    last_approach_notified_at=None,
                )
                .returning(TrackedItems.id)
            )
            result = await session.execute(q)
            return len(result.scalars().all())

    async def get_user_settings(self, user_id: int) -> UserSettings | None:
        async with Session() as session:
            stmt = select(
                Users.user_id,
                Users.check_interval,
                Users.subscribed_until,
                Users.created_at,
            ).where(Users.user_id == user_id)
            row = (await session.execute(stmt)).first()
        if row is None:
            return None
        return UserSettings.model_validate(row._mapping)

    async def update_user_interval(self, user_id: int, check_interval: int) -> None:
        async with transaction() as session:
            await session.execute(update(Users).where(Users.user_id == user_id).values(check_interval=check_interval))
            await session.execute(
                update(TrackedItems)
                .where(TrackedItems.user_id == user_id, TrackedItems.is_active.is_(True))
                .values(last_checked_at=None)
            )

    async def poll_due_with_backlog(
        self,
    ) -> tuple[list[DueTrackItem], int, datetime.datetime | None]:
        """
        Return (items due for poll now, count of all active rows,
        earliest next poll time if none are due).
        """
        async with Session() as session:
            stmt = _select_due_tracks()
            rows = (await session.execute(stmt)).all()
        now = datetime.datetime.now(datetime.UTC)
        due: list[DueTrackItem] = []
        next_candidates: list[datetime.datetime] = []
        for row in rows:
            interval = max(int(row.check_interval), 1)
            last_checked = row.last_checked_at
            if is_track_due(last_checked, interval, now):
                due.append(_due_item_from_row(row))
            elif last_checked is not None:
                nxt = last_checked + datetime.timedelta(minutes=interval)
                next_candidates.append(nxt)
        earliest: datetime.datetime | None = None
        if next_candidates:
            earliest = min(x.astimezone(datetime.UTC) for x in next_candidates)
        return due, len(rows), earliest

    async def apply_poll_result(
        self,
        track_id: int,
        api_price: Decimal,
        title: str | None,
        *,
        price_above_threshold: bool,
        sent_threshold_alert: bool,
        set_api_baseline_price_if_missing: bool = False,
    ) -> None:
        now = datetime.datetime.now(datetime.UTC)
        values: dict = {
            "api_price": api_price,
            "last_checked_at": now,
        }
        if title:
            values["title"] = title
        if set_api_baseline_price_if_missing:
            values["api_baseline_price"] = api_price
        if price_above_threshold:
            values["last_threshold_notified_at"] = None
        elif sent_threshold_alert:
            values["last_threshold_notified_at"] = now
        async with transaction() as session:
            await session.execute(update(TrackedItems).where(TrackedItems.id == track_id).values(**values))

    async def record_secondary_alert_sent(self, track_id: int, kind: str) -> None:
        if kind not in ("drop5", "approach"):
            msg = f"unknown secondary alert kind: {kind}"
            raise ValueError(msg)
        now = datetime.datetime.now(datetime.UTC)
        column = "last_drop5_notified_at" if kind == "drop5" else "last_approach_notified_at"
        async with transaction() as session:
            await session.execute(update(TrackedItems).where(TrackedItems.id == track_id).values(**{column: now}))
