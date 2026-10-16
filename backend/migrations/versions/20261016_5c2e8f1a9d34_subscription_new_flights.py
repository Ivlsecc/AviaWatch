"""subscription new flights

Revision ID: 5c2e8f1a9d34
Revises: 22a3308e9375
Create Date: 2026-10-16 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5c2e8f1a9d34'
down_revision: Union[str, Sequence[str], None] = '22a3308e9375'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_new_flights', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('seen_flights', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_column('seen_flights')
        batch_op.drop_column('notify_new_flights')
