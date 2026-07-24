"""add shot_durations to videos

Revision ID: 005
Revises: 004
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("shot_durations", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "shot_durations")
