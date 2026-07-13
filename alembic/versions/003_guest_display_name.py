"""add display_name to guests

Revision ID: 003
Revises: 002
Create Date: 2026-07-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "guests",
        sa.Column("display_name", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guests", "display_name")
