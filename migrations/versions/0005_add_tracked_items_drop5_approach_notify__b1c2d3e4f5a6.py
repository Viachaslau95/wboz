"""add last_drop5_notified_at and last_approach_notified_at

Revision ID: b1c2d3e4f5a6
Revises: a8b3c4d5e6f7
Create Date: 2026-04-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a8b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tracked_items",
        sa.Column("last_drop5_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tracked_items",
        sa.Column("last_approach_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracked_items", "last_approach_notified_at")
    op.drop_column("tracked_items", "last_drop5_notified_at")
