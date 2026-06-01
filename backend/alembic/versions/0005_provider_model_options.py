"""provider model options

Revision ID: 0005_provider_model_options
Revises: 0004_story_glossary_entries
Create Date: 2026-06-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_provider_model_options"
down_revision = "0004_story_glossary_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_configs",
        sa.Column("stream", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("provider_configs", sa.Column("options", sa.JSON(), nullable=True))
    op.execute(
        """
        UPDATE provider_configs
        SET options = json_build_object(
            'temperature', COALESCE(temperature, 0.2),
            'num_predict', COALESCE(max_tokens, 2048),
            'repeat_penalty', 1.2,
            'timeout', 28800000
        )
        WHERE options IS NULL
        """
    )
    op.alter_column("provider_configs", "options", nullable=False)
    op.alter_column("provider_configs", "stream", server_default=None)
    op.drop_column("provider_configs", "max_tokens")


def downgrade() -> None:
    op.add_column(
        "provider_configs",
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="2048"),
    )
    op.execute(
        """
        UPDATE provider_configs
        SET max_tokens = COALESCE((options ->> 'num_predict')::integer, 2048)
        WHERE options IS NOT NULL
        """
    )
    op.alter_column("provider_configs", "max_tokens", server_default=None)
    op.drop_column("provider_configs", "options")
    op.drop_column("provider_configs", "stream")
