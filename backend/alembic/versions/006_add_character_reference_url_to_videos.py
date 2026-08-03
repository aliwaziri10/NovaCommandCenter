"""add character_reference_url to videos

Revision ID: 006
Revises: 005
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("character_reference_url", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "character_reference_url")
