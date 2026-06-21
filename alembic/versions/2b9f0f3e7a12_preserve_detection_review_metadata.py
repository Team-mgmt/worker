"""Preserve detection review metadata

Revision ID: 2b9f0f3e7a12
Revises: 5e5ce504ab85
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2b9f0f3e7a12"
down_revision: Union[str, Sequence[str], None] = "5e5ce504ab85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("detections", sa.Column("crop_image_path", sa.Text(), nullable=True))
    op.add_column("detections", sa.Column("match_method", sa.String(length=50), nullable=True))
    op.add_column("detections", sa.Column("top_candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("detections", "top_candidates")
    op.drop_column("detections", "match_method")
    op.drop_column("detections", "crop_image_path")
