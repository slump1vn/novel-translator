"""job chunk results and glossary provider

Revision ID: 0007_job_chunk_results_and_glossary_provider
Revises: 0006_users_auth
Create Date: 2026-06-09 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_job_chunk_results_and_glossary_provider"
down_revision = "0006_users_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("glossary_provider_config_id", sa.String(length=36), nullable=True))
    op.create_index("ix_jobs_glossary_provider_config_id", "jobs", ["glossary_provider_config_id"])
    op.create_foreign_key(
        "fk_jobs_glossary_provider_config_id",
        "jobs",
        "provider_configs",
        ["glossary_provider_config_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "job_chunk_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("provider_name", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "chunk_index", name="uq_job_chunk_results_job_chunk"),
    )
    op.create_index("ix_job_chunk_results_job_id", "job_chunk_results", ["job_id"])
    op.create_index("ix_job_chunk_results_created_at", "job_chunk_results", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_job_chunk_results_created_at", table_name="job_chunk_results")
    op.drop_index("ix_job_chunk_results_job_id", table_name="job_chunk_results")
    op.drop_table("job_chunk_results")

    op.drop_constraint("fk_jobs_glossary_provider_config_id", "jobs", type_="foreignkey")
    op.drop_index("ix_jobs_glossary_provider_config_id", table_name="jobs")
    op.drop_column("jobs", "glossary_provider_config_id")
