"""add phases

Revision ID: 8ea6da59c552
Revises: 60083bfb9322
Create Date: 2024-08-26 22:51:12.900536

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8ea6da59c552'
down_revision = '60083bfb9322'
branch_labels = None
depends_on = None


def upgrade():
    # Add the column as nullable first
    with op.batch_alter_table('bid', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phase', sa.VARCHAR(), nullable=True))
    
    # Update existing rows with a default value
    op.execute("UPDATE bid SET phase = 'Unknown' WHERE phase IS NULL")
    
    # Now alter the column to be NOT NULL
    with op.batch_alter_table('bid', schema=None) as batch_op:
        batch_op.alter_column('phase', nullable=False)

def downgrade():
    with op.batch_alter_table('bid', schema=None) as batch_op:
        batch_op.drop_column('phase')
    # ### end Alembic commands ###
