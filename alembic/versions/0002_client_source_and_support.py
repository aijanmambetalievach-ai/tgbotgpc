"""Two directions (purchasers, suppliers), client source, tender support.

Revision ID: 0002_source_support
Revises: 0001_consulting
Create Date: 2026-10-17

* ``users.source`` — first-touch channel from the ``/start`` link (Instagram).
* The "beginner" category is gone: such clients choose again on next /start,
  beginner-only content becomes visible to everyone.
* ``SUPPORT`` applications need no schema change (enums are VARCHAR).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_source_support"
down_revision = "0001_consulting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("source", sa.String(length=32), nullable=True))
    op.create_index("ix_users_source", "users", ["source"])
    op.execute("UPDATE users SET category = NULL WHERE category = 'BEGINNER'")
    for table in ("courses", "lessons"):
        op.execute(f"UPDATE {table} SET audience = 'ALL' WHERE audience = 'BEGINNER'")


def downgrade() -> None:
    op.drop_index("ix_users_source", table_name="users")
    op.drop_column("users", "source")
