"""Add phase to bid primary key

Revision ID: 1ccf13888106
Revises: cf2a8ecf8ee8
Create Date: 2024-08-28 23:56:50.583651

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1ccf13888106'
down_revision = 'cf2a8ecf8ee8'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('bid', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_bid_id_phase', ['bid_id', 'phase'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('bid', schema=None) as batch_op:
        batch_op.drop_constraint('uq_bid_id_phase', type_='unique')

    # ### end Alembic commands ###
