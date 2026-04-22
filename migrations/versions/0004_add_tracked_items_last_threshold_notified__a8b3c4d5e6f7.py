"""add tracked_items.last_threshold_notified_at

Revision ID: a8b3c4d5e6f7
Revises: f1ba500d7847
Create Date: 2026-04-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a8b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1ba500d7847"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tracked_items",
        sa.Column("last_threshold_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracked_items", "last_threshold_notified_at")
