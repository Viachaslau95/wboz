"""add tracked_items.initial_price

Revision ID: d4e5f6a7b8c9
Revises: b1c2d3e4f5a6
Create Date: 2026-04-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tracked_items", sa.Column("initial_price", sa.Numeric(12, 2), nullable=True))
    op.execute(sa.text("UPDATE tracked_items SET initial_price = last_price WHERE initial_price IS NULL"))
    op.alter_column("tracked_items", "initial_price", nullable=False)


def downgrade() -> None:
    op.drop_column("tracked_items", "initial_price")
