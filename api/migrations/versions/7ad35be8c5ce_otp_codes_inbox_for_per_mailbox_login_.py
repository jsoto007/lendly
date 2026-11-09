"""otp_codes.inbox for per-mailbox login code limit

Revision ID: 7ad35be8c5ce
Revises: 034ebc173dae
Create Date: 2026-11-09 12:16:31.091771

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7ad35be8c5ce'
down_revision = '034ebc173dae'
branch_labels = None
depends_on = None


def upgrade():
    # Existing rows get inbox = lower(email); the app writes the canonical gmail form for new rows.
    op.add_column('otp_codes', sa.Column('inbox', sa.String(length=255), nullable=False, server_default=''))
    op.execute("UPDATE otp_codes SET inbox = lower(email)")
    op.alter_column('otp_codes', 'inbox', server_default=None)
    op.create_index(op.f('ix_otp_codes_inbox'), 'otp_codes', ['inbox'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_otp_codes_inbox'), table_name='otp_codes')
    op.drop_column('otp_codes', 'inbox')
