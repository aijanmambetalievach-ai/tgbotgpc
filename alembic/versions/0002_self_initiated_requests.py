"""self-initiated purchase requests

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25

Lets a purchaser start a request on their own, without waiting for a
procurement: ``procurement_id`` becomes nullable and ``subject`` describes what
the purchaser needs. A check constraint keeps every row meaningful — a request
must belong to a procurement or carry a subject.

Note on the existing ``uq_purchase_requests_pair`` constraint: PostgreSQL
treats NULLs as distinct, so "one request per purchaser per procurement" is
still enforced while any number of self-initiated requests stay possible.
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
    op.add_column(
        "purchase_requests",
        sa.Column("subject", sa.String(length=300), nullable=True),
    )
    op.alter_column(
        "purchase_requests",
        "procurement_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.create_check_constraint(
        "procurement_or_subject",
        "purchase_requests",
        "procurement_id IS NOT NULL OR subject IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_purchase_requests_procurement_or_subject",
        "purchase_requests",
        type_="check",
    )
    # Self-initiated requests cannot be represented by the old schema.
    op.execute("DELETE FROM purchase_requests WHERE procurement_id IS NULL")
    op.alter_column(
        "purchase_requests",
        "procurement_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_column("purchase_requests", "subject")
