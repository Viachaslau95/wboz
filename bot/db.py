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
        threshold: int,
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

    async def set_threshold(self, user_id: int, track_id: int, threshold: int) -> int:
        async with transaction() as session:
            query = (
                TrackedItems.update()
                .where(
                    (TrackedItems.user_id == user_id)
                    & (TrackedItems.id == track_id)
                    & (TrackedItems.is_active.is_(True))
                )
                .values(threshold=threshold)
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
            query = Users.update().where(Users.user_id == user_id).values(check_interval=check_interval)
            await session.execute(query)

    async def get_due_items(self) -> list[dict]:
        async with Session() as session:
            query = _build_due_items_query()
            rows = (await session.execute(query)).all()
            now = datetime.datetime.now(datetime.UTC)
            due_items: list[dict] = []
            for row in rows:
                interval_minutes = max(int(row.check_interval), 3)
                last_checked_at = row.last_checked_at
                is_due = _is_item_due(last_checked_at, interval_minutes, now)
                if is_due:
                    due_items.append(
                        {
                            "id": row.id,
                            "user_id": row.user_id,
                            "platform": row.platform,
                            "item_id": row.item_id,
                            "url": row.url,
                            "title": row.title,
                            "last_price": row.last_price,
                            "threshold": row.threshold,
                            "check_interval": row.check_interval,
                        }
                    )
            return due_items

    async def mark_checked(self, track_id: int) -> None:
        async with transaction() as session:
            query = (
                TrackedItems.update()
                .where(TrackedItems.id == track_id)
                .values(last_checked_at=datetime.datetime.now(datetime.UTC))
            )
            await session.execute(query)

    async def update_last_price(self, track_id: int, current_price: Decimal, title: str | None = None) -> None:
        async with transaction() as session:
            values = {
                "last_price": current_price,
                "last_checked_at": datetime.datetime.now(datetime.UTC),
            }
            if title:
                values["title"] = title

            query = TrackedItems.update().where(TrackedItems.id == track_id).values(**values)
            await session.execute(query)
