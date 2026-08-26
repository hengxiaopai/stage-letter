"""Repair creator sequence after explicit Formal identity imports.

Revision ID: c82e7a4d1f30
Revises: b71f6d2a4c90
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c82e7a4d1f30"
down_revision: Union[str, Sequence[str], None] = "b71f6d2a4c90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('creators', 'id'),
            COALESCE((SELECT MAX(id) FROM creators), 1),
            EXISTS (SELECT 1 FROM creators)
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError("creator identity sequence repair is forward-only")
