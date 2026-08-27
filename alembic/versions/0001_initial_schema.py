"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-22

Creates the full MVP schema: users, invites, procurements, participants,
purchase requests and items, status history, audit log and the number
counters used for concurrency-safe TENDER-/REQ- numbering.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLE = sa.Enum(
    "ADMIN",
    "TENDER_EMPLOYEE",
    "PURCHASER",
    native_enum=False,
    length=32,
    name="user_role",
)
PROCUREMENT_STATUS = sa.Enum(
    "DRAFT",
    "OPEN",
    "CLOSED",
    "CANCELLED",
    "COMPLETED",
    native_enum=False,
    length=32,
    name="procurement_status",
)
PARTICIPANT_MODE = sa.Enum(
    "ALL_ACTIVE",
    "MANUAL",
    native_enum=False,
    length=32,
    name="participant_selection_mode",
)
REQUEST_STATUS = sa.Enum(
    "DRAFT",
    "SUBMITTED",
    "VIEWED",
    "IN_PROGRESS",
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
    native_enum=False,
    length=32,
    name="purchase_request_status",
)


def upgrade() -> None:
    # --- users ------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=64), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_users_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    # `unique=True` + `index=True` on the model produces a single UNIQUE INDEX.
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_role_is_active", "users", ["role", "is_active"])
    op.create_index("ix_users_created_by", "users", ["created_by"])

    # --- number counters --------------------------------------------------
    op.create_table(
        "number_counters",
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("current_value", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("scope", "year", name="pk_number_counters"),
    )

    # --- invites ----------------------------------------------------------
    op.create_table(
        "invites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_invites_created_by_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["used_by_user_id"],
            ["users.id"],
            name="fk_invites_used_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invites"),
    )
    op.create_index("ix_invites_code", "invites", ["code"], unique=True)
    op.create_index("ix_invites_created_by", "invites", ["created_by"])
    op.create_index("ix_invites_expires_at", "invites", ["expires_at"])

    # --- procurements -----------------------------------------------------
    op.create_table(
        "procurements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("procurement_number", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", PROCUREMENT_STATUS, nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("participant_mode", PARTICIPANT_MODE, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_procurements_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_procurements"),
        sa.UniqueConstraint(
            "procurement_number", name="uq_procurements_procurement_number"
        ),
    )
    op.create_index("ix_procurements_status", "procurements", ["status"])
    op.create_index("ix_procurements_deadline", "procurements", ["deadline"])
    op.create_index("ix_procurements_created_by", "procurements", ["created_by"])
    op.create_index(
        "ix_procurements_status_deadline", "procurements", ["status", "deadline"]
    )

    # --- participants -----------------------------------------------------
    op.create_table(
        "procurement_participants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("procurement_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["procurement_id"],
            ["procurements.id"],
            name="fk_procurement_participants_procurement_id_procurements",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_procurement_participants_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_procurement_participants"),
        sa.UniqueConstraint(
            "procurement_id", "user_id", name="uq_procurement_participants_pair"
        ),
    )
    op.create_index(
        "ix_procurement_participants_procurement_id",
        "procurement_participants",
        ["procurement_id"],
    )
    op.create_index(
        "ix_procurement_participants_user_id", "procurement_participants", ["user_id"]
    )

    # --- purchase requests ------------------------------------------------
    op.create_table(
        "purchase_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_number", sa.String(length=32), nullable=True),
        sa.Column("procurement_id", sa.BigInteger(), nullable=False),
        sa.Column("purchaser_id", sa.BigInteger(), nullable=False),
        sa.Column("status", REQUEST_STATUS, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["procurement_id"],
            ["procurements.id"],
            name="fk_purchase_requests_procurement_id_procurements",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchaser_id"],
            ["users.id"],
            name="fk_purchase_requests_purchaser_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_requests"),
        sa.UniqueConstraint("request_number", name="uq_purchase_requests_request_number"),
        sa.UniqueConstraint(
            "procurement_id", "purchaser_id", name="uq_purchase_requests_pair"
        ),
    )
    op.create_index("ix_purchase_requests_status", "purchase_requests", ["status"])
    op.create_index(
        "ix_purchase_requests_procurement_id", "purchase_requests", ["procurement_id"]
    )
    op.create_index(
        "ix_purchase_requests_purchaser_id", "purchase_requests", ["purchaser_id"]
    )
    op.create_index(
        "ix_purchase_requests_submitted_at", "purchase_requests", ["submitted_at"]
    )
    op.create_index(
        "ix_purchase_requests_procurement_status",
        "purchase_requests",
        ["procurement_id", "status"],
    )

    # --- purchase request items -------------------------------------------
    op.create_table(
        "purchase_request_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("purchase_request_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["purchase_request_id"],
            ["purchase_requests.id"],
            name="fk_purchase_request_items_purchase_request_id_purchase_requests",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_request_items"),
        sa.UniqueConstraint(
            "purchase_request_id", "position", name="uq_purchase_request_items_position"
        ),
    )
    op.create_index(
        "ix_purchase_request_items_purchase_request_id",
        "purchase_request_items",
        ["purchase_request_id"],
    )
    op.create_index(
        "ix_purchase_request_items_normalized_name_unit",
        "purchase_request_items",
        ["normalized_name", "unit"],
    )

    # --- status history ---------------------------------------------------
    op.create_table(
        "status_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("purchase_request_id", sa.BigInteger(), nullable=False),
        sa.Column("old_status", REQUEST_STATUS, nullable=True),
        sa.Column("new_status", REQUEST_STATUS, nullable=False),
        sa.Column("changed_by", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["purchase_request_id"],
            ["purchase_requests.id"],
            name="fk_status_history_purchase_request_id_purchase_requests",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_status_history_changed_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_status_history"),
    )
    op.create_index(
        "ix_status_history_purchase_request_id", "status_history", ["purchase_request_id"]
    )
    op.create_index("ix_status_history_created_at", "status_history", ["created_at"])

    # --- audit log --------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_logs_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("status_history")
    op.drop_table("purchase_request_items")
    op.drop_table("purchase_requests")
    op.drop_table("procurement_participants")
    op.drop_table("procurements")
    op.drop_table("invites")
    op.drop_table("number_counters")
    op.drop_table("users")
