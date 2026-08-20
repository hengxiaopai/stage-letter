"""Gate 3.3 durable WeChat client grant-intake evidence.

Revision ID: d33c4e8a1b60
Revises: c32a1d7e9b40
Create Date: 2026-08-20

The evidence table is operational notification state outside the Gate 1
canonical Base. It provides durable idempotency; it is not provider balance
truth and cannot mutate live truth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d33c4e8a1b60"
down_revision: Union[str, Sequence[str], None] = "c32a1d7e9b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wechat_grant_intakes",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accept', 'reject', 'ban')",
            name="ck_g33_grant_intake_decision",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "request_id", "template_id"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Gate 3.3 grant-intake migration is forward-only; create a corrective revision instead"
    )
