"""users auth

Revision ID: 0006_users_auth
Revises: 0005_provider_model_options
Create Date: 2026-06-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_users_auth"
down_revision = "0005_provider_model_options"
branch_labels = None
depends_on = None


INITIAL_ADMIN_HASH = "pbkdf2_sha256$260000$nx3DMZpvTC-osOIdRPm2pw$tkGKTXl0etc4Qx2J0e3Uafk6ZSF4QsYKWAF5y7ez9BI"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_created_at", "users", ["created_at"])
    op.execute(
        sa.text(
            """
            INSERT INTO users (id, username, password_hash, role, is_active, created_at, updated_at)
            VALUES (
                '00000000-0000-0000-0000-000000000001',
                'slump',
                :password_hash,
                'super_admin',
                true,
                NOW(),
                NOW()
            )
            """
        ).bindparams(password_hash=INITIAL_ADMIN_HASH)
    )


def downgrade() -> None:
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
