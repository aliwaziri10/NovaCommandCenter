"""add asset_urls to videos

Revision ID: 002
Revises: 001
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("asset_urls", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "asset_urls")
