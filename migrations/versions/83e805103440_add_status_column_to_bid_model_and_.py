"""Add status column to Bid model and update existing bids

Revision ID: 83e805103440
Revises: 1ccf13888106
Create Date: 2024-09-05 13:34:02.495073

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.ext.declarative import declarative_base

# revision identifiers, used by Alembic.
revision = '83e805103440'
down_revision = '1ccf13888106'
branch_labels = None
depends_on = None

Base = declarative_base()

class Bid(Base):
    __tablename__ = 'bid'
    bid_id = sa.Column(sa.String, primary_key=True)
    status = sa.Column(sa.String(50))

def upgrade():
    # Add the status column
    with op.batch_alter_table('bid', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=50), nullable=True))
    
    # Update existing bids to have 'Bid' status
    connection = op.get_bind()
    session = Session(bind=connection)
    session.query(Bid).update({Bid.status: 'Bid'}, synchronize_session=False)
    session.commit()

def downgrade():
    with op.batch_alter_table('bid', schema=None) as batch_op:
        batch_op.drop_column('status')