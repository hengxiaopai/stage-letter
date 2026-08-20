"""Gate 2.5 durable cross-worker detection probe leases.

Revision ID: b25d4e9c7a12
Revises: a63f4b2d9e71
Create Date: 2026-08-20

The lease table is operational coordination metadata only. It does not belong to
the frozen Gate 1 canonical Base and never represents live truth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b25d4e9c7a12"
down_revision: Union[str, Sequence[str], None] = "a63f4b2d9e71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "detection_probe_leases",
        sa.Column("platform_account_id", sa.BigInteger(), nullable=False),
        sa.Column("probe_id", sa.String(length=255), nullable=False),
        sa.Column("owner_token", sa.String(length=64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["platform_account_id"],
            ["platform_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("platform_account_id"),
    )
    op.create_index(
        "idx_g25_detection_lease_expiry",
        "detection_probe_leases",
        ["lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Gate 2.5 detection lease migration is forward-only; create a corrective revision instead"
    )
