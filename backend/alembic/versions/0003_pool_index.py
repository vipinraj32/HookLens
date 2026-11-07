"""pool index: hooked v4 pools from immutable Initialize logs, with a per-chain cursor

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pool_index",
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("pool_id", sa.String(length=66), nullable=False),
        sa.Column("hooks", sa.String(length=42), nullable=False),
        sa.Column("currency0", sa.String(length=42), nullable=False),
        sa.Column("currency1", sa.String(length=42), nullable=False),
        sa.Column("fee", sa.Integer(), nullable=False),
        sa.Column("tick_spacing", sa.Integer(), nullable=False),
        sa.Column("init_sqrt_price_x96", sa.String(length=80), nullable=False),
        sa.Column("init_tick", sa.Integer(), nullable=False),
        sa.Column("init_block", sa.Integer(), nullable=False),
        sa.Column("init_tx", sa.String(length=66), nullable=True),
        sa.PrimaryKeyConstraint("chain_id", "pool_id"),
    )
    op.create_index("ix_pool_index_chain_hooks", "pool_index", ["chain_id", "hooks"])
    op.create_index("ix_pool_index_init_block", "pool_index", ["init_block"])
    op.create_table(
        "pool_index_cursor",
        sa.Column("chain_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("pool_manager", sa.String(length=42), nullable=False),
        sa.Column("from_block", sa.Integer(), nullable=False),
        sa.Column("scanned_to", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("chain_id"),
    )


def downgrade() -> None:
    op.drop_table("pool_index_cursor")
    op.drop_index("ix_pool_index_init_block", table_name="pool_index")
    op.drop_index("ix_pool_index_chain_hooks", table_name="pool_index")
    op.drop_table("pool_index")
