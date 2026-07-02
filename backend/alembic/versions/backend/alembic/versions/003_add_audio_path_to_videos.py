"""add audio_path to videos

Revision ID: 003
Revises: 002
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("audio_path", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "audio_path")
