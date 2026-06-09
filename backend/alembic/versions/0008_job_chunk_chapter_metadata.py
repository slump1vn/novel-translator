"""job chunk chapter metadata

Revision ID: 0008_job_chunk_chapter_metadata
Revises: 0007_job_chunk_results_and_glossary_provider
Create Date: 2026-06-09 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_job_chunk_chapter_metadata"
down_revision = "0007_job_chunk_results_and_glossary_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_chunk_results", sa.Column("chapter_index", sa.Integer(), nullable=True))
    op.add_column("job_chunk_results", sa.Column("chapter_title", sa.String(length=255), nullable=True))
    op.add_column("job_chunk_results", sa.Column("chapter_chunk_index", sa.Integer(), nullable=True))
    op.add_column("job_chunk_results", sa.Column("chapter_total_chunks", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_chunk_results", "chapter_total_chunks")
    op.drop_column("job_chunk_results", "chapter_chunk_index")
    op.drop_column("job_chunk_results", "chapter_title")
    op.drop_column("job_chunk_results", "chapter_index")
