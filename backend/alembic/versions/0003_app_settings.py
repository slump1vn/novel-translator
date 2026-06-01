"""app settings

Revision ID: 0003_app_settings
Revises: 0002_job_logs_and_step_progress
Create Date: 2026-06-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_app_settings"
down_revision = "0002_job_logs_and_step_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
