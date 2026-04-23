"""0002_add active item unique constraint

Revision ID: 2d4f3d9a1cbe
Revises: b18d263e0920
Create Date: 2026-04-23
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "2d4f3d9a1cbe"
down_revision: Union[str, Sequence[str], None] = "b18d263e0920"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep only the newest active row per (user_id, item_id); deactivate older duplicates.
    op.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, item_id
                        ORDER BY id DESC
                    ) AS rn
                FROM tracked_items
                WHERE is_active = TRUE
            )
            UPDATE tracked_items t
            SET is_active = FALSE
            FROM ranked r
            WHERE t.id = r.id AND r.rn > 1
            """))
    op.create_index(
        "uq_tracked_items_user_item_active",
        "tracked_items",
        ["user_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_tracked_items_user_item_active", table_name="tracked_items")
