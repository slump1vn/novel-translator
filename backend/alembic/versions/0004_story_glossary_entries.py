"""story glossary entries

Revision ID: 0004_story_glossary_entries
Revises: 0003_app_settings
Create Date: 2026-06-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_story_glossary_entries"
down_revision = "0003_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_glossary_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("source_term", sa.String(length=255), nullable=False),
        sa.Column("translated_term", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_story_glossary_entries_job_id", "story_glossary_entries", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_story_glossary_entries_job_id", table_name="story_glossary_entries")
    op.drop_table("story_glossary_entries")
