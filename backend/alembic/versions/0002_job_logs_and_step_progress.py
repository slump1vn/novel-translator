"""job logs and step progress

Revision ID: 0002_job_logs_and_step_progress
Revises: 0001_initial
Create Date: 2026-05-28 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_job_logs_and_step_progress"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_steps", sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("job_steps", "progress_percent", server_default=None)

    op.create_table(
        "job_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("step_name", sa.String(length=64), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_logs_job_id", "job_logs", ["job_id"])
    op.create_index("ix_job_logs_step_name", "job_logs", ["step_name"])
    op.create_index("ix_job_logs_created_at", "job_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_job_logs_created_at", table_name="job_logs")
    op.drop_index("ix_job_logs_step_name", table_name="job_logs")
    op.drop_index("ix_job_logs_job_id", table_name="job_logs")
    op.drop_table("job_logs")
    op.drop_column("job_steps", "progress_percent")
