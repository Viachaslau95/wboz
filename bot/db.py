from __future__ import annotations

import datetime
from decimal import Decimal

from app.db import Session, engine, transaction
from app.db.models import TrackedItems, Users


def _build_due_items_query():
    return (
        TrackedItems.select(
            TrackedItems.id,
            TrackedItems.user_id,
            TrackedItems.platform,
            TrackedItems.item_id,
            TrackedItems.url,
            TrackedItems.title,
            TrackedItems.last_price,
            TrackedItems.threshold,
            TrackedItems.last_checked_at,
            TrackedItems.last_threshold_notified_at,
            Users.check_interval,
        )
        .join(Users, Users.user_id == TrackedItems.user_id)
        .where(TrackedItems.is_active.is_(True))
    )


def _is_item_due(
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


def _due_item_from_row(row) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "platform": row.platform,
        "item_id": row.item_id,
        "url": row.url,
        "title": row.title,
        "last_price": row.last_price,
        "threshold": row.threshold,
        "check_interval": row.check_interval,
        "last_threshold_notified_at": row.last_threshold_notified_at,
    }


class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def init(self) -> None:
        # SQLAlchemy engine/session are initialized in app.db.
        _ = self._database_url

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
        current_price: Decimal,
        threshold: Decimal,
    ) -> int:
        async with transaction() as session:
            query = (
                TrackedItems.insert()
                .values(
                    user_id=user_id,
                    platform=platform,
                    item_id=item_id,
                    url=url,
                    title=title,
                    last_price=current_price,
                    threshold=threshold,
                )
                .returning(TrackedItems.id)
            )
            row = await session.execute(query)
            track_id = row.scalar_one()
            return int(track_id)

    async def list_user_tracks(self, user_id: int) -> list[dict]:
        async with Session() as session:
            query = (
                TrackedItems.select(
                    TrackedItems.id,
                    TrackedItems.platform,
                    TrackedItems.item_id,
                    TrackedItems.url,
                    TrackedItems.title,
                    TrackedItems.last_price,
                    TrackedItems.threshold,
                    TrackedItems.created_at,
                )
                .where((TrackedItems.user_id == user_id) & (TrackedItems.is_active.is_(True)))
                .order_by(TrackedItems.created_at.desc())
            )
            rows = (await session.execute(query)).all()
            return [
                {
                    "id": row.id,
                    "platform": row.platform,
                    "item_id": row.item_id,
                    "url": row.url,
                    "title": row.title,
                    "last_price": row.last_price,
                    "threshold": row.threshold,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    async def remove_tracking(self, user_id: int, track_id: int) -> int:
        async with transaction() as session:
            query = (
                TrackedItems.update()
                .where(
                    (TrackedItems.user_id == user_id)
                    & (TrackedItems.id == track_id)
                    & (TrackedItems.is_active.is_(True))
                )
                .values(is_active=False)
                .returning(TrackedItems.id)
            )
            result = await session.execute(query)
            return len(result.scalars().all())

    async def set_threshold(self, user_id: int, track_id: int, threshold: Decimal) -> int:
        async with transaction() as session:
            query = (
                TrackedItems.update()
                .where(
                    (TrackedItems.user_id == user_id)
                    & (TrackedItems.id == track_id)
                    & (TrackedItems.is_active.is_(True))
                )
                .values(threshold=threshold, last_threshold_notified_at=None)
                .returning(TrackedItems.id)
            )
            result = await session.execute(query)
            return len(result.scalars().all())

    async def get_user_settings(self, user_id: int) -> dict | None:
        async with Session() as session:
            query = Users.select(
                Users.user_id,
                Users.check_interval,
                Users.subscribed_until,
                Users.created_at,
            ).where(Users.user_id == user_id)
            row = (await session.execute(query)).first()
            if row is None:
                return None
            return {
                "user_id": row.user_id,
                "check_interval": row.check_interval,
                "subscribed_until": row.subscribed_until,
                "created_at": row.created_at,
            }

    async def update_user_interval(self, user_id: int, check_interval: int) -> None:
        async with transaction() as session:
            await session.execute(Users.update().where(Users.user_id == user_id).values(check_interval=check_interval))
            # Сбрасываем таймер проверок: иначе после смены интервала ждёте ещё старый «хвост» (last_check + old_interval).
            await session.execute(
                TrackedItems.update()
                .where(
                    (TrackedItems.user_id == user_id) & (TrackedItems.is_active.is_(True)),
                )
                .values(last_checked_at=None)
            )

    async def poll_due_with_backlog(
        self,
    ) -> tuple[list[dict], int, datetime.datetime | None]:
        """(due, всего треков с join на users, ближайшее last_checked+interval, если сейчас никого «по сроку»)."""
        async with Session() as session:
            query = _build_due_items_query()
            rows = (await session.execute(query)).all()
        now = datetime.datetime.now(datetime.UTC)
        due_items: list[dict] = []
        next_at_candidates: list[datetime.datetime] = []
        for row in rows:
            interval_minutes = max(int(row.check_interval), 1)
            last_checked_at = row.last_checked_at
            is_due = _is_item_due(last_checked_at, interval_minutes, now)
            if is_due:
                due_items.append(_due_item_from_row(row))
            elif last_checked_at is not None:
                nxt = last_checked_at + datetime.timedelta(minutes=interval_minutes)
                next_at_candidates.append(nxt)
        earliest_next: datetime.datetime | None = None
        if next_at_candidates:
            earliest_next = min(x.astimezone(datetime.UTC) for x in next_at_candidates)
        return due_items, len(rows), earliest_next

    async def get_due_items(self) -> list[dict]:
        due, _, _ = await self.poll_due_with_backlog()
        return due

    async def apply_poll_result(
        self,
        track_id: int,
        current_price: Decimal,
        title: str | None,
        *,
        price_above_threshold: bool,
        sent_threshold_alert: bool,
    ) -> None:
        """Обновляет last_price и last_checked_at; last_threshold_notified_at — по сценарию опроса."""
        now = datetime.datetime.now(datetime.UTC)
        values: dict = {
            "last_price": current_price,
            "last_checked_at": now,
        }
        if title:
            values["title"] = title
        if price_above_threshold:
            values["last_threshold_notified_at"] = None
        elif sent_threshold_alert:
            values["last_threshold_notified_at"] = now
        async with transaction() as session:
            await session.execute(TrackedItems.update().where(TrackedItems.id == track_id).values(**values))
