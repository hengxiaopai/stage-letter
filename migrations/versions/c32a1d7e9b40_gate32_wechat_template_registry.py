"""Gate 3.2 durable WeChat notification-template registry.

Revision ID: c32a1d7e9b40
Revises: b25d4e9c7a12
Create Date: 2026-08-20

Template configuration is notification operational state. It remains outside
the frozen Gate 1 canonical Base and cannot represent or mutate live truth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c32a1d7e9b40"
down_revision: Union[str, Sequence[str], None] = "b25d4e9c7a12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wechat_notification_templates",
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_source", sa.String(length=32), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.Column("disabled_reason", sa.String(length=64), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('ENABLED', 'DISABLED')",
            name="ck_g32_template_state",
        ),
        sa.CheckConstraint(
            "state_source IN ('REGISTRATION', 'PROVIDER_40037', 'ADMINISTRATOR')",
            name="ck_g32_template_state_source",
        ),
        sa.CheckConstraint(
            "(state = 'ENABLED' AND disabled_reason IS NULL AND disabled_at IS NULL) "
            "OR (state = 'DISABLED' AND disabled_reason IS NOT NULL "
            "AND disabled_at IS NOT NULL)",
            name="ck_g32_template_disabled_metadata",
        ),
        sa.PrimaryKeyConstraint("template_id"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Gate 3.2 template registry migration is forward-only; create a corrective revision instead"
    )
