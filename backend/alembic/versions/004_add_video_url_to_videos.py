"""add video_url to videos

Revision ID: 004
Revises: 003
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("video_url", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "video_url")
