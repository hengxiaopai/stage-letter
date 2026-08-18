"""add notification_jobs attempt and next_retry_at

Revision ID: c23b5e229894
Revises: 5354a9ed7741
Create Date: 2026-08-13 00:40:32.821568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c23b5e229894'
down_revision: Union[str, Sequence[str], None] = '5354a9ed7741'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notification_jobs",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "notification_jobs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notification_jobs", "next_retry_at")
    op.drop_column("notification_jobs", "attempt")
