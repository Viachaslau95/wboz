"""0001_init schema (clean baseline)

Revision ID: b18d263e0920
Revises:
Create Date: 2026-04-17 17:03:09.911590

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b18d263e0920"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("subscribed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_interval", sa.Integer(), server_default="30", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "tracked_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("api_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("api_baseline_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("manual_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("threshold_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_threshold_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_drop5_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_approach_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tracked_items_active", "tracked_items", ["is_active", "last_checked_at"], unique=False)
    op.create_index("idx_tracked_items_user", "tracked_items", ["user_id", "is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_tracked_items_user", table_name="tracked_items")
    op.drop_index("idx_tracked_items_active", table_name="tracked_items")
    op.drop_table("tracked_items")
    op.drop_table("users")
