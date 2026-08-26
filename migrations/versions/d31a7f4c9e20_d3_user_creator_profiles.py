"""Add private Creator-level profiles for D3.

Revision ID: d31a7f4c9e20
Revises: c82e7a4d1f30
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d31a7f4c9e20"
down_revision: Union[str, Sequence[str], None] = "c82e7a4d1f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_creator_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("user_alias", sa.String(length=128)),
        sa.Column("note", sa.Text()),
        sa.Column("group_name", sa.String(length=64)),
        sa.Column(
            "user_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("reference_schedule", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.UniqueConstraint("user_id", "creator_id", name="uq_d3_profile_user_creator"),
    )
    op.create_index("idx_d3_profile_creator", "user_creator_profiles", ["creator_id"])


def downgrade() -> None:
    op.drop_index("idx_d3_profile_creator", table_name="user_creator_profiles")
    op.drop_table("user_creator_profiles")
