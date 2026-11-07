"""widen hash columns that hold "sha256:<64 hex>" (71 chars)

simulations.harness_commit was VARCHAR(64) and reports.content_hash VARCHAR(66); Postgres rejected
the 71-character values (SQLite does not enforce lengths, so local runs did not notice).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("simulations") as b:
        b.alter_column("harness_commit", type_=sa.String(length=128), existing_type=sa.String(length=64))
    with op.batch_alter_table("reports") as b:
        b.alter_column(
            "content_hash", type_=sa.String(length=128), existing_type=sa.String(length=66), existing_nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("reports") as b:
        b.alter_column(
            "content_hash", type_=sa.String(length=66), existing_type=sa.String(length=128), existing_nullable=False
        )
    with op.batch_alter_table("simulations") as b:
        b.alter_column("harness_commit", type_=sa.String(length=64), existing_type=sa.String(length=128))
