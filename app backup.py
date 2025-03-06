from flask import Flask, request, jsonify, render_template, session, send_file, current_app, redirect, url_for, flash, abort
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from dotenv import load_dotenv
from fuzzywuzzy import process, fuzz
from sqlalchemy import or_, desc, select, union, func, literal, cast, String
import os
import threading 
from werkzeug.exceptions import BadRequest
import traceback
from flask_wtf.csrf import CSRFProtect
from flask_caching import Cache
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.serving import run_simple
from math import ceil
from urllib.parse import unquote
from sqlalchemy.exc import SQLAlchemyError, DBAPIError  # Add this import
from wtforms import ValidationError
from urllib.parse import unquote
import json  # Add this import
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set the database URI with SSL mode required
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL_DOCKER')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Use an environment variable for the secret key
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("No SECRET_KEY set for Flask application")
csrf = CSRFProtect(app)


# Initialize caching
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Global variable to store the last update time
last_update_time = None


# Add these lines after creating the Flask app
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Define the association table
inventory_conversion_code = db.Table('inventory_conversion_code',
    db.Column('inventory_part_number', db.String, db.ForeignKey('inventory.part_number'), primary_key=True),
    db.Column('conversion_code', db.String, db.ForeignKey('conversion_code.code'), primary_key=True),
    extend_existing=True  # Ensure this parameter is included to avoid redefinition errors
)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # Increased to 255 characters

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Add this function to your app.py file
def update_database_schema():
    with app.app_context():
        db.reflect()
        if 'user' in db.metadata.tables:
            user_table = db.metadata.tables['user']
            if 'password_hash' in user_table.columns:
                column = user_table.columns['password_hash']
                column.type = db.String(255)
                db.session.execute(db.text('ALTER TABLE "user" ALTER COLUMN password_hash TYPE VARCHAR(255)'))
                db.session.commit()
                print("Updated password_hash column to VARCHAR(255)")
        db.create_all()



class Proposal(db.Model):
    __tablename__ = 'proposals'
    id = db.Column(db.Integer, primary_key=True)
    bid_id = db.Column(db.String, db.ForeignKey('bid.bid_id'), nullable=False, unique=True)
    customer_name = db.Column(db.String(255))
    project_name = db.Column(db.String(255))
    total_budget = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    special_notes = db.Column(db.Text)
    terms_conditions = db.Column(db.Text)
    revision_number = db.Column(db.Integer, default=1)

    # Relationships
    bid = db.relationship('Bid', backref=db.backref('proposal', uselist=False))
    proposal_amounts = db.relationship('ProposalAmount', back_populates='proposal', cascade="all, delete-orphan")
    options = db.relationship('ProposalOption', back_populates='proposal', cascade="all, delete-orphan")

    components = db.relationship('ProposalComponent', back_populates='proposal', cascade="all, delete-orphan")


    # We're not using sections, so we'll remove that part from the to_dict method
    def to_dict(self):
        return {
            'bid_id': self.bid_id,
            'customer_name': self.customer_name,
            'project_name': self.project_name,
            'total_budget': float(self.total_budget) if self.total_budget else None,
            'special_notes': self.special_notes,
            'terms_conditions': self.terms_conditions,
            'revision_number': self.revision_number,
            'proposal_amounts': [amount.to_dict() for amount in self.proposal_amounts],
            'options': [option.to_dict() for option in self.options]
        }

class ProposalComponent(db.Model):
    __tablename__ = 'proposal_components'
    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'), nullable=False)
    type = db.Column(db.String(50))  # 'section' or 'phase'
    name = db.Column(db.String(255))
    
    proposal = db.relationship('Proposal', back_populates='components')
    lines = db.relationship('ProposalComponentLine', back_populates='component', cascade="all, delete-orphan")

class ProposalComponentLine(db.Model):
    __tablename__ = 'proposal_component_lines'
    id = db.Column(db.Integer, primary_key=True)
    component_id = db.Column(db.Integer, db.ForeignKey('proposal_components.id'), nullable=False)
    name = db.Column(db.String(255))
    value = db.Column(db.Float)
    
    component = db.relationship('ProposalComponent', back_populates='lines')


class ProposalAmount(db.Model):
    __tablename__ = 'proposal_amounts'
    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'), nullable=False)
    description = db.Column(db.String(255))
    amount = db.Column(db.Float)

    proposal = db.relationship('Proposal', back_populates='proposal_amounts')

    def to_dict(self):
        return {
            'description': self.description,
            'amount': float(self.amount) if self.amount else None
        }
class ProposalOption(db.Model):
    __tablename__ = 'proposal_options'
    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'), nullable=False)
    description = db.Column(db.String(255))
    amount = db.Column(db.Float)

    proposal = db.relationship('Proposal', back_populates='options')
    
    def to_dict(self):
        return {
            'description': self.description,
            'amount': float(self.amount) if self.amount else None
        }
class Architect(db.Model):
    __tablename__ = 'architects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(50), nullable=False)

class Vendor(db.Model):
    __tablename__ = 'vendors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(50), nullable=False)

class Engineer(db.Model):
    __tablename__ = 'engineers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(50), nullable=False)

class LaborRates(db.Model):
    __tablename__ = 'labor_rates'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), unique=True, nullable=False)
    rate = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<LaborRates {self.category}: {self.rate}>'

class Project(db.Model):
    project_name = db.Column(db.String(255), primary_key=True)
    project_address = db.Column(db.String(255))
    project_state = db.Column(db.String(255))
    project_city = db.Column(db.String(255))
    project_zip = db.Column(db.String(255))
    point_of_contact = db.Column(db.String(255), nullable=True)  # New field
    contact_phone_number = db.Column(db.String(50), nullable=True)  # New field

    bids = db.relationship('Bid', back_populates='project')

class GroupMember:
    def __init__(self, id, name, company, address, phone_number, category):
        self.id = id
        self.name = name
        self.company = company
        self.address = address
        self.phone_number = phone_number
        self.category = category

# Define the FactorCode model
class FactorCode(db.Model):
    __tablename__ = 'factor_code'
    factor_code = db.Column(db.String, primary_key=True)
    description = db.Column(db.String)
    labor_hours = db.Column(db.Float)
    items = db.relationship('FactorCodeItems', back_populates='factor')
    inventory_items = db.relationship('Inventory', back_populates='related_factor_code')

# Update the Inventory model to include the relationship with FactorCode
class Inventory(db.Model):
    __tablename__ = 'inventory'
    part_number = db.Column(db.String, primary_key=True)
    description = db.Column(db.String)
    cost = db.Column(db.Float)
    factor_code = db.Column(db.String, db.ForeignKey('factor_code.factor_code'))
    unit = db.Column(db.String)
    conversion_codes = db.relationship('ConversionCode', secondary=inventory_conversion_code, back_populates='inventory_items')
    related_factor_code = db.relationship('FactorCode', back_populates='inventory_items')
    factor_codes = db.relationship('FactorCodeItems', back_populates='inventory_item')
    bids = db.relationship('Bid', back_populates='inventory')

class FactorCodeItems(db.Model):
    __tablename__ = 'factor_code_items'
    id = db.Column(db.Integer, primary_key=True)
    factor_code = db.Column(db.String(50), db.ForeignKey('factor_code.factor_code'), nullable=False)
    part_number = db.Column(db.String(50), db.ForeignKey('inventory.part_number'), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=1.0)

    factor = db.relationship('FactorCode', back_populates='items')
    inventory_item = db.relationship('Inventory', back_populates='factor_codes')

# Define the ConversionCode model
class ConversionCode(db.Model):
    __tablename__ = 'conversion_code'
    code = db.Column(db.String(50), primary_key=True, unique=True, nullable=False)
    inventory_items = db.relationship('Inventory', secondary=inventory_conversion_code, back_populates='conversion_codes')

class Customer(db.Model):
    customer_name = db.Column(db.String(255), primary_key=True)
    customer_address = db.Column(db.String(255))
    customer_state = db.Column(db.String(255))
    customer_city = db.Column(db.String(255))
    customer_zip = db.Column(db.String(255))

    bids = db.relationship('Bid', back_populates='customer')

class Bid(db.Model):
    bid_id = db.Column(db.String, primary_key=True)
    bid_date = db.Column(db.Date)
    date_created = db.Column(db.Date, default=datetime.utcnow)
    customer_name = db.Column(db.String(255), db.ForeignKey('customer.customer_name'))
    drains_labor_rate = db.Column(db.Numeric)
    irrigation_labor_rate = db.Column(db.Numeric)
    landscape_labor_rate = db.Column(db.Numeric)
    maintenance_labor_rate = db.Column(db.Numeric)
    local_sales_tax = db.Column(db.Numeric)
    engineer_name = db.Column(db.String(255))
    architect_name = db.Column(db.String(255))
    point_of_contact = db.Column(db.String(255))
    project_name = db.Column(db.String(255), db.ForeignKey('project.project_name'))
    project_address = db.Column(db.String(255))
    project_state = db.Column(db.String(255))
    project_city = db.Column(db.String(255))
    project_zip = db.Column(db.String(255))
    part_number = db.Column(db.String(255), db.ForeignKey('inventory.part_number'))
    description = db.Column(db.String(255))
    landscaping_total = db.Column(db.Float, default=0.0)
    drains_total = db.Column(db.Float, default=0.0)
    irrigation_total = db.Column(db.Float, default=0.0)
    maintenance_total = db.Column(db.Float, default=0.0)
    total_budget = db.Column(db.Float, default=0.0)

    customer = db.relationship('Customer', back_populates='bids')
    project = db.relationship('Project', back_populates='bids')
    inventory = db.relationship('Inventory', back_populates='bids')
    sub_bids = db.relationship('SubBid', back_populates='bid', cascade="all, delete-orphan")
    factor_code_items = db.relationship('BidFactorCodeItems', back_populates='bid', 
                                        cascade="all, delete-orphan")

class BidFactorCodeItems(db.Model):
    __tablename__ = 'bid_factor_code_items'
    id = db.Column(db.Integer, primary_key=True)
    bid_id = db.Column(db.String, db.ForeignKey('bid.bid_id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    factor_code = db.Column(db.String(50), nullable=False)
    part_number = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    quantity = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    labor_hours = db.Column(db.Float, nullable=False)
    line_ext_cost = db.Column(db.Float, nullable=False)
    tax = db.Column(db.Float, nullable=False, default=0.0)
    additional_description = db.Column(db.String(255))
    
    bid = db.relationship('Bid', back_populates='factor_code_items')

class SubBid(db.Model):
    sub_bid_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    cost = db.Column(db.Float)
    labor_hours = db.Column(db.Float)
    bid_id = db.Column(db.String, db.ForeignKey('bid.bid_id'), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='unknown')
    total_cost = db.Column(db.Float, default=0.0)

    bid = db.relationship('Bid', back_populates='sub_bids')
    items = db.relationship('SubBidItem', back_populates='sub_bid', cascade='all, delete-orphan')

class SubBidItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sub_bid_id = db.Column(db.Integer, db.ForeignKey('sub_bid.sub_bid_id'), nullable=False)
    part_number = db.Column(db.String(50))
    description = db.Column(db.String(255))
    factor_code = db.Column(db.String(50))
    quantity = db.Column(db.Float)
    cost = db.Column(db.Float)
    labor_hours = db.Column(db.Float)
    line_ext_cost = db.Column(db.Float)
    sub_bid = db.relationship('SubBid', back_populates='items')


class Tax(db.Model):
    __tablename__ = 'tax'
    zip_code = db.Column(db.String(10), primary_key=True)
    tax_rate = db.Column(db.Float, nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Tax zip_code={self.zip_code} tax_rate={self.tax_rate}>"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/add-update-project', methods=['POST'])
def add_update_project():
    try:
        data = request.form
        project_name = data.get('project_name')
        
        project = Project.query.get(project_name)
        if project:
            # Update existing project
            project.project_address = data.get('project_address')
            project.project_state = data.get('project_state')
            project.project_city = data.get('project_city')
            project.project_zip = data.get('project_zip')
            project.point_of_contact = data.get('point_of_contact')
            project.contact_phone_number = data.get('contact_phone_number')
            message = "Project updated successfully."
        else:
            # Create new project
            new_project = Project(
                project_name=project_name,
                project_address=data.get('project_address'),
                project_state=data.get('project_state'),
                project_city=data.get('project_city'),
                project_zip=data.get('project_zip'),
                point_of_contact=data.get('point_of_contact'),
                contact_phone_number=data.get('contact_phone_number')
            )
            db.session.add(new_project)
            message = "New project created successfully."

        db.session.commit()
        return jsonify({"success": True, "message": message})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500 



@app.route('/add-sub-bid-to-main', methods=['POST'])
@csrf.exempt  # Exempt CSRF protection if necessary
def add_sub_bid_to_main():
    app.logger.info('add_sub_bid_to_main called')
    try:
        data = request.get_json()
        app.logger.info(f"Received data: {data}")
        if not data:
            app.logger.warning('No JSON data received')
            return jsonify({'success': False, 'message': 'Invalid JSON data'}), 400

        bid_id = data.get('bid_id')
        sub_bid_id = data.get('sub_bid_id')
        category = data.get('category')

        if not all([bid_id, sub_bid_id, category]):
            app.logger.warning('Missing required data')
            return jsonify({'success': False, 'message': 'Missing required data'}), 400

        # Fetch the sub-bid
        sub_bid = SubBid.query.get_or_404(sub_bid_id)
        
        added_items = []

        # Create a new line item for the sub-bid name
        new_item = BidFactorCodeItems(
            bid_id=bid_id,
            category=category,
            description=f"Sub-Bid: {sub_bid.name}",
            quantity=1,
            cost=sub_bid.total_cost,
            labor_hours=sub_bid.labor_hours,
            line_ext_cost=sub_bid.total_cost,
            factor_code='',
            part_number='SUB-BID',
            tax=0.0,
            additional_description=''
        )
        db.session.add(new_item)
        db.session.flush()  # Ensure new_item.id is populated
        added_items.append({
            'id': new_item.id,
            'part_number': new_item.part_number,
            'description': new_item.description,
            'factor_code': new_item.factor_code,
            'quantity': new_item.quantity,
            'cost': float(new_item.cost),
            'labor_hours': float(new_item.labor_hours),
            'line_ext_cost': float(new_item.line_ext_cost),
            # Include any additional fields needed
        })

        # Add sub-bid items as separate line items
        for item in sub_bid.items:
            sub_item = BidFactorCodeItems(
                bid_id=bid_id,
                category=category,
                part_number=item.part_number if item.part_number else 'N/A',
                description=item.description if item.description else '',
                factor_code=item.factor_code if hasattr(item, 'factor_code') and item.factor_code else '',
                quantity=item.quantity,
                cost=item.cost,
                labor_hours=item.labor_hours,
                line_ext_cost=item.line_ext_cost,
                tax=0.0,
                additional_description=''
            )
            db.session.add(sub_item)
            db.session.flush()  # Ensure sub_item.id is populated
            added_items.append({
                'id': sub_item.id,
                'description': sub_item.description,
                'quantity': float(sub_item.quantity),
                'cost': float(sub_item.cost),
                'labor_hours': float(sub_item.labor_hours),
                'line_ext_cost': float(sub_item.line_ext_cost),
                'part_number': sub_item.part_number,
                'factor_code': sub_item.factor_code
            })

        # Update the main bid totals
        main_bid = Bid.query.get(bid_id)
        if main_bid:
            if category == 'landscape':
                main_bid.landscaping_total = float(main_bid.landscaping_total or 0) + float(sub_bid.total_cost)
            elif category == 'drains':
                main_bid.drains_total = float(main_bid.drains_total or 0) + float(sub_bid.total_cost)
            elif category == 'irrigation':
                main_bid.irrigation_total = float(main_bid.irrigation_total or 0) + float(sub_bid.total_cost)
            elif category == 'maintenance':
                main_bid.maintenance_total = float(main_bid.maintenance_total or 0) + float(sub_bid.total_cost)
            
            main_bid.total_budget = (
                float(main_bid.landscaping_total or 0) +
                float(main_bid.drains_total or 0) +
                float(main_bid.irrigation_total or 0) +
                float(main_bid.maintenance_total or 0)
            )

        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Sub-bid added to main bid successfully',
            'added_items': added_items,
            'sub_bid_id': sub_bid_id,
            'updated_totals': {
                'landscaping_total': float(main_bid.landscaping_total or 0),
                'drains_total': float(main_bid.drains_total or 0),
                'irrigation_total': float(main_bid.irrigation_total or 0),
                'maintenance_total': float(main_bid.maintenance_total or 0),
                'total_budget': float(main_bid.total_budget or 0)
            }
        })

    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.error(f"Database error in add_sub_bid_to_main: {str(e)}")
        return jsonify({'success': False, 'message': 'A database error occurred'}), 500
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Unexpected error in add_sub_bid_to_main: {str(e)}")
        return jsonify({'success': False, 'message': 'An unexpected error occurred'}), 500


@app.route('/save-proposal', methods=['POST'])
def save_proposal():
    app.logger.info('Received save proposal request')
    data = request.json
    app.logger.debug(f'Received proposal data: {data}')
    proposal_id = data.get('proposal_id')
    version_number = data.get('revision_number')

    if not proposal_id:
        app.logger.error('Proposal ID is missing')
        return jsonify({'success': False, 'message': 'Proposal ID is required'}), 400
    
    if version_number is None:
        app.logger.error('Version number is missing')
        return jsonify({'success': False, 'message': 'Version number is required'}), 400

    app.logger.info(f'Processing proposal with ID: {proposal_id} and version number: {version_number}')
    proposal = Proposal.query.filter_by(bid_id=proposal_id, revision_number=version_number).first()
    if not proposal:
        app.logger.info(f'Proposal not found for ID: {proposal_id} and version {version_number}, creating new proposal')
        proposal = Proposal(bid_id=proposal_id, revision_number=version_number)
        db.session.add(proposal)
    
    try:
        # Update proposal fields
        app.logger.info('Updating proposal fields')
        proposal.customer_name = data.get('customer_name')
        proposal.total_budget = data.get('total_budget')
        proposal.special_notes = json.dumps(data.get('special_notes', []))
        proposal.terms_conditions = json.dumps(data.get('terms_conditions', []))
        proposal.project_name = data.get('job_name')
        proposal.project_city = data.get('job_city')
        proposal.bid_date = data.get('bid_date')
        proposal.point_of_contact = data.get('point_of_contact')

        # Update proposal fields
        proposal.architect_name = data.get('architect_name')
        proposal.architect_specifications = data.get('architect_specifications')
        proposal.architect_dated = data.get('architect_dated')
        proposal.architect_sheets = data.get('architect_sheets')
        proposal.engineer_name = data.get('engineer_name')
        proposal.engineer_specifications = data.get('engineer_specifications')
        proposal.engineer_dated = data.get('engineer_dated')
        proposal.engineer_sheets = data.get('engineer_sheets')


        # Update other fields as needed...

        # Clear existing amounts, options, and components
        app.logger.info('Clearing existing amounts, options, and components')
        proposal.proposal_amounts = []
        proposal.options = []

        # Delete existing component lines first
        app.logger.info('Deleting existing component lines')
        ProposalComponentLine.query.filter(
            ProposalComponentLine.component_id.in_(
                ProposalComponent.query.with_entities(ProposalComponent.id).filter_by(proposal_id=proposal.id)
            )
        ).delete(synchronize_session=False)

        # Now delete the components
        app.logger.info('Deleting existing components')
        ProposalComponent.query.filter_by(proposal_id=proposal.id).delete(synchronize_session=False)

        # Add new amounts
        app.logger.info('Adding new proposal amounts')
        for amount in data.get('proposal_amounts', []):
            proposal.proposal_amounts.append(ProposalAmount(description=amount['description'], amount=amount['amount']))

        # Add new options
        app.logger.info('Adding new options')
        for option in data.get('options', []):
            proposal.options.append(ProposalOption(description=option['description'], amount=option['amount']))

        # Add new components (sections and lines)
        app.logger.info('Adding new components (sections and lines)')
        for component in data.get('components', []):
            new_component = ProposalComponent(
                proposal_id=proposal.id,
                type=component['type'],
                name=component['name']
            )
            db.session.add(new_component)
            for line in component.get('lines', []):
                new_line = ProposalComponentLine(
                    component=new_component,
                    name=line['name'],
                    value=line['value']
                )
                db.session.add(new_line)

        db.session.commit()
        app.logger.info('Proposal saved successfully')
        return jsonify({'success': True, 'message': 'Proposal saved successfully'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Error saving proposal: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        app.logger.info('save_proposal route completed')

def login_exempt(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        return view(*args, **kwargs)
    wrapped_view.login_exempt = True
    return wrapped_view


@app.before_request
def check_login():
    if not current_user.is_authenticated and request.endpoint and 'static' not in request.endpoint:
        view = app.view_functions.get(request.endpoint)
        if view and not getattr(view, 'login_exempt', False):
            return redirect(url_for('login', next=request.url))

# Modify your existing login route
@app.route('/login', methods=['GET', 'POST'])
@login_exempt
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home'))
        else:
            flash('Invalid username or password', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/reset-password-request', methods=['GET', 'POST'])
@login_required
def reset_password_request():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            # Generate a token
            serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
            token = serializer.dumps(user.email, salt='password-reset-salt')
            
            # Send reset email
            reset_url = url_for('reset_password', token=token, _external=True)
            msg = Message('Password Reset Request',
                          sender='noreply@yourdomain.com',
                          recipients=[user.email])
            msg.body = f'To reset your password, visit the following link: {reset_url}'
            mail.send(msg)
            
            flash('An email has been sent with instructions to reset your password.', 'info')
        else:
            flash('Email address not found', 'error')
    return render_template('reset_password_request.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='password-reset-salt', max_age=3600)
    except:
        flash('The password reset link is invalid or has expired.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        user = User.query.filter_by(email=email).first()
        if user:
            new_password = request.form.get('password')
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Your password has been updated!', 'success')
            return redirect(url_for('login'))
        else:
            flash('User not found', 'error')
    return render_template('reset_password.html', token=token)

@app.route('/api/subbids/<int:subbid_id>/items', methods=['GET'])
def get_subbid_items(subbid_id):
    try:
        subbid = SubBid.query.get_or_404(subbid_id)
        items = SubBidItem.query.filter_by(sub_bid_id=subbid_id).all()
        
        items_data = [{
            'id': item.id,
            'part_number': item.part_number,
            'description': item.description,
            'factor_code': item.factor_code,
            'quantity': float(item.quantity),
            'cost': float(item.cost),
            'labor_hours': float(item.labor_hours),
            'line_ext_cost': float(item.line_ext_cost)
        } for item in items]
        
        return jsonify(items_data)
    except Exception as e:
        app.logger.error(f"Error fetching sub-bid items: {str(e)}")
        return jsonify({"error": "An error occurred while fetching sub-bid items"}), 500
    

@app.route('/save-bid-labor-rate', methods=['POST'])
@login_required
def save_bid_labor_rate():
    try:
        data = request.json
        bid_id = data.get('bid_id')
        if not bid_id:
            return jsonify({'success': False, 'message': 'Bid ID is required'}), 400

        bid = Bid.query.get(bid_id)
        if not bid:
            return jsonify({'success': False, 'message': 'Bid not found'}), 404

        for category, rate in data.items():
            if category != 'bid_id':
                setattr(bid, f'{category}_labor_rate', float(rate))

        db.session.commit()
        return jsonify({'success': True, 'message': 'Labor rates saved successfully'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error saving bid labor rates: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred while saving labor rates'}), 500
    
    
@app.route('/conversion-codes', methods=['GET'])
def get_conversion_codes():
    try:
        conversion_codes = ConversionCode.query.all()
        codes_data = [{
            'code': code.code,
            'inventory_items': [{'part_number': item.part_number, 'description': item.description} for item in code.inventory_items]
        } for code in conversion_codes]
        return jsonify(codes_data)
    except Exception as e:
        app.logger.error(f"Error fetching conversion codes: {str(e)}")
        return jsonify({"error": "An error occurred while fetching conversion codes"}), 500    


@app.route('/duplicate_bid', methods=['POST'])
def duplicate_bid():
    try:
        data = request.json
        original_bid_id = data.get('original_bid_id')
        new_bid_id = data.get('new_bid_id')

        if not original_bid_id or not new_bid_id:
            return jsonify({'success': False, 'message': 'Original and new bid IDs are required'}), 400

        # Fetch the original bid
        original_bid = Bid.query.filter_by(bid_id=original_bid_id).first()
        if not original_bid:
            return jsonify({'success': False, 'message': 'Original bid not found'}), 404

        # Check if the new bid ID already exists
        existing_bid = Bid.query.filter_by(bid_id=new_bid_id).first()
        if existing_bid:
            return jsonify({'success': False, 'message': 'New bid ID already exists'}), 400

        # Create a new bid with the same details as the original
        new_bid = Bid(
            bid_id=new_bid_id,
            bid_date=datetime.now().date(),
            customer_name=original_bid.customer_name,
            drains_labor_rate=original_bid.drains_labor_rate,
            irrigation_labor_rate=original_bid.irrigation_labor_rate,
            landscape_labor_rate=original_bid.landscape_labor_rate,
            maintenance_labor_rate=original_bid.maintenance_labor_rate,
            local_sales_tax=original_bid.local_sales_tax,
            engineer_name=original_bid.engineer_name,
            architect_name=original_bid.architect_name,
            point_of_contact=original_bid.point_of_contact,
            project_name=original_bid.project_name,
            project_address=original_bid.project_address,
            project_state=original_bid.project_state,
            project_city=original_bid.project_city,
            project_zip=original_bid.project_zip,
            description=original_bid.description
        )
        db.session.add(new_bid)

        # Duplicate all BidFactorCodeItems
        original_items = BidFactorCodeItems.query.filter_by(bid_id=original_bid_id).all()
        for item in original_items:
            new_item = BidFactorCodeItems(
                bid_id=new_bid_id,
                category=item.category,
                factor_code=item.factor_code,
                part_number=item.part_number,
                description=item.description,
                quantity=item.quantity,
                cost=item.cost,
                labor_hours=item.labor_hours,
                line_ext_cost=item.line_ext_cost,
                tax=item.tax,
                additional_description=item.additional_description
            )
            db.session.add(new_item)

        # Duplicate all SubBids
        original_sub_bids = SubBid.query.filter_by(bid_id=original_bid_id).all()
        for sub_bid in original_sub_bids:
            new_sub_bid = SubBid(
                bid_id=new_bid_id,
                name=sub_bid.name,
                cost=sub_bid.cost,
                labor_hours=sub_bid.labor_hours,
                category=sub_bid.category,
                total_cost=sub_bid.total_cost
            )
            db.session.add(new_sub_bid)

            # Duplicate SubBidItems for each SubBid
            original_sub_bid_items = SubBidItem.query.filter_by(sub_bid_id=sub_bid.sub_bid_id).all()
            for item in original_sub_bid_items:
                new_item = SubBidItem(
                    sub_bid_id=new_sub_bid.sub_bid_id,
                    part_number=item.part_number,
                    description=item.description,
                    factor_code=item.factor_code,
                    quantity=item.quantity,
                    cost=item.cost,
                    labor_hours=item.labor_hours,
                    line_ext_cost=item.line_ext_cost
                )
                db.session.add(new_item)

        db.session.commit()
        return jsonify({'success': True, 'message': 'Bid duplicated successfully', 'new_bid_id': new_bid_id})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error duplicating bid: {str(e)}")
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500

@app.route('/search-engineers', methods=['GET'])
def search_engineers():
    query = request.args.get('query', '')
    engineers = Engineer.query.filter(or_(
        Engineer.name.ilike(f'%{query}%'),
        Engineer.company.ilike(f'%{query}%')
    )).limit(10).all()
    
    return jsonify([{
        'name': e.name,
        'company': e.company,
        'phone_number': e.phone_number
    } for e in engineers])


@app.route('/search-architects', methods=['GET'])
def search_architects():
    query = request.args.get('query', '')
    architects = Architect.query.filter(or_(
        Architect.name.ilike(f'%{query}%'),
        Architect.company.ilike(f'%{query}%')
    )).limit(10).all()
    
    return jsonify([{
        'name': a.name,
        'company': a.company,
        'phone_number': a.phone_number
    } for a in architects])

@app.route('/api/subbids/<bid_id>/<category>', methods=['GET'])
def getSubBids(bid_id, category):
    try:
        sub_bids = SubBid.query.filter_by(bid_id=bid_id, category=category).all()
        sub_bids_data = [{
            'id': sb.sub_bid_id,
            'name': sb.name,
            'total_cost': sb.total_cost,
            'labor_hours': sb.labor_hours
        } for sb in sub_bids]
        return jsonify(sub_bids_data), 200
    except Exception as e:
        app.logger.error(f"Error fetching sub-bids: {str(e)}")
        return jsonify({"error": "An error occurred while fetching sub-bids"}), 500

@app.route('/api/bids', methods=['GET'])
def get_bids():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20
        bids_query = Bid.query.order_by(desc(Bid.bid_date))
        total_items = bids_query.count()
        pages = ceil(total_items / per_page)
        items = bids_query.paginate(page=page, per_page=per_page, error_out=False)
        bids_data = []
        for bid in items.items:
            # Check if a proposal exists for this bid
            has_proposal = Proposal.query.filter_by(bid_id=bid.bid_id).first() is not None
            
            bids_data.append({
                'bid_id': bid.bid_id,
                'project_name': bid.project_name,
                'customer_name': bid.customer_name,
                'engineer_name': bid.engineer_name,
                'architect_name': bid.architect_name,
                'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,
                'point_of_contact': bid.point_of_contact,
                'local_sales_tax': float(bid.local_sales_tax) if bid.local_sales_tax else None,
                'has_proposal': has_proposal  # Add this new field
            })
        return jsonify({
            'bids': bids_data,
            'current_page': page,
            'pages': pages,
            'total': total_items
        })
    except Exception as e:
        app.logger.error(f"Error fetching bids: {str(e)}")
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500
    

@app.route('/get_next_bid_id', methods=['GET'])
def get_next_bid_id():
    try:
        # Get the latest bid ID from the database
        latest_bid = Bid.query.order_by(Bid.bid_id.desc()).first()
        
        if latest_bid:
            # If there are existing bids, increment the last one
            last_id = latest_bid.bid_id
            # Assuming the bid_id is in the format 'BXXXXX'
            try:
                num = int(last_id[1:]) + 1  # Remove the 'B' and convert to int
            except ValueError:
                app.logger.error(f"Error parsing last bid ID '{last_id}'")
                num = 1  # Fallback to starting from 1 if parsing fails
            next_id = f"B{num:05d}"
        else:
            # If no bids exist, start with B00001
            next_id = "B00001"
        
        app.logger.info(f"Generated next bid ID: {next_id}")
        return jsonify({'next_bid_id': next_id}), 200
    except Exception as e:
        app.logger.error(f"Error generating next bid ID: {str(e)}", exc_info=True)
        return jsonify({'error': 'An error occurred while generating the next bid ID', 'details': str(e)}), 500

@app.route('/get-bid-labor-rates', methods=['GET'])
def get_bid_labor_rates():
    try:
        bid_id = request.args.get('bid_id')
        
        # Fetch custom labor rates for the bid
        custom_labor_rates = BidLaborRates.query.filter_by(bid_id=bid_id).first()
        
        if custom_labor_rates:
            current_app.logger.debug(f"Retrieved custom labor rates for bid {bid_id}: {custom_labor_rates}")
            response = {
                'drains_labor_rate': custom_labor_rates.drains_labor_rate,
                'irrigation_labor_rate': custom_labor_rates.irrigation_labor_rate,
                'landscape_labor_rate': custom_labor_rates.landscape_labor_rate,
                'maintenance_labor_rate': custom_labor_rates.maintenance_labor_rate,
                'subcontractor_labor_rate': custom_labor_rates.subcontractor_labor_rate
            }
        else:
            # If no custom rates found, get the default labor rates
            labor_rates = LaborRates.query.all()
            if not labor_rates:
                current_app.logger.warning("No default labor rates found in the database.")
                return jsonify({
                    'drains_labor_rate': 50.0,
                    'irrigation_labor_rate': 50.0,
                    'landscape_labor_rate': 50.0,
                    'maintenance_labor_rate': 50.0,
                    'subcontractor_labor_rate': 50.0
                })

            rates_dict = {rate.category: rate.rate for rate in labor_rates}
            response = {
                'drains_labor_rate': rates_dict.get('drains', 50.0),
                'irrigation_labor_rate': rates_dict.get('irrigation', 50.0),
                'landscape_labor_rate': rates_dict.get('landscape', 50.0),
                'maintenance_labor_rate': rates_dict.get('maintenance', 50.0),
                'subcontractor_labor_rate': rates_dict.get('subcontractor', 50.0)
            }

        current_app.logger.debug(f"Response for bid {bid_id}: {response}")
        return jsonify(response)
    except SQLAlchemyError as e:
        current_app.logger.error(f"Database error when fetching labor rates: {str(e)}")
        return jsonify({'error': 'A database error occurred while fetching labor rates'}), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error when fetching labor rates: {str(e)}")
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500


@app.route('/get-default-labor-rates', methods=['GET'])
def get_default_labor_rates():
    try:
        labor_rates = LaborRates.query.all()
        if not labor_rates:
            return jsonify({
                'drains_labor_rate': 50.0,
                'irrigation_labor_rate': 50.0,
                'landscape_labor_rate': 50.0,
                'maintenance_labor_rate': 50.0,
                'local_sales_tax': 8.75
            })

        rates_dict = {rate.category: rate.rate for rate in labor_rates}
        
        return jsonify({
            'drains_labor_rate': rates_dict.get('drains', 50.0),
            'irrigation_labor_rate': rates_dict.get('irrigation', 50.0),
            'landscape_labor_rate': rates_dict.get('landscape', 50.0),
            'maintenance_labor_rate': rates_dict.get('maintenance', 50.0),
            'local_sales_tax': 8.75  # Adjust based on your database if needed
        })
    except SQLAlchemyError as e:
        return jsonify({'error': 'A database error occurred while fetching labor rates'}), 500
    except Exception as e:
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500
    
@app.route('/save-default-labor-rates', methods=['POST'])
def save_default_labor_rates():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400

        categories = ['drains', 'irrigation', 'landscape', 'maintenance']
        
        for category in categories:
            rate = data.get(f'{category}_labor_rate')
            if rate is not None:
                labor_rate = LaborRates.query.filter_by(category=category).first()
                if labor_rate:
                    labor_rate.rate = float(rate)
                else:
                    new_rate = LaborRates(category=category, rate=float(rate))
                    db.session.add(new_rate)

        db.session.commit()
        current_app.logger.info(f"Labor rates updated: {data}")
        return jsonify({'success': True, 'message': 'Labor rates saved successfully'})
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error when saving labor rates: {str(e)}")
        return jsonify({'success': False, 'message': 'A database error occurred while saving rates'}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error when saving labor rates: {str(e)}")
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {str(e)}'}), 500
    

@app.route('/get_tax_rate/<zip_code>', methods=['GET'])
def get_tax_rate(zip_code):
    print(f"Fetching tax rate for zip code: {zip_code}")
    tax = Tax.query.filter_by(zip_code=zip_code).first()
    if tax:
        print(f"Tax rate found: {tax.tax_rate}")
        return jsonify({'tax_rate': tax.tax_rate})
    else:
        print(f"No tax rate found for zip code: {zip_code}")
        return jsonify({'tax_rate': None})
    
@app.route('/check_tax_table')
def check_tax_table():
    inspector = inspect(db.engine)
    if 'tax' in inspector.get_table_names():
        return jsonify({"message": "Tax table exists"}), 200
    else:
        try:
            Tax.__table__.create(db.engine)
            return jsonify({"message": "Tax table created successfully"}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500  

@app.route('/save_tax_rate', methods=['POST'])
def save_tax_rate():
    print("Entering save_tax_rate function")
    print(f"Request method: {request.method}")
    print(f"Request headers: {request.headers}")
    print(f"Request data: {request.data}")
    
    try:
        data = request.json
        print(f"Parsed JSON data: {data}")
    except Exception as e:
        print(f"Error parsing JSON: {str(e)}")
        return jsonify({'error': 'Invalid JSON data'}), 400

    zip_code = data.get('zip_code')
    tax_rate = data.get('tax_rate')
    
    print(f"Extracted zip_code: {zip_code}, tax_rate: {tax_rate}")
    
    if not zip_code:
        print("Error: Missing zip_code")
        return jsonify({'error': 'Missing zip_code'}), 400
    
    if tax_rate is None:
        print("Error: Missing tax_rate")
        return jsonify({'error': 'Missing tax_rate'}), 400
    
    try:
        tax_rate = float(tax_rate)
    except ValueError:
        print(f"Error: Invalid tax_rate value: {tax_rate}")
        return jsonify({'error': f'Invalid tax_rate value: {tax_rate}'}), 400
    
    try:
        print("Querying for existing tax record")
        tax = Tax.query.filter_by(zip_code=zip_code).first()
        if tax:
            print(f"Updating existing tax record for zip_code: {zip_code}")
            tax.tax_rate = tax_rate
            tax.last_updated = datetime.utcnow()
        else:
            print(f"Creating new tax record for zip_code: {zip_code}")
            tax = Tax(zip_code=zip_code, tax_rate=tax_rate)
            db.session.add(tax)
        
        print("Attempting to commit changes to database")
        db.session.commit()
        print("Successfully committed changes to database")
        return jsonify({'success': True, 'message': 'Tax rate saved successfully'})
    except Exception as e:
        db.session.rollback()
        print(f"Error occurred while saving tax rate: {str(e)}")
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception details: {str(e)}")
        return jsonify({'error': f'An error occurred while saving the tax rate: {str(e)}'}), 500
    finally:
        print("Exiting save_tax_rate function")

@app.route('/customer-management', methods=['GET', 'POST'])
def customer_management():
    if request.method == 'POST':
        customer_name = request.form.get('customer_name')
        customer_address = request.form.get('customer_address')
        customer_state = request.form.get('customer_state')
        customer_city = request.form.get('customer_city')
        customer_zip = request.form.get('customer_zip')

        existing_customer = Customer.query.get(customer_name)

        if existing_customer:
            # Update existing customer
            existing_customer.customer_address = customer_address
            existing_customer.customer_state = customer_state
            existing_customer.customer_city = customer_city
            existing_customer.customer_zip = customer_zip
            flash("Customer updated successfully.", "success")
        else:
            # Create new customer
            new_customer = Customer(
                customer_name=customer_name,
                customer_address=customer_address,
                customer_state=customer_state,
                customer_city=customer_city,
                customer_zip=customer_zip
            )
            db.session.add(new_customer)
            flash("New customer created successfully.", "success")

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", "error")

        return redirect(url_for('customer_management'))

    # For GET request
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Number of customers per page
    
    customers_query = Customer.query.order_by(Customer.customer_name)
    total_customers = customers_query.count()
    pages = ceil(total_customers / per_page)
    
    customers = customers_query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'customer_management.html',
        customers=customers.items,
        page=page,
        pages=pages,
        total_customers=total_customers
    )

@app.route('/conversion-codes/manage', methods=['GET', 'POST'])
def manage_conversion_codes():
    if request.method == 'POST':
        data = request.get_json()
        code = data.get('code')
        csrf_token = data.get('csrf_token')

        if not code or not csrf_token:
            return jsonify(success=False, message='Missing required fields'), 400

        # Create or update the conversion code
        conversion_code = ConversionCode.query.filter_by(code=code).first()
        if not conversion_code:
            conversion_code = ConversionCode(code=code)
            db.session.add(conversion_code)
            db.session.commit()
            return jsonify(success=True, code=code), 200
        else:
            return jsonify(success=False, message='Conversion code already exists'), 400

    # For GET request
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Number of conversion codes per page

    conversion_codes = ConversionCode.query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        'ManageConversionCodes.html',
        conversion_codes=conversion_codes.items,
        page=page,
        total_pages=conversion_codes.pages
    )

@app.route('/conversion-codes/add-item', methods=['POST'])
def add_item_to_conversion_code():
    data = request.get_json()
    code = data.get('code')
    part_number = data.get('part_number')
    csrf_token = data.get('csrf_token')

    if not code or not part_number or not csrf_token:
        return jsonify(success=False, message='Missing required fields'), 400

    # Ensure the part number exists in the Inventory
    inventory_item = Inventory.query.filter_by(part_number=part_number).first()
    if not inventory_item:
        return jsonify(success=False, message='Part number not found in inventory'), 400

    # Add the item to the conversion code
    conversion_code = ConversionCode.query.filter_by(code=code).first()
    if conversion_code:
        conversion_code.inventory_items.append(inventory_item)
        db.session.commit()
        return jsonify(success=True, code=code), 200
    else:
        return jsonify(success=False, message='Conversion code not found'), 400

@app.route('/search-conversion-codes', methods=['GET'])
def search_conversion_codes():
    query = request.args.get('query', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    per_page = 10

    conversion_codes_query = ConversionCode.query
    if query:
        conversion_codes_query = conversion_codes_query.filter(ConversionCode.code.ilike(f'%{query}%'))

    conversion_codes = conversion_codes_query.paginate(page=page, per_page=per_page, error_out=False)
    conversion_code_data = [
        {
            'code': code.code,
            'items': [
                {'part_number': item.part_number, 'description': item.description}
                for item in code.inventory_items
            ]
        }
        for code in conversion_codes.items
    ]

    return jsonify({
        'codes': conversion_code_data,
        'current_page': conversion_codes.page,
        'total_pages': conversion_codes.pages
    })


@app.route('/conversion-codes/delete', methods=['POST'])
def delete_conversion_code():
    data = request.get_json()
    code = data.get('code')
    csrf_token = data.get('csrf_token')

    if not code or not csrf_token:
        return jsonify(success=False, message='Missing required fields'), 400

    conversion_code = ConversionCode.query.filter_by(code=code).first()
    if conversion_code:
        db.session.delete(conversion_code)
        db.session.commit()
        return jsonify(success=True), 200
    else:
        return jsonify(success=False, message='Conversion code not found'), 404


@app.route('/search-customers', methods=['GET'])
def search_customers():
    query = request.args.get('query', '')
    customers = Customer.query.filter(or_(
        Customer.customer_name.ilike(f'%{query}%'),
        Customer.customer_address.ilike(f'%{query}%'),
        Customer.customer_city.ilike(f'%{query}%')
    )).limit(10).all()
    
    return jsonify([{
        'customer_name': c.customer_name,
        'customer_address': c.customer_address,
        'customer_state': c.customer_state,
        'customer_city': c.customer_city,
        'customer_zip': c.customer_zip
    } for c in customers])

@app.route('/save-customer', methods=['POST'])
def save_customer():
    data = request.json
    existing_customer = Customer.query.filter_by(customer_name=data['customer_name']).first()
    
    if existing_customer:
        existing_customer.customer_address = data['customer_address']
        existing_customer.customer_state = data['customer_state']
        existing_customer.customer_city = data['customer_city']
        existing_customer.customer_zip = data['customer_zip']
        db.session.commit()
        return jsonify({'status': 'updated'})
    else:
        return jsonify({'status': 'new'})

@app.route('/create-customer', methods=['POST'])
def create_customer():
    data = request.json
    new_customer = Customer(
        customer_name=data['customer_name'],
        customer_address=data['customer_address'],
        customer_state=data['customer_state'],
        customer_city=data['customer_city'],
        customer_zip=data['customer_zip']
    )
    db.session.add(new_customer)
    db.session.commit()
    return jsonify({'status': 'created'})

@app.route('/get-bid-items/<bid_id>', methods=['GET'])
def get_bid_items(bid_id):
    try:
        bid = Bid.query.filter_by(bid_id=bid_id).first_or_404()
        items = BidFactorCodeItems.query.filter_by(bid_id=bid_id).order_by(BidFactorCodeItems.id).all()
        items_data = {}
        for item in items:
            if item.category not in items_data:
                items_data[item.category] = []
            items_data[item.category].append({
                'id': item.id,
                'part_number': item.part_number,
                'description': item.description,
                'factor_code': item.factor_code,
                'quantity': item.quantity,
                'cost': item.cost,
                'labor_hours': item.labor_hours,
                'line_ext_cost': item.line_ext_cost,
                'tax': item.tax,
                'additional_description': item.additional_description
            })
        
        for category in items_data:
            for index, item in enumerate(items_data[category], start=1):
                item['line_number'] = index

        response_data = {
            'items': items_data,
            'labor_rates': {
                'drains_labor_rate': float(bid.drains_labor_rate) if bid.drains_labor_rate is not None else None,
                'irrigation_labor_rate': float(bid.irrigation_labor_rate) if bid.irrigation_labor_rate is not None else None,
                'landscape_labor_rate': float(bid.landscape_labor_rate) if bid.landscape_labor_rate is not None else None,
                'maintenance_labor_rate': float(bid.maintenance_labor_rate) if bid.maintenance_labor_rate is not None else None,
                'local_sales_tax': float(bid.local_sales_tax) if bid.local_sales_tax is not None else None
            },
            'heading_info': {
                'customer_name': bid.customer_name,
                'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,
                'project_name': bid.project_name,
                'project_address': bid.project_address,
                'project_state': bid.project_state,
                'project_city': bid.project_city,
                'project_zip': bid.project_zip,
                'engineer_name': bid.engineer_name,
                'architect_name': bid.architect_name,
                'point_of_contact': bid.point_of_contact
            }
        }
        return jsonify(response_data), 200
    except Exception as e:
        app.logger.error(f"Error fetching bid items: {str(e)}")
        return jsonify({"error": "An error occurred while fetching bid items"}), 500
    
@app.route('/get-proposal-items/<bid_id>')
def get_proposal_items(bid_id):
    try:
        version_number = request.args.get('revision_number', type=int)

        app.logger.info(f"Fetching proposal items for bid_id: {bid_id} and version: {version_number}")

        if version_number is not None:
            proposal = Proposal.query.filter_by(bid_id=bid_id, revision_number=version_number).first_or_404()
        else:
            # If version number is not provided, get the latest version
            proposal = Proposal.query.filter_by(bid_id=bid_id).order_by(Proposal.revision_number.desc()).first_or_404()
            version_number = proposal.revision_number

        bid = Bid.query.filter_by(bid_id=bid_id).first_or_404()
        
        response_data = {
            'labor_rates': {
                'drains_labor_rate': float(bid.drains_labor_rate) if bid.drains_labor_rate is not None else None,
                'irrigation_labor_rate': float(bid.irrigation_labor_rate) if bid.irrigation_labor_rate is not None else None,
                'landscape_labor_rate': float(bid.landscape_labor_rate) if bid.landscape_labor_rate is not None else None,
                'maintenance_labor_rate': float(bid.maintenance_labor_rate) if bid.maintenance_labor_rate is not None else None,
                'local_sales_tax': float(bid.local_sales_tax) if bid.local_sales_tax is not None else None
            },
            'proposal_info': {
                'bid_id': proposal.bid_id,
                'project_name': proposal.project_name,
                'project_city': bid.project_city,  # Accessing from bid object
                'customer_name': proposal.customer_name,
                'special_notes': json.loads(proposal.special_notes) if proposal.special_notes else [],
                'terms_conditions': json.loads(proposal.terms_conditions) if proposal.terms_conditions else [],
                'revision_number': proposal.revision_number,
                'total_budget': float(proposal.total_budget) if proposal.total_budget else None,
                'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,  # Accessing from bid object
                'engineer_name': bid.engineer_name,  # Accessing from bid object
                'architect_name': bid.architect_name,  # Accessing from bid object
                'point_of_contact': bid.point_of_contact,  # Accessing from bid object
                'drains_total': float(bid.drains_total) if bid.drains_total else None,
                'irrigation_total': float(bid.irrigation_total) if bid.irrigation_total else None,
                'landscaping_total': float(bid.landscaping_total) if bid.landscaping_total else None,
                'maintenance_total': float(bid.maintenance_total) if bid.maintenance_total else None,
            },
            'customer_info': {
                'address': bid.customer.customer_address if bid.customer else None,
                'city': bid.customer.customer_city if bid.customer else None,
                'state': bid.customer.customer_state if bid.customer else None,
                'zip': bid.customer.customer_zip if bid.customer else None,
                'phone': bid.customer.customer_phone if hasattr(bid.customer, 'customer_phone') else None,
                'fax': bid.customer.customer_fax if hasattr(bid.customer, 'customer_fax') else None,
            },
            'options': [
                {
                    'description': option.description,
                    'amount': float(option.amount)
                } for option in proposal.options
            ],
            'proposal_amounts': [
                {
                    'description': amount.description,
                    'amount': float(amount.amount)
                } for amount in proposal.proposal_amounts
            ],
            'components': [
                {
                    'type': component.type,
                    'name': component.name,
                    'lines': [
                        {
                            'name': line.name,
                            'value': float(line.value)
                        } for line in component.lines
                    ]
                } for component in proposal.components
            ]
        }
        app.logger.info(f"Successfully fetched proposal items for bid_id: {bid_id} and version: {version_number}")
        return jsonify(response_data), 200
    except Exception as e:
        app.logger.error(f"Error fetching proposal items for bid_id {bid_id}: {str(e)}")
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500
    


@app.route('/delete_customer/<customer_name>', methods=['POST'])
def delete_customer(customer_name):
    app.logger.info(f"Attempting to delete customer: {customer_name}")
    customer = Customer.query.get(customer_name)
    if customer:
        try:
            db.session.delete(customer)
            db.session.commit()
            app.logger.info(f"Customer {customer_name} deleted successfully")
            flash('Customer deleted successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error deleting customer {customer_name}: {str(e)}")
            flash(f'Error deleting customer: {str(e)}', 'error')
    else:
        app.logger.warning(f"Customer not found: {customer_name}")
        flash('Customer not found.', 'error')
    return redirect(url_for('customer_management'))

@app.route('/save-factor-code-items/<int:bid_id>', methods=['POST'])
def save_factor_code_items(bid_id):
    data = request.json
    category = data['category']
    items = data['items']

    # Delete existing items for this bid and category
    BidFactorCodeItems.query.filter_by(bid_id=bid_id, category=category).delete()

    # Add new items
    for item in items:
        new_item = BidFactorCodeItems(
            bid_id=bid_id,
            factor_code=item['factor_code'],
            part_number=item['part_number'],
            quantity=item['quantity'],
            category=category
        )
        db.session.add(new_item)

    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/subbids/<int:subbid_id>/other-materials', methods=['GET'])
def get_subbid_other_materials(subbid_id):
    try:
        subbid = SubBid.query.get_or_404(subbid_id)
        other_materials = []
        
        for item in subbid.items:
            factor_code = item.factor_code
            if factor_code:
                factor_items = FactorCodeItems.query.filter_by(factor_code=factor_code).all()
                for factor_item in factor_items:
                    inventory_item = Inventory.query.get(factor_item.part_number)
                    if inventory_item:
                        existing_material = next((m for m in other_materials if m['part_number'] == inventory_item.part_number), None)
                        if existing_material:
                            existing_material['quantity'] += factor_item.quantity * item.quantity
                        else:
                            other_materials.append({
                                'part_number': inventory_item.part_number,
                                'description': inventory_item.description,
                                'quantity': factor_item.quantity * item.quantity,
                                'cost': inventory_item.cost
                            })
        
        return jsonify(other_materials)
    except Exception as e:
        app.logger.error(f"Error fetching sub-bid other materials: {str(e)}")
        return jsonify({"error": "An error occurred while fetching sub-bid other materials"}), 500


@app.route('/api/subbids/<bid_id>', methods=['GET'])
def get_subbids(bid_id):
    category = request.args.get('category')
    app.logger.info(f"Fetching sub-bids for bid ID: {bid_id}, category: {category}")
    
    try:
        query = SubBid.query.filter_by(bid_id=bid_id)
        if category:
            query = query.filter_by(category=category)
        
        subbids = query.all()
        app.logger.info(f"Found {len(subbids)} sub-bids")
        
        subbids_data = []
        for subbid in subbids:
            items = SubBidItem.query.filter_by(sub_bid_id=subbid.sub_bid_id).all()
            subbid_data = {
                'id': subbid.sub_bid_id,
                'category': subbid.category,
                'name': subbid.name,
                'total_cost': float(subbid.total_cost) if subbid.total_cost is not None else 0,
                'labor_hours': float(subbid.labor_hours) if subbid.labor_hours is not None else 0,
                'items': [{
                    'id': item.id,
                    'part_number': item.part_number,
                    'description': unquote(item.description) if item.description else '',
                    'factor_code': item.factor_code,
                    'quantity': float(item.quantity) if item.quantity is not None else 0,
                    'cost': float(item.cost) if item.cost is not None else 0,
                    'labor_hours': float(item.labor_hours) if item.labor_hours is not None else 0,
                    'line_ext_cost': float(item.line_ext_cost) if item.line_ext_cost is not None else 0,
                } for item in items],
                'other_materials': []  # You may need to implement this if you have other materials
            }
            subbids_data.append(subbid_data)
        
        app.logger.info(f"Returning sub-bids data: {subbids_data}")
        return jsonify(subbids_data)
    except Exception as e:
        app.logger.error(f"Error fetching sub-bids: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/subbids/<int:subbid_id>', methods=['GET'])
def get_subbid(subbid_id):
    try:
        app.logger.info(f"Fetching sub-bid with ID: {subbid_id}")
        subbid = SubBid.query.get_or_404(subbid_id)
        app.logger.info(f"Found sub-bid: {subbid}")
        
        # Fetch sub-bid items
        items = SubBidItem.query.filter_by(sub_bid_id=subbid_id).all()
        app.logger.info(f"Found {len(items)} items for sub-bid {subbid_id}")
        
        subbid_data = {
            'id': subbid.sub_bid_id,
            'category': subbid.category,
            'name': subbid.name,
            'total_cost': float(subbid.total_cost) if subbid.total_cost is not None else 0,
            'labor_hours': float(subbid.labor_hours) if subbid.labor_hours is not None else 0,
            'items': [{
                'id': item.id,
                'part_number': item.part_number,
                'description': item.description,
                'factor_code': item.factor_code,
                'quantity': float(item.quantity) if item.quantity is not None else 0,
                'cost': float(item.cost) if item.cost is not None else 0,
                'labor_hours': float(item.labor_hours) if item.labor_hours is not None else 0,
                'line_ext_cost': float(item.line_ext_cost) if item.line_ext_cost is not None else 0,
            } for item in items],
            'other_materials': []  # You may need to implement this if you have other materials
        }
        
        app.logger.info(f"Returning sub-bid data: {subbid_data}")
        return jsonify(subbid_data)
    except Exception as e:
        app.logger.error(f"Error fetching sub-bid {subbid_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/subbids/<string:bid_id>', methods=['POST'])
def create_subbid(bid_id):
    try:
        data = request.json
        if not data:
            raise BadRequest("No JSON data received")

        category = data.get('category')
        name = data.get('name')
        total_cost = data.get('total_cost', 0)
        labor_hours = data.get('labor_hours', 0)

        if not category or not name:
            raise BadRequest("Category and name are required")

        new_subbid = SubBid(
            bid_id=bid_id,
            category=category,
            name=name,
            total_cost=total_cost,
            labor_hours=labor_hours
        )
        db.session.add(new_subbid)
        db.session.commit()

        return jsonify({"success": True, "sub_bid_id": new_subbid.sub_bid_id}), 201
    except BadRequest as e:
        db.session.rollback()
        app.logger.error(f"Bad request error: {str(e)}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Unexpected error creating sub-bid: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "An unexpected error occurred while creating the sub-bid", "details": str(e)}), 500

@app.route('/api/customer/<string:customer_name>', methods=['PUT'])
def update_customer(customer_name):
    customer = Customer.query.get_or_404(customer_name)
    data = request.json

    try:
        customer.customer_address = data.get('customer_address', customer.customer_address)
        customer.customer_state = data.get('customer_state', customer.customer_state)
        customer.customer_city = data.get('customer_city', customer.customer_city)
        customer.customer_zip = data.get('customer_zip', customer.customer_zip)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Customer updated successfully'}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/customer/rename/<string:original_name>', methods=['PUT'])
def rename_customer(original_name):
    customer = Customer.query.get_or_404(original_name)
    data = request.json
    new_name = data.get('customer_name')

    if not new_name:
        return jsonify({'success': False, 'message': 'New customer name is required'}), 400

    if new_name == original_name:
        return jsonify({'success': True, 'message': 'No change in customer name'}), 200

    try:
        # Check if the new name already exists
        existing_customer = Customer.query.filter_by(customer_name=new_name).first()
        if existing_customer:
            return jsonify({'success': False, 'message': 'A customer with this name already exists'}), 409

        # Create a new customer record
        new_customer = Customer(
            customer_name=new_name,
            customer_address=data.get('customer_address', customer.customer_address),
            customer_state=data.get('customer_state', customer.customer_state),
            customer_city=data.get('customer_city', customer.customer_city),
            customer_zip=data.get('customer_zip', customer.customer_zip)
        )
        db.session.add(new_customer)

        # Update all bids associated with the old customer name
        Bid.query.filter_by(customer_name=original_name).update({'customer_name': new_name})

        # Delete the old customer record
        db.session.delete(customer)

        db.session.commit()
        return jsonify({'success': True, 'message': 'Customer renamed successfully'}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/subbids/<int:subbid_id>', methods=['PUT'])
def update_subbid(subbid_id):
    try:
        subbid = SubBid.query.get_or_404(subbid_id)
        data = request.json
        subbid.name = data.get('name', subbid.name)
        subbid.total_cost = data.get('total_cost', subbid.total_cost)
        subbid.labor_hours = data.get('labor_hours', subbid.labor_hours)
        
        # Update or create sub-bid items
        SubBidItem.query.filter_by(sub_bid_id=subbid_id).delete()
        for item_data in data.get('items', []):
            new_item = SubBidItem(
                sub_bid_id=subbid_id,
                part_number=item_data['part_number'],
                description=item_data['description'],
                factor_code=item_data['factor_code'],
                quantity=item_data['quantity'],
                cost=item_data['cost'],
                labor_hours=item_data['labor_hours'],
                line_ext_cost=item_data['line_ext_cost']
            )
            db.session.add(new_item)
        
        db.session.commit()
        return jsonify({'message': 'Sub-bid updated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating sub-bid: {str(e)}")
        return jsonify({'error': str(e)}), 400
    
@app.route('/api/subbids/<int:subbid_id>/items/<int:item_index>', methods=['DELETE'])
def delete_subbid_item(subbid_id, item_index):
    subbid = SubBid.query.get_or_404(subbid_id)
    items = SubBidItem.query.filter_by(sub_bid_id=subbid_id).all()
    
    if item_index < 0 or item_index >= len(items):
        return jsonify({'error': 'Item index out of range'}), 400
    
    item_to_delete = items[item_index]
    db.session.delete(item_to_delete)
    
    # Recalculate totals
    remaining_items = [item for item in items if item != item_to_delete]
    subbid.total_cost = sum(item.cost * item.quantity for item in remaining_items)
    subbid.labor_hours = sum(item.labor_hours for item in remaining_items)
    
    db.session.commit()
    
    return jsonify({'message': 'Sub-bid item deleted successfully', 'new_total_cost': subbid.total_cost, 'new_labor_hours': subbid.labor_hours})

@app.route('/api/subbids/<int:subbid_id>', methods=['DELETE'])
def delete_subbid(subbid_id):
    try:
        subbid = SubBid.query.get_or_404(subbid_id)
        db.session.delete(subbid)
        db.session.commit()
        return jsonify({'message': 'Sub-bid deleted successfully', 'success': True}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting sub-bid {subbid_id}: {str(e)}")
        return jsonify({'error': str(e), 'success': False}), 400
    
@app.route('/get-other-materials/<int:bid_id>/<category>', methods=['GET'])
def get_other_materials(bid_id, category):
    try:
        if category.startswith('subbid-'):
            subbid_id = int(category.split('-')[1])
            return get_subbid_other_materials(subbid_id)
        
        items = BidFactorCodeItems.query.filter_by(bid_id=bid_id, category=category).all()
        other_materials = []
        
        app.logger.info(f"Fetched items for bid_id: {bid_id}, category: {category} - {items}")

        for item in items:
            factor_code = item.factor_code
            if factor_code:
                factor_items = FactorCodeItems.query.filter_by(factor_code=factor_code).all()
                for factor_item in factor_items:
                    inventory_item = Inventory.query.get(factor_item.part_number)
                    if inventory_item:
                        existing_material = next((m for m in other_materials if m['part_number'] == inventory_item.part_number), None)
                        if existing_material:
                            existing_material['quantity'] += factor_item.quantity * item.quantity
                        else:
                            other_materials.append({
                                'part_number': inventory_item.part_number,
                                'description': inventory_item.description,
                                'quantity': factor_item.quantity * item.quantity,
                                'cost': inventory_item.cost
                            })
        
        app.logger.info(f"Other materials: {other_materials}")
        return jsonify(other_materials)
    except Exception as e:
        app.logger.error(f"Error fetching other materials: {str(e)}")
        return jsonify({"error": "An error occurred while fetching other materials"}), 500

@app.route('/manage-groups', methods=['GET', 'POST'])
def manage_groups():
    if request.method == 'POST':
        member_id = request.form.get('member_id')
        name = request.form.get('name')
        category = request.form.get('category')
        company = request.form.get('company')
        address = request.form.get('address')
        phone_number = request.form.get('phone_number')
        try:
            if member_id:
                # Update existing member
                if category == 'Architect':
                    member = Architect.query.get(member_id)
                elif category == 'Engineer':
                    member = Engineer.query.get(member_id)
                elif category == 'Vendor':
                    member = Vendor.query.get(member_id)
                else:
                    return jsonify({'success': False, 'error': 'Invalid category'})
                if member:
                    member.name = name
                    member.company = company
                    member.address = address
                    member.phone_number = phone_number
                    db.session.commit()
                    return jsonify({'success': True, 'message': 'Member updated successfully'})
                else:
                    return jsonify({'success': False, 'error': 'Member not found'})
            else:
                # Add new member
                if category == 'Architect':
                    new_member = Architect(name=name, company=company, address=address, phone_number=phone_number)
                elif category == 'Engineer':
                    new_member = Engineer(name=name, company=company, address=address, phone_number=phone_number)
                elif category == 'Vendor':
                    new_member = Vendor(name=name, company=company, address=address, phone_number=phone_number)
                else:
                    return jsonify({'success': False, 'error': 'Invalid category'})
                db.session.add(new_member)
                db.session.commit()
                # Return the new member's data
                return jsonify({
                    'success': True,
                    'message': 'New member added successfully',
                    'member': {
                        'id': new_member.id,
                        'name': new_member.name,
                        'category': category,
                        'company': new_member.company,
                        'address': new_member.address,
                        'phone_number': new_member.phone_number
                    }
                })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

    # For GET request (unchanged)
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Number of members per page
    
    # Query all types of group members
    architects = select(Architect, db.literal('Architect').label('category'))
    engineers = select(Engineer, db.literal('Engineer').label('category'))
    vendors = select(Vendor, db.literal('Vendor').label('category'))
    
    union_query = union(architects, engineers, vendors).alias('union_query')
    
    # Use the column reference from the aliased union query
    query = select(union_query).order_by(union_query.c.name)
    
    total_members = db.session.execute(select(db.func.count()).select_from(union_query)).scalar()
    pages = ceil(total_members / per_page)
    
    members = db.session.execute(
        query.offset((page - 1) * per_page).limit(per_page)
    ).fetchall()
    group_members = [
        {
            'id': m.id,
            'name': m.name,
            'company': m.company,
            'address': m.address,
            'phone_number': m.phone_number,
            'category': m.category
        }
        for m in members
    ]
    return render_template(
        'manage_groups.html',
        group_members=group_members,
        page=page,
        pages=pages,
        total_members=total_members
    )

@app.route('/delete-group-member/<int:member_id>/<category>', methods=['POST'])
def delete_group_member(member_id, category):
    if category == 'Architect':
        member = Architect.query.get(member_id)
    elif category == 'Engineer':
        member = Engineer.query.get(member_id)
    elif category == 'Vendor':
        member = Vendor.query.get(member_id)
    else:
        return jsonify({'success': False, 'error': 'Invalid category'}), 400

    if member:
        try:
            db.session.delete(member)
            db.session.commit()
            return jsonify({'success': True})
        except SQLAlchemyError as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    else:
        return jsonify({'success': False, 'error': 'Member not found'}), 404

@app.route('/update-group-member', methods=['POST'])
def update_group_member():
    data = request.get_json()
    name = data.get('original_name')
    new_name = data.get('name')
    category = data.get('category')
    company = data.get('company')
    address = data.get('address')
    phone_number = data.get('phone_number')

    # Find the member by the original name
    member = Architect.query.filter_by(name=name).first() or \
             Engineer.query.filter_by(name=name).first() or \
             Vendor.query.filter_by(name=name).first()

    if member:
        try:
            # Update the member’s details
            member.name = new_name
            member.category = category
            member.company = company
            member.address = address
            member.phone_number = phone_number

            db.session.commit()
            return jsonify({'success': True}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    else:
        return jsonify({'success': False, 'error': 'Member not found'}), 404



@app.route('/search-projects', methods=['GET'])
def search_projects():
    query = request.args.get('query')
    if not query:
        return jsonify([])

    projects = Project.query.filter(Project.project_name.ilike(f"%{query}%")).all()
    return jsonify([{
        "project_name": project.project_name,
        "project_zip": project.project_zip,
        "point_of_contact": project.point_of_contact,
        "project_address": project.project_address,
        "project_city": project.project_city,
        "project_state": project.project_state,
        "contact_phone_number": project.contact_phone_number  # Make sure this line is included
    } for project in projects])

@app.route('/search-parts', methods=['GET'])
def search_parts():
    query = request.args.get('query', '').strip().lower()
    
    if query:
        parts = Inventory.query.filter(
            db.or_(
                Inventory.part_number.ilike(f'%{query}%'),
                Inventory.description.ilike(f'%{query}%')
            )
        ).limit(10).all()
    else:
        parts = Inventory.query.limit(10).all()

    results = [{
        'part_number': part.part_number,
        'description': part.description,
        'cost': float(part.cost) if part.cost is not None else 0.0  # Ensure cost is serializable
    } for part in parts]

    return jsonify(results)

@app.route('/api/proposal/<bid_id>', methods=['GET'])
def get_proposal_data(bid_id):
    proposal = Proposal.query.filter_by(bid_id=bid_id).first()
    if not proposal:
        return jsonify({"error": "Proposal not found"}), 404

    bid = Bid.query.get(bid_id)
    if not bid:
        return jsonify({"error": "Associated bid not found"}), 404

    proposal_data = {
        'bid_id': proposal.bid_id,
        'project_name': proposal.project_name,
        'customer_name': proposal.customer_name,
        'special_notes': proposal.special_notes,
        'terms_conditions': proposal.terms_conditions,
        'revision_number': proposal.revision_number,
        'total_budget': float(proposal.total_budget) if proposal.total_budget else None,
        'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,
        'engineer_name': bid.engineer_name,
        'architect_name': bid.architect_name,
        'point_of_contact': bid.point_of_contact,
        'local_sales_tax': float(bid.local_sales_tax) if bid.local_sales_tax else None,
        'drains_total': float(bid.drains_total) if bid.drains_total else None,
        'irrigation_total': float(bid.irrigation_total) if bid.irrigation_total else None,
        'landscaping_total': float(bid.landscaping_total) if bid.landscaping_total else None,
        'maintenance_total': float(bid.maintenance_total) if bid.maintenance_total else None,
    }

    return jsonify(proposal_data)

@app.route('/bid-management', methods=['GET', 'POST'])
def bid_management():
    if request.method == 'POST':
        bid_id = request.form.get('bidID')
        project_name = request.form.get('projectName')
        description = request.form.get('description')
        customer_name = request.form.get('customerName')
        project_zip = request.form.get('projectZip')
        tax_rate = request.form.get('taxRate')
        engineer_name = request.form.get('engineerName')
        architect_name = request.form.get('architectName')

        if not bid_id or not project_name:
            return jsonify({"success": False, "message": "Bid ID and Project Name are required."})

        existing_bid = Bid.query.filter_by(bid_id=bid_id).first()
        project = Project.query.filter_by(project_name=project_name).first()

        if not project:
            return jsonify({"success": False, "message": "Selected project not found."})

        point_of_contact = project.point_of_contact

        try:
            if existing_bid:
                existing_bid.project_name = project_name
                existing_bid.description = description
                existing_bid.customer_name = customer_name
                existing_bid.local_sales_tax = float(tax_rate) if tax_rate else 0
                existing_bid.point_of_contact = point_of_contact
                existing_bid.engineer_name = engineer_name
                existing_bid.architect_name = architect_name
                message = "Bid updated successfully."
            else:
                new_bid = Bid(
                    bid_id=bid_id,
                    project_name=project_name,
                    description=description,
                    customer_name=customer_name,
                    bid_date=datetime.now().date(),
                    local_sales_tax=float(tax_rate) if tax_rate else 0,
                    point_of_contact=point_of_contact,
                    engineer_name=engineer_name,
                    architect_name=architect_name
                )
                db.session.add(new_bid)
                message = "New bid created successfully."

            db.session.commit()
            return jsonify({"success": True, "message": message, "bid_id": bid_id})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"An error occurred: {str(e)}"})

    # For GET request
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Query for all bids without status filter
    bids_query = db.session.query(
        Bid.bid_id.label('id'),
        Bid.project_name,
        Bid.customer_name,
        Bid.engineer_name,
        Bid.architect_name,
        Bid.bid_date.label('date'),
        Bid.point_of_contact,
        Bid.local_sales_tax
    ).order_by(desc(Bid.bid_date))

    # Get total count and paginate
    total_items = bids_query.count()
    pages = ceil(total_items / per_page)
    items = bids_query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'BidManagement.html',
        items=items.items,
        page=page,
        pages=pages,
        total_items=total_items
    )

@app.route('/proposal-management', methods=['GET', 'POST'])
def proposal_management():
    if request.method == 'POST':
        bid_id = request.form.get('bidID')
        project_name = request.form.get('projectName')
        customer_name = request.form.get('customerName')
        engineer_name = request.form.get('engineerName')
        architect_name = request.form.get('architectName')
        special_notes = request.form.get('specialNotes')
        terms_conditions = request.form.get('termsConditions')

        if not bid_id or not project_name:
            return jsonify({"success": False, "message": "Bid ID and Project Name are required."})

        existing_bid = Bid.query.filter_by(bid_id=bid_id).first()
        if not existing_bid:
            return jsonify({"success": False, "message": "Associated bid not found."})

        existing_proposal = Proposal.query.filter_by(bid_id=bid_id).first()

        try:
            if existing_proposal:
                existing_proposal.project_name = project_name
                existing_proposal.customer_name = customer_name
                existing_proposal.special_notes = special_notes
                existing_proposal.terms_conditions = terms_conditions
                existing_proposal.revision_number += 1
                message = "Proposal updated successfully."
            else:
                new_proposal = Proposal(
                    bid_id=bid_id,
                    project_name=project_name,
                    customer_name=customer_name,
                    special_notes=special_notes,
                    terms_conditions=terms_conditions,
                    revision_number=1,
                    total_budget=existing_bid.total_budget
                )
                db.session.add(new_proposal)
                message = "New proposal created successfully."

            # Update associated bid information
            existing_bid.project_name = project_name
            existing_bid.customer_name = customer_name
            existing_bid.engineer_name = engineer_name
            existing_bid.architect_name = architect_name

            db.session.commit()
            return jsonify({"success": True, "message": message, "bid_id": bid_id})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"An error occurred: {str(e)}"})

    # For GET request
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Query for all proposals
    proposals_query = db.session.query(
        Proposal.bid_id.label('id'),
        Proposal.project_name,
        Proposal.customer_name,
        Bid.engineer_name,
        Bid.architect_name,
        Bid.bid_date.label('date'),
        Bid.point_of_contact,
        Proposal.revision_number,
        Proposal.total_budget
    ).join(Bid, Proposal.bid_id == Bid.bid_id).order_by(desc(Proposal.created_at))

    # Get total count and paginate
    total_items = proposals_query.count()
    pages = ceil(total_items / per_page)
    items = proposals_query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'ProposalManagement.html',
        items=items.items,
        page=page,
        pages=pages,
        total_items=total_items
    )

@app.route('/api/bids', methods=['GET'])
def get_all_bids():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20

        bids_query = Bid.query.order_by(desc(Bid.bid_date))

        total_items = bids_query.count()
        pages = ceil(total_items / per_page)
        items = bids_query.paginate(page=page, per_page=per_page, error_out=False)

        bids_data = []
        for bid in items.items:
            bids_data.append({
                'bid_id': bid.bid_id,
                'project_name': bid.project_name,
                'customer_name': bid.customer_name,
                'engineer_name': bid.engineer_name,
                'architect_name': bid.architect_name,
                'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,
                'point_of_contact': bid.point_of_contact,
                'local_sales_tax': float(bid.local_sales_tax) if bid.local_sales_tax else None,
                'status': bid.status
            })

        return jsonify({
            'bids': bids_data,
            'current_page': page,
            'pages': pages,
            'total': total_items
        })
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500

@app.route('/inventory/search', methods=['GET'])
def search_inventory():
    query = request.args.get('query', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    ITEMS_PER_PAGE = 50  # Define how many items you want per page

    # Base query for Inventory items
    inventory_query = db.session.query(Inventory)

    if query:
        # Check if the query exactly matches any conversion code (case-insensitive)
        conversion_code_match = db.session.query(ConversionCode).filter(
            func.lower(ConversionCode.code) == func.lower(query)
        ).first()

        if conversion_code_match:
            # If there's an exact match, retrieve the connected part numbers
            inventory_query = inventory_query.filter(
                Inventory.conversion_codes.contains(conversion_code_match)
            )
            total_items = inventory_query.count()
            inventory_items = inventory_query.all()  # Fetch all matching items
        else:
            # Add search conditions for part number, description, or conversion code
            inventory_query = inventory_query.outerjoin(Inventory.conversion_codes).filter(
                or_(
                    func.lower(Inventory.part_number).contains(func.lower(query)),
                    func.lower(Inventory.description).contains(func.lower(query)),
                    func.lower(ConversionCode.code).contains(func.lower(query))
                )
            )
            # Get total number of items matching the query
            total_items = inventory_query.count()
            
            # Apply pagination
            inventory_items = inventory_query.offset((page - 1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()
    else:
        # If no query, apply pagination to all inventory items
        total_items = inventory_query.count()
        inventory_items = inventory_query.offset((page - 1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()

    # Serialize the inventory items
    inventory_data = [
        {
            'part_number': item.part_number,
            'description': item.description,
            'cost': float(item.cost) if item.cost is not None else 0.0,
            'factor_code': item.factor_code,
            'conversion_codes': [code.code for code in item.conversion_codes]  # Include conversion codes
        }
        for item in inventory_items
    ]
    return jsonify({
        'inventory': inventory_data,
        'total_pages': ceil(total_items / ITEMS_PER_PAGE),
        'current_page': page
    })


@app.route('/factors/remove_item', methods=['POST'])
def remove_item():
    data = request.get_json()
    factor_code = data.get('factor_code')
    part_number = data.get('part_number')

    print(f"Attempting to remove item: factor_code={factor_code}, part_number={part_number}")

    # Query for the item based on factor_code and part_number
    item_to_remove = FactorCodeItems.query.filter_by(factor_code=factor_code, part_number=part_number).first()

    if not item_to_remove:
        # Log the query results for debugging
        all_items = FactorCodeItems.query.all()
        print("All FactorCodeItems:")
        for item in all_items:
            print(f"ID: {item.id}, Factor Code: {item.factor_code}, Part Number: {item.part_number}, Quantity: {item.quantity}")
        return jsonify({'success': False, 'message': 'Item not found.'})

    try:
        # Remove the item
        db.session.delete(item_to_remove)
        db.session.commit()
        print(f"Item removed successfully: ID={item_to_remove.id}, Factor Code={item_to_remove.factor_code}, Part Number={item_to_remove.part_number}")
        return jsonify({'success': True, 'message': 'Item removed successfully'})
    except Exception as e:
        db.session.rollback()
        print(f"Error occurred while removing item: {str(e)}")
        return jsonify({'success': False, 'message': f'Error occurred: {str(e)}'})
    
@app.route('/conversion-codes/remove-item', methods=['POST'])
def remove_conversion_code_item():
    data = request.get_json()
    part_number = data.get('part_number')
    conversion_code = data.get('conversion_code')

    if not part_number or not conversion_code:
        return jsonify({'error': 'Invalid input'}), 400

    # Find the inventory item by part number
    inventory_item = Inventory.query.filter_by(part_number=part_number).first()
    if not inventory_item:
        return jsonify({'error': 'Item not found'}), 404

    # Find the conversion code
    conversion_code_obj = ConversionCode.query.filter_by(code=conversion_code).first()
    if not conversion_code_obj:
        return jsonify({'error': 'Conversion code not found'}), 404

    # Remove the conversion code from the inventory item's conversion codes
    if conversion_code_obj in inventory_item.conversion_codes:
        inventory_item.conversion_codes.remove(conversion_code_obj)
        db.session.commit()
        return jsonify({'success': 'Item removed successfully'})
    else:
        return jsonify({'error': 'Conversion code not associated with this item'}), 404

@app.route('/search-factor-codes', methods=['GET'])
def search_factor_codes():
    query = request.args.get('query', '').strip().lower()
    
    if len(query) < 2:
        return jsonify(factor_codes=[])

    results = FactorCode.query.filter(
        db.or_(
            FactorCode.factor_code.ilike(f'%{query}%'),
            FactorCode.description.ilike(f'%{query}%')
        )
    ).limit(50).all()  # Limit to 50 results for performance

    factors = [{
        'factor_code': factor.factor_code,
        'description': factor.description,
        'labor_hours': factor.labor_hours,
        'items': [{
            'part_number': item.part_number,
            'description': item.inventory_item.description if item.inventory_item else '',
            'quantity': item.quantity
        } for item in factor.items],
        'total_material_cost': sum(item.quantity * (item.inventory_item.cost or 0) for item in factor.items)
    } for factor in results]
    return jsonify(factor_codes=factors)

@app.route('/delete_project/<path:project_name>', methods=['POST'])
def delete_project(project_name):
    app.logger.info(f"Attempting to delete project: {project_name}")
    decoded_project_name = unquote(project_name)
    project = Project.query.get_or_404(decoded_project_name)
    try:
        db.session.delete(project)
        db.session.commit()
        app.logger.info(f"Project {decoded_project_name} deleted successfully")
        flash('Project deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting project {decoded_project_name}: {str(e)}")
        flash(f'Error deleting project: {str(e)}', 'error')
    return redirect(url_for('manage_projects'))

@app.route('/manage-projects', methods=['GET', 'POST'])
@login_required
def manage_projects():
    if request.method == 'POST':
        project_name = request.form.get('project_name')
        project_address = request.form.get('project_address')
        project_state = request.form.get('project_state')
        project_city = request.form.get('project_city')
        project_zip = request.form.get('project_zip')
        point_of_contact = request.form.get('point_of_contact')  # New field
        contact_phone_number = request.form.get('contact_phone_number')  # New field

        existing_project = Project.query.filter_by(project_name=project_name).first()

        try:
            if existing_project:
                # Update existing project
                existing_project.project_address = project_address
                existing_project.project_state = project_state
                existing_project.project_city = project_city
                existing_project.project_zip = project_zip
                existing_project.point_of_contact = point_of_contact  # New field
                existing_project.contact_phone_number = contact_phone_number  # New field
                flash("Project updated successfully.", "success")
            else:
                # Create new project
                new_project = Project(
                    project_name=project_name,
                    project_address=project_address,
                    project_state=project_state,
                    project_city=project_city,
                    project_zip=project_zip,
                    point_of_contact=point_of_contact,  # New field
                    contact_phone_number=contact_phone_number  # New field
                )
                db.session.add(new_project)
                flash("New project created successfully.", "success")

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", "error")

        return redirect(url_for('manage_projects'))

    # For GET request
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Number of projects per page
    
    projects_query = Project.query.order_by(Project.project_name)
    total_projects = projects_query.count()
    pages = ceil(total_projects / per_page)
    
    projects = projects_query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'Manage_Projects.html',
        projects=projects.items,
        page=page,
        pages=pages,
        total_projects=total_projects
    )

@app.route('/api/project/<project_name>', methods=['GET', 'PUT'])
def update_project(project_name):
    project = Project.query.get_or_404(project_name)
    
    if request.method == 'GET':
        return jsonify({
            'project_name': project.project_name,
            'project_address': project.project_address,
            'project_state': project.project_state,
            'project_city': project.project_city,
            'project_zip': project.project_zip
        })
    
    elif request.method == 'PUT':
        data = request.json
        try:
            project.project_address = data.get('project_address', project.project_address)
            project.project_state = data.get('project_state', project.project_state)
            project.project_city = data.get('project_city', project.project_city)
            project.project_zip = data.get('project_zip', project.project_zip)
            
            db.session.commit()
            return jsonify({'success': True, 'message': 'Project updated successfully'}), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/autocomplete-factor-codes', methods=['GET'])
def autocomplete_factor_codes():
    query = request.args.get('query', '').strip().lower()
    
    if query:
        results = FactorCode.query.filter(FactorCode.factor_code.ilike(f'%{query}%')).all()
    else:
        results = FactorCode.query.limit(10).all()  # Optionally limit to 10 results if no query is provided

    factors = [{
        'factor_code': factor.factor_code,
        'description': factor.description,
        'labor_hours': factor.labor_hours
    } for factor in results]

    return jsonify(factor_codes=factors)

@app.route('/')
def home():
    # Basic homepage with links to other parts of the application
    return render_template('Home.html')

@app.route('/add', methods=['POST'])
def add_item():
    part_num = request.form['PartNum']
    quantity = int(request.form['Quantity'])
    item = next((item for item in inventory if item['PartNum'] == part_num), None)
    if item:
        # Append to bid_items in session
        session['bid_items'].append({**item, "Quantity": quantity, "Cost": float(item['Cost'])})
        session.modified = True  # Mark the session as modified to save changes
        total_cost = sum(item['Cost'] * item['Quantity'] for item in session['bid_items'])
        return jsonify(success=True, bid_items=session['bid_items'], total_cost=total_cost)
    else:
        return jsonify(success=False)

@app.route('/factors/update', methods=['POST'])
def update_factor():
    try:
        # Extract data from the request
        factor_id = request.form.get('Factor_ID')
        description = request.form.get('Description')
        labor_hours = request.form.get('LaborHours')

        # Validate input
        if not factor_id:
            raise ValueError("Factor ID is required")
        if not description:
            raise ValueError("Description is required")
        if labor_hours is not None:
            try:
                labor_hours = float(labor_hours)
            except ValueError:
                raise ValueError("Labor Hours must be a valid number")

        # Fetch the factor from the database
        factor = FactorCode.query.filter_by(factor_code=factor_id).first()
        if not factor:
            raise ValueError(f"Factor with ID {factor_id} not found")

        # Update the factor
        factor.description = description
        if labor_hours is not None:
            factor.labor_hours = labor_hours

        # Commit the changes to the database
        db.session.commit()

        return jsonify({
            'success': True, 
            'message': 'Factor updated successfully',
            'factor': {
                'factor_id': factor.factor_code,
                'description': factor.description,
                'labor_hours': factor.labor_hours
            }
        })

    except ValueError as ve:
        db.session.rollback()
        app.logger.error(f"ValueError: {str(ve)}")
        return jsonify({'success': False, 'message': str(ve)}), 400

    except (SQLAlchemyError, DBAPIError) as e:
        db.session.rollback()
        app.logger.error(f"Database Error: {str(e)}")
        return jsonify({'success': False, 'message': 'A database error occurred. Please try again later.'}), 500

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Unexpected Error: {str(e)}")
        return jsonify({'success': False, 'message': 'An unexpected error occurred. Please try again later.'}), 500

    finally:
        db.session.close()


# Add this new route to your Flask application
@app.route('/update-factor-code-item', methods=['POST'])
def update_factor_code_item():
    data = request.json
    factor_code = data.get('factor_code')
    part_number = data.get('part_number')
    new_quantity = data.get('new_quantity')
    
    try:
        # Find the FactorCodeItems entry
        item = FactorCodeItems.query.filter_by(factor_code=factor_code, part_number=part_number).first()
        
        if item:
            item.quantity = float(new_quantity)
            db.session.commit()
            return jsonify(success=True, message="Item updated successfully")
        else:
            return jsonify(success=False, message="Item not found"), 404
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500

@app.route('/factors/manage', methods=['GET', 'POST'])
def manage_factors():
    ITEMS_PER_PAGE = 10

    if request.method == 'POST':
        factor_code = request.form.get('Factor_ID')
        description = request.form.get('Description')
        labor_hours = request.form.get('LaborHours')

        factor = FactorCode.query.filter_by(factor_code=factor_code).first()
        if factor:
            factor.description = description
            factor.labor_hours = float(labor_hours) if labor_hours else None
        else:
            factor = FactorCode(
                factor_code=factor_code,
                description=description,
                labor_hours=float(labor_hours) if labor_hours else None
            )
            db.session.add(factor)

        db.session.commit()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': True,
                'message': 'New factor added successfully!',
                'factor': {
                    'factor_code': factor.factor_code,
                    'description': factor.description,
                    'labor_hours': str(factor.labor_hours) if factor.labor_hours is not None else 'N/A',
                    'items': [],
                    'total_material_cost': '0.00'
                }
            })

        return redirect(url_for('manage_factors'))

    page = request.args.get('page', 1, type=int)
    query = request.args.get('query', '').strip()

    if query:
        factors_query = FactorCode.query.filter(FactorCode.factor_code.ilike(f'%{query}%'))
    else:
        factors_query = FactorCode.query

    total_items = factors_query.count()
    total_pages = ceil(total_items / ITEMS_PER_PAGE)
    factors = factors_query.offset((page - 1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()

    factor_codes = [factor.factor_code for factor in factors]

    # Fetch all related items in a single query
    items_query = db.session.query(FactorCodeItems, Inventory) \
        .join(Inventory, FactorCodeItems.part_number == Inventory.part_number) \
        .filter(FactorCodeItems.factor_code.in_(factor_codes)) \
        .all()

    # Group items by factor_code
    items_by_factor = {}
    for item in items_query:
        if item.FactorCodeItems.factor_code not in items_by_factor:
            items_by_factor[item.FactorCodeItems.factor_code] = []
        items_by_factor[item.FactorCodeItems.factor_code].append(item)

    # Fetch active bids for all factors in a single query
    active_bids_query = db.session.query(BidFactorCodeItems.factor_code, BidFactorCodeItems.bid_id) \
        .filter(BidFactorCodeItems.factor_code.in_(factor_codes)) \
        .distinct() \
        .all()

    # Group active bids by factor_code
    active_bids_by_factor = {}
    for factor_code, bid_id in active_bids_query:
        if factor_code not in active_bids_by_factor:
            active_bids_by_factor[factor_code] = []
        active_bids_by_factor[factor_code].append(bid_id)

    serialized_factors = []
    for factor in factors:
        items = items_by_factor.get(factor.factor_code, [])

        total_material_cost = sum(
            (item.Inventory.cost or 0) * item.FactorCodeItems.quantity
            for item in items
            if item.Inventory is not None
        )

        serialized_items = [
            {
                'part_number': item.Inventory.part_number,
                'description': item.Inventory.description,
                'quantity': str(item.FactorCodeItems.quantity),
                'cost': str(item.Inventory.cost * item.FactorCodeItems.quantity if item.Inventory.cost is not None else 0)
            } for item in items if item.Inventory is not None
        ]

        active_bid_numbers = active_bids_by_factor.get(factor.factor_code, [])

        serialized_factors.append({
            'factor_code': factor.factor_code,
            'description': factor.description,
            'labor_hours': str(factor.labor_hours) if factor.labor_hours is not None else 'N/A',
            'items': serialized_items,
            'total_material_cost': str(total_material_cost),
            'active_bids': active_bid_numbers
        })

    return render_template(
        'ManageFactors.html',
        factors=serialized_factors,
        current_page=page,
        total_pages=total_pages,
        query=query
    )

@app.route('/delete_bid/<bid_id>', methods=['POST'])
def delete_bid(bid_id):
    bid = Bid.query.filter_by(bid_id=bid_id).first_or_404()
    db.session.delete(bid)
    db.session.commit()
    return redirect(url_for('bid_management'))

@app.route('/inventory/manage', methods=['GET', 'POST'])
def manage_inventory():
    # Constants
    ITEMS_PER_PAGE = 50
    MAX_ITEMS = 500

    if request.method == 'POST':
        part_num = request.form.get('PartNum')
        description = request.form.get('Description')
        cost = request.form.get('Cost')
        factor_code = request.form.get('FactorCode')

        # Validate and convert cost to a float, default to 0.0 if invalid or None
        try:
            cost = float(cost) if cost else 0.0
        except ValueError:
            cost = 0.0

        # Ensure the factor code exists
        factor = FactorCode.query.filter_by(factor_code=factor_code).first()
        if not factor:
            return jsonify({"error": "Factor code not found."}), 404

        # Check if this is an existing item or a new one
        inventory_item = Inventory.query.filter_by(part_number=part_num).first()
        if inventory_item:
            # Update the existing item
            inventory_item.description = description
            inventory_item.cost = cost
            inventory_item.factor_code = factor_code
        else:
            # Create a new item
            new_item = Inventory(
                part_number=part_num,
                description=description,
                cost=cost,
                factor_code=factor_code
            )
            db.session.add(new_item)

        # Commit changes to the database
        db.session.commit()
        return redirect(url_for('manage_inventory'))

    # For GET request or initial page load
    page = request.args.get('page', 1, type=int)
    part_number_search = request.args.get('part_number_search', '').strip()
    description_search = request.args.get('description_search', '').strip()

    if part_number_search:
        # Exact match search for part numbers with pagination
        query = Inventory.query.filter(Inventory.part_number.ilike(f"%{part_number_search}%"))
        total_items = query.count()
        inventory_items = query.offset((page - 1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()
    elif description_search:
        # Load all inventory items for fuzzy search on descriptions
        all_inventory_items = Inventory.query.limit(MAX_ITEMS).all()
        
        # Prepare a list of descriptions for fuzzy matching and ensure no None values
        inventory_descriptions = [item.description if item.description else "" for item in all_inventory_items]

        # Perform fuzzy matching on descriptions
        matches = process.extractBests(
            description_search,
            inventory_descriptions,
            scorer=fuzz.ratio,  # Using fuzz.ratio for more accurate matching
            limit=MAX_ITEMS  # Limit to a maximum of 500 items
        )

        # Filter matches to ensure they meet a high accuracy threshold (e.g., 70%)
        threshold = 25
        high_accuracy_matches = [match for match in matches if match[1] >= threshold]

        # Extract matched inventory items based on the fuzzy matches
        matched_descriptions = [match[0] for match in high_accuracy_matches]
        inventory_items = [item for item in all_inventory_items if item.description in matched_descriptions]

        # Paginate the filtered results
        total_items = len(inventory_items)
        start = (page - 1) * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        inventory_items = inventory_items[start:end]
    else:
        # Default query if no search terms are provided
        query = Inventory.query
        total_items = query.count()
        inventory_items = query.offset((page - 1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()

    total_pages = ceil(total_items / ITEMS_PER_PAGE)
    factors = FactorCode.query.all()  # Get all factor codes to populate the dropdown

    # Ensure cost is not None for display purposes
    for item in inventory_items:
        if item.cost is None:
            item.cost = 0.0

    return render_template(
        'ManageInventory.html',
        inventory=inventory_items,
        factors=factors,
        part_number_search=part_number_search,
        description_search=description_search,
        current_page=page,
        total_pages=total_pages
    )


@app.route('/inventory/update', methods=['POST'])
def update_inventory():
    part_num = request.form.get('PartNum')
    description = request.form.get('Description')
    cost = request.form.get('Cost')
    factor_code = request.form.get('FactorCode')

    # Validate and convert cost to a float, default to 0.0 if invalid or None
    try:
        cost = float(cost) if cost else 0.0
    except ValueError:
        return jsonify({"success": False, "message": "Invalid cost value"}), 400

    # Ensure the factor code exists
    factor = FactorCode.query.filter_by(factor_code=factor_code).first()
    if not factor:
        return jsonify({"success": False, "message": "Factor code not found"}), 404

    # Update the inventory item
    inventory_item = Inventory.query.filter_by(part_number=part_num).first()
    if inventory_item:
        inventory_item.description = description
        inventory_item.cost = cost
        inventory_item.factor_code = factor_code
        db.session.commit()
        return jsonify({"success": True, "message": "Inventory item updated successfully"})
    else:
        return jsonify({"success": False, "message": "Inventory item not found"}), 404

@app.route('/inventory/check-delete', methods=['POST'])
def check_delete_inventory():
    part_num = request.form.get('PartNum')
    inventory_item = Inventory.query.filter_by(part_number=part_num).first()
    if inventory_item:
        # Check if the item is used in any active bids
        active_bids = BidFactorCodeItems.query.filter_by(part_number=part_num).distinct(BidFactorCodeItems.bid_id).all()
        if active_bids:
            bid_numbers = ', '.join([item.bid_id for item in active_bids])
            return jsonify({
                'can_delete': False,
                'message': f'This item is used in the following active bids: {bid_numbers}. Please remove it from these bids before deleting.'
            })

        # Find all factor codes that contain this part number
        factor_codes = db.session.query(FactorCode.factor_code).join(FactorCodeItems).filter(
            FactorCodeItems.part_number == part_num
        ).distinct().all()
        factor_codes = [fc[0] for fc in factor_codes]  # Extract factor codes from result

        if factor_codes:
            return jsonify({
                'can_delete': True,
                'has_factor_codes': True,
                'factor_codes': factor_codes,
                'message': f'This item is contained in the following factor codes: {", ".join(factor_codes)}. Are you sure you want to delete it?'
            })
        else:
            return jsonify({'can_delete': True, 'has_factor_codes': False})
    else:
        return jsonify({'error': 'Item not found'}), 404


@app.route('/inventory/delete', methods=['POST'])
def delete_inventory():
    part_num = request.form.get('PartNum')
    confirm = request.form.get('confirm', 'false')
    
    inventory_item = Inventory.query.filter_by(part_number=part_num).first()
    if inventory_item:
        # Check if the item is used in any active bids
        active_bids = BidFactorCodeItems.query.filter_by(part_number=part_num).first()
        if active_bids:
            return jsonify({'success': False, 'message': 'This item is in an active bid and cannot be deleted.'}), 400

        if confirm.lower() == 'true':
            try:
                # Delete the item from FactorCodeItems
                FactorCodeItems.query.filter_by(part_number=part_num).delete()
                
                # Delete the inventory item
                db.session.delete(inventory_item)
                db.session.commit()
                return jsonify({'success': True, 'message': 'Inventory item and its associations have been deleted.'})
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error deleting inventory item: {str(e)}")
                return jsonify({'success': False, 'message': f'Error deleting item: {str(e)}'}), 500
        else:
            return jsonify({'success': False, 'message': 'Deletion cancelled.'})
    else:
        return jsonify({'success': False, 'message': 'Error: Item not found'}), 404
    

@app.route('/factors/delete', methods=['POST'])
def delete_factor_code():
    factor_id = request.form.get('Factor_ID')
    factor = FactorCode.query.get(factor_id)
    
    if not factor:
        return jsonify({'success': False, 'message': 'Factor code not found'}), 404

    # Check if the factor is used in any active bids
    active_bids = BidFactorCodeItems.query.filter_by(factor_code=factor_id).distinct(BidFactorCodeItems.bid_id).all()
    if active_bids:
        bid_numbers = ', '.join([item.bid_id for item in active_bids])
        return jsonify({
            'success': False, 
            'message': f'This factor code is contained in the following bid(s): {bid_numbers}. Please remove this factor code from the bid(s) and try again.'
        }), 400

    try:
        # Delete associated FactorCodeItems
        FactorCodeItems.query.filter_by(factor_code=factor_id).delete()
        
        # Delete the factor code
        db.session.delete(factor)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Factor code deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500
    
# Add these global variables
inventory_last_update_time = None

# Add this function to update the inventory cache
def update_inventory_cache():
    global inventory_last_update_time
    with app.app_context():
        inventory_items = Inventory.query.all()
        inventory_data = [
            {
                'part_number': item.part_number,
                'description': item.description,
                'cost': float(item.cost) if item.cost is not None else 0.0,
                'factor_code': item.factor_code
            }
            for item in inventory_items
        ]
        cache.set('inventory', inventory_data)
        inventory_last_update_time = datetime.now()

    
# Update the /inventory route to use the cache
@app.route('/inventory', methods=['GET'])
@cache.cached(timeout=3600)  # Cache for 1 hour
def get_inventory():
    inventory_data = cache.get('inventory')
    if inventory_data is None:
        update_inventory_cache()
        inventory_data = cache.get('inventory')
    return jsonify(inventory_data)


@app.route('/factors/add_item', methods=['POST'])
def add_item_to_factor():
    factor_id = request.form.get('Factor_ID')
    part_number = request.form.get('PartNumber')
    quantity = request.form.get('Quantity')

    print(f"Adding item: factor_id={factor_id}, part_number={part_number}, quantity={quantity}")

    # Input validation
    if not factor_id or not part_number or not quantity:
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    try:
        quantity = float(quantity)
    except ValueError:
        return jsonify({'success': False, 'message': 'Quantity must be a number'}), 400

    # Fetch the factor and inventory item
    factor = FactorCode.query.filter_by(factor_code=factor_id).first()
    inventory_item = Inventory.query.filter_by(part_number=part_number).first()

    if not factor or not inventory_item:
        return jsonify({'success': False, 'message': 'Invalid Factor ID or Part Number'}), 404

    # Check if the item already exists for this factor
    existing_item = FactorCodeItems.query.filter_by(factor_code=factor_id, part_number=part_number).first()
    if existing_item:
        existing_item.quantity = quantity
        print(f"Updated existing item: {existing_item}")
    else:
        # Create a new instance of FactorCodeItems and add it to the factor
        new_factor_item = FactorCodeItems(
            factor_code=factor_id,
            part_number=part_number,
            quantity=quantity
        )
        db.session.add(new_factor_item)
        print(f"Added new item: {new_factor_item}")

    try:
        db.session.commit()
        print("Database commit successful")
        return jsonify({'success': True, 'message': 'Item added successfully', 'factor_id': factor_id}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error occurred while adding item: {str(e)}")
        return jsonify({'success': False, 'message': f'Error occurred: {str(e)}'}), 500

# Modify your existing route for fetching factor code items
@app.route('/get-factor-code-items/<factor_code>', methods=['GET'])
@cache.memoize(timeout=3600)  # Cache individual factor code items for 1 hour
def get_factor_code_items(factor_code):
    try:
        app.logger.info(f"Fetching items for factor code: {factor_code}")
        
        factor = FactorCode.query.filter_by(factor_code=factor_code).first()

        if not factor:
            app.logger.warning(f"Factor code not found: {factor_code}")
            return jsonify({"error": f"Factor code '{factor_code}' not found"}), 404

        items = []
        for item in factor.items:
            try:
                inventory_item = item.inventory_item
                if inventory_item:
                    items.append({
                        "part_number": inventory_item.part_number,
                        "description": inventory_item.description,
                        "quantity": float(item.quantity),
                        "cost": float(inventory_item.cost) if inventory_item.cost is not None else 0.0
                    })
            except Exception as item_error:
                app.logger.error(f"Error processing item for factor code {factor_code}: {str(item_error)}")

        response_data = {
            "factor_code": factor.factor_code,
            "description": factor.description,
            "labor_hours": float(factor.labor_hours) if factor.labor_hours is not None else 0.0,
            "items": items
        }
        
        app.logger.info(f"Successfully fetched items for factor code: {factor_code}")
        return jsonify(response_data)

    except Exception as e:
        app.logger.error(f"Error fetching factor code items for {factor_code}: {str(e)}")
        return jsonify({"error": f"An error occurred while fetching factor code items: {str(e)}"}), 500
    


@app.route('/get-factor-code-and-labor-hours/<part_num>', methods=['GET'])
def get_factor_code_and_labor_hours(part_num):
    # Query the Inventory table to find the item by part number
    inventory_item = Inventory.query.filter_by(part_number=part_num).first()

    if inventory_item:
        # Get the associated factor code from the inventory item
        factor_code = inventory_item.factor_code

        # Query the FactorCode table to find the labor hours for the factor code
        factor_code_item = FactorCode.query.filter_by(factor_code=factor_code).first()

        if factor_code_item:
            # Return the factor code and labor hours as a JSON response
            return jsonify({
                'factor_code': factor_code_item.factor_code,
                'labor_hours': factor_code_item.labor_hours
            })
        else:
            # If the factor code is not found, return an error response
            return jsonify({
                'factor_code': 'N/A',
                'labor_hours': 0
            }), 404
    else:
        # If the part number is not found in the inventory, return an error response
        return jsonify({
            'factor_code': 'N/A',
            'labor_hours': 0
        }), 404
def update_factor_codes_cache():
    with app.app_context():
        factor_items = FactorCode.query.all()
        factor_data = []
        for factor in factor_items:
            total_material_cost = sum(
                item.quantity * item.inventory_item.cost 
                for item in factor.items 
                if item.inventory_item and item.inventory_item.cost is not None
            )
            factor_data.append({
                'factor_code': factor.factor_code,
                'description': factor.description,
                'labor_hours': factor.labor_hours,
                'items': [
                    {
                        'part_number': item.inventory_item.part_number,
                        'description': item.inventory_item.description,
                        'quantity': item.quantity,
                        'cost': item.inventory_item.cost
                    } for item in factor.items if item.inventory_item
                ],
                'total_material_cost': total_material_cost
            })
        cache.set('factor_codes', factor_data)


# Modify the check_and_update_cache function to include inventory
def check_and_update_cache():
    global last_update_time, inventory_last_update_time
    current_time = datetime.now()
    if last_update_time is None or (current_time - last_update_time) > timedelta(minutes=60):
        update_factor_codes_cache()
    if inventory_last_update_time is None or (current_time - inventory_last_update_time) > timedelta(minutes=60):
        update_inventory_cache()
    threading.Timer(60, check_and_update_cache).start()

# Start the background update process
check_and_update_cache()

@app.route('/factors')
@cache.cached(timeout=3600)  # Cache for 1 hour
def get_factors():
    factor_data = cache.get('factor_codes')
    if factor_data is None:
        update_factor_codes_cache()
        factor_data = cache.get('factor_codes')
    return jsonify(factor_data)

@app.route('/add-update-bid', methods=['GET', 'POST'])
def add_update_bid():
    if request.method == 'POST':
        bid_data = request.form.to_dict()
        
        # Convert the form data to the format expected by save_bid
        formatted_bid_data = {
            'bid_id': bid_data.get('bidID'),
            'heading_info': {
                'bid_date': bid_data.get('bidDate'),
                'customer_name': bid_data.get('customerName'),
                'project_name': bid_data.get('projectName'),
                'engineer_name': bid_data.get('engineerName'),
                'architect_name': bid_data.get('architectName'),
                'point_of_contact': bid_data.get('pointOfContact'),
            },
            'customer': {
                'name': bid_data.get('customerName'),
                'address': bid_data.get('customerAddress'),
                'state': bid_data.get('customerState'),
                'city': bid_data.get('customerCity'),
                'zip_code': bid_data.get('customerZip')
            },
            'project': {
                'name': bid_data.get('projectName'),
                'address': bid_data.get('projectAddress'),
                'state': bid_data.get('projectState'),
                'city': bid_data.get('projectCity'),
                'zip_code': bid_data.get('projectZip')
            },
            'labor_rates': {
                'drains_labor_rate': float(bid_data.get('laborRateDrains', 0)),
                'irrigation_labor_rate': float(bid_data.get('laborRateIrrigation', 0)),
                'landscape_labor_rate': float(bid_data.get('laborRateLandscape', 0)),
                'maintenance_labor_rate': float(bid_data.get('laborRateMaintenance', 0)),
                'subcontractor_labor_rate': float(bid_data.get('laborRateSubcontractor', 0)),
                'local_sales_tax': float(bid_data.get('localSalesTax', 0))
            },
            'engineer_name': bid_data.get('engineerName'),
            'architect_name': bid_data.get('architectName'),
            'point_of_contact': bid_data.get('pointOfContact'),
            'contact_phone_number': bid_data.get('contactPhoneNumber')
        }
        
        try:
            # Call save_bid function
            result = save_bid(formatted_bid_data)
            
            if result.get('success'):
                flash("Bid created/updated successfully with ID: " + result['bid_id'], "success")
                return jsonify({"success": True, "bid_id": result['bid_id']})
            else:
                flash("Error: " + result.get('message', 'Unknown error occurred'), "error")
                return jsonify({"success": False, "message": result.get('message', 'Unknown error occurred')}), 400
        except Exception as e:
            app.logger.error(f"Error in add_update_bid: {str(e)}")
            return jsonify({"success": False, "message": "An unexpected error occurred"}), 500
    else:
        # For GET requests, you might want to pre-populate the form with default values
        default_labor_rates = get_default_labor_rates()
        return render_template('AddUpdateBid.html', default_labor_rates=default_labor_rates)

@app.route('/get-factor-code-labor-hours/<factor_code>', methods=['GET'])
def get_factor_code_labor_hours(factor_code):
    factor = FactorCode.query.filter_by(factor_code=factor_code).first()
    if factor:
        return jsonify({'labor_hours': factor.labor_hours})
    else:
        return jsonify({'error': 'Factor code not found'}), 404
    
@app.route('/save-sub-bid', methods=['POST'])
def save_sub_bid():
    try:
        app.logger.info("Received save-sub-bid request")
        sub_bid_data = request.json
        if not sub_bid_data:
            raise BadRequest("No sub-bid data received")
        app.logger.info(f"Received sub-bid data: {sub_bid_data}")

        bid_id = sub_bid_data.get('bid_id')
        sub_bid_id = sub_bid_data.get('sub_bid_id')
        
        if not bid_id:
            raise BadRequest("Bid ID is required")

        # Fetch existing sub-bid or create a new one
        if sub_bid_id:
            sub_bid = SubBid.query.get(sub_bid_id)
            if not sub_bid:
                raise BadRequest(f"Sub-bid with ID {sub_bid_id} not found")
        else:
            sub_bid = SubBid(bid_id=bid_id)
            db.session.add(sub_bid)

        # Update sub-bid details
        sub_bid.name = sub_bid_data.get('name')
        sub_bid.category = sub_bid_data.get('category')
        sub_bid.total_cost = sub_bid_data.get('total_cost', 0)
        sub_bid.labor_hours = sub_bid_data.get('labor_hours', 0)

        # Save sub-bid items
        SubBidItem.query.filter_by(sub_bid_id=sub_bid.sub_bid_id).delete()
        for item_data in sub_bid_data.get('items', []):
            new_item = SubBidItem(
                sub_bid_id=sub_bid.sub_bid_id,
                part_number=item_data.get('part_number'),
                description=item_data.get('description'),
                factor_code=item_data.get('factor_code'),
                quantity=float(item_data.get('quantity', 0)),
                cost=float(item_data.get('cost', 0)),
                labor_hours=float(item_data.get('labor_hours', 0)),
                line_ext_cost=float(item_data.get('line_ext_cost', 0))
            )
            db.session.add(new_item)

        db.session.commit()
        app.logger.info(f"Sub-bid saved successfully: ID {sub_bid.sub_bid_id}")
        return jsonify({"success": True, "sub_bid_id": sub_bid.sub_bid_id})

    except BadRequest as e:
        db.session.rollback()
        app.logger.error(f"Bad request error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 400

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Unexpected error saving sub-bid: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "error": "An unexpected error occurred while saving the sub-bid", "details": str(e)}), 500

@app.route('/save-bid', methods=['POST'])
def save_bid(bid_data=None):
    try:
        app.logger.info("Received save-bid request")
        if bid_data is None:
            bid_data = request.json
        if not bid_data:
            raise BadRequest("No bid data received")
        app.logger.info(f"Received bid data: {bid_data}")
        bid_id = bid_data.get('bid_id')
        if not bid_id:
            raise BadRequest("Bid ID is required")
        app.logger.info(f"Processing bid with ID: {bid_id}")
        
        # Fetch existing bid or create new one
        bid = Bid.query.filter_by(bid_id=bid_id).first()
        if not bid:
            app.logger.info(f"Creating new bid with ID: {bid_id}")
            bid = Bid(bid_id=bid_id)
            db.session.add(bid)
        else:
            app.logger.info(f"Updating existing bid with ID: {bid_id}")
        
        # Update bid fields from heading_info
        heading_info = bid_data.get('heading_info', {})
        for key, value in heading_info.items():
            if hasattr(bid, key) and key != 'bid_id':  # Prevent changing bid_id
                setattr(bid, key, value)
        
        # Update labor rates
        labor_rates = bid_data.get('labor_rates', {})
        for key, value in labor_rates.items():
            if hasattr(bid, key):
                setattr(bid, key, float(value))
        
        # Update category totals
        category_totals = bid_data.get('category_totals')
        if category_totals:
            app.logger.info(f"Using provided category totals: {category_totals}")
            bid.landscaping_total = float(category_totals.get('landscape', 0))
            bid.drains_total = float(category_totals.get('drains', 0))
            bid.irrigation_total = float(category_totals.get('irrigation', 0))
            bid.maintenance_total = float(category_totals.get('maintenance', 0))
            bid.total_budget = float(bid_data.get('total_budget', 0))
        else:
            app.logger.info("Calculating category totals from line items")
            category_totals = {'landscape': 0, 'drains': 0, 'irrigation': 0, 'maintenance': 0}
            for category, category_items in bid_data.get('items', {}).items():
                if category.lower() in category_totals:
                    for item in category_items:
                        line_ext_cost = float(item.get('line_ext_cost', 0))
                        category_totals[category.lower()] += line_ext_cost
                        app.logger.debug(f"Added {line_ext_cost} to {category.lower()} total")
            
            bid.landscaping_total = category_totals['landscape']
            bid.drains_total = category_totals['drains']
            bid.irrigation_total = category_totals['irrigation']
            bid.maintenance_total = category_totals['maintenance']
            bid.total_budget = sum(category_totals.values())

        app.logger.info(f"Final category totals: Landscape: {bid.landscaping_total}, Drains: {bid.drains_total}, "
                        f"Irrigation: {bid.irrigation_total}, Maintenance: {bid.maintenance_total}")
        app.logger.info(f"Total budget: {bid.total_budget}")

        # Save line items
        with db.session.no_autoflush:
            BidFactorCodeItems.query.filter_by(bid_id=bid_id).delete()
            for category, category_items in bid_data.get('items', {}).items():
                for item in category_items:
                    new_item = BidFactorCodeItems(
                        bid_id=bid_id,
                        category=category,
                        factor_code=item.get('factor_code', ''),
                        part_number=item.get('part_number', ''),
                        description=unquote(item.get('description', '')),
                        quantity=float(item.get('quantity', 0)),
                        cost=float(item.get('cost', 0)),
                        labor_hours=float(item.get('labor_hours', 0)),
                        line_ext_cost=float(item.get('line_ext_cost', 0)),
                        tax=float(item.get('tax', 0)),
                        additional_description=unquote(item.get('additional_description', ''))
                    )
                    db.session.add(new_item)

        db.session.commit()
        app.logger.info(f"Bid saved successfully: ID {bid.bid_id}")
        return {"success": True, "bid_id": bid.bid_id}
    except BadRequest as e:
        db.session.rollback()
        app.logger.error(f"Bad request error: {str(e)}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Unexpected error saving bid: {str(e)}")
        app.logger.error(traceback.format_exc())
        return {"success": False, "error": "An unexpected error occurred while saving the bid", "details": str(e)}
    
@app.route('/api/proposals', methods=['GET', 'POST'])
def api_proposals():
    if request.method == 'GET':
        # Fetch all proposals ordered by creation date descending
        proposals = Proposal.query.order_by(Proposal.created_at.desc()).all()
        
        # Prepare the response data
        proposals_data = [{
            'bid_id': proposal.bid_id,
            'project_name': proposal.project_name,
            'customer_name': proposal.customer_name,
            'revision_number': proposal.revision_number
            # 'status' field removed
        } for proposal in proposals]
        
        return jsonify({'proposals': proposals_data}), 200

    elif request.method == 'POST':
        try:
            data = request.get_json()
            bid_id = data.get('bid_id')

            if not bid_id:
                return jsonify({'success': False, 'message': 'Missing bid_id'}), 400

            # Check if the Bid exists
            bid = Bid.query.filter_by(bid_id=bid_id).first()
            if not bid:
                return jsonify({'success': False, 'message': 'Bid not found'}), 404

            # Check if a Proposal already exists for this Bid
            proposal = Proposal.query.filter_by(bid_id=bid_id).first()

            if proposal:
                # Increment revision_number
                proposal.revision_number += 1
                proposal.updated_at = datetime.utcnow()
                db.session.commit()
                return jsonify({'success': True, 'message': 'Proposal revision incremented successfully'}), 200
            else:
                # Create a new Proposal
                new_proposal = Proposal(
                    bid_id=bid_id,
                    customer_name=bid.customer_name,
                    project_name=bid.project_name,
                    total_budget=bid.total_budget,
                    revision_number=1
                )
                db.session.add(new_proposal)
                db.session.commit()
                return jsonify({'success': True, 'message': 'Proposal started successfully'}), 201

        except SQLAlchemyError as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'Database error', 'error': str(e)}), 500

        except Exception as e:
            return jsonify({'success': False, 'message': 'An error occurred', 'error': str(e)}), 500

@app.route('/create-proposal')
def create_proposal():
    bid_id = request.args.get('bid_id')
    revision = request.args.get('revision', 1, type=int)
    app.logger.info(f"Attempting to create/open proposal for bid_id: {bid_id}, revision: {revision}")
    
    if not bid_id:
        app.logger.error("No bid_id provided")
        flash('No bid ID provided', 'error')
        return redirect(url_for('home'))
    
    bid = db.session.get(Bid, bid_id)
    if not bid:
        app.logger.error(f"Bid not found for bid_id: {bid_id}")
        flash('Bid not found', 'error')
        return redirect(url_for('home'))
    
    proposal_data = {}
    try:
        customer = db.session.query(Customer).filter_by(customer_name=bid.customer_name).first()
        project = db.session.query(Project).filter_by(project_name=bid.project_name).first()
        proposal = Proposal.query.filter_by(bid_id=bid_id).first()
        
        def safe_get(obj, attr, default=''):
            return getattr(obj, attr, default) if obj else default

        proposal_data = {
            'bidID': bid.bid_id,
            'customerName': bid.customer_name,
            'customerAddress': safe_get(customer, 'customer_address'),
            'customerCity': safe_get(customer, 'customer_city'),
            'customerState': safe_get(customer, 'customer_state'),
            'customerZip': safe_get(customer, 'customer_zip'),
            'projectName': bid.project_name,
            'projectAddress': safe_get(project, 'project_address'),
            'projectCity': safe_get(bid, 'project_city'),
            'projectState': safe_get(project, 'project_state'),
            'projectZip': safe_get(project, 'project_zip'),
            'bidDate': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else '',
            'engineerName': safe_get(bid, 'engineer_name'),
            'architectName': safe_get(bid, 'architect_name'),
            'landscapingTotal': float(bid.landscaping_total or 0),
            'drainsTotal': float(bid.drains_total or 0),
            'irrigationTotal': float(bid.irrigation_total or 0),
            'maintenanceTotal': float(bid.maintenance_total or 0),
            'totalBudget': float(bid.total_budget or 0),
            'revisionNumber': revision,
            'localSalesTax': float(bid.local_sales_tax or 0),
            'drainsLaborRate': float(bid.drains_labor_rate or 0),
            'irrigationLaborRate': float(bid.irrigation_labor_rate or 0),
            'landscapeLaborRate': float(bid.landscape_labor_rate or 0),
            'maintenanceLaborRate': float(bid.maintenance_labor_rate or 0),
            'pointOfContact': safe_get(bid, 'point_of_contact'),
        }
        
        if proposal:
            proposal_data.update({
                'specialNotes': safe_get(proposal, 'special_notes'),
                'termsConditions': safe_get(proposal, 'terms_conditions'),
            })
            
            proposal_amounts = ProposalAmount.query.filter_by(proposal_id=proposal.id).all()
            proposal_data['proposalAmounts'] = [
                {'description': pa.description, 'amount': float(pa.amount or 0)}
                for pa in proposal_amounts
            ]
            
            proposal_options = ProposalOption.query.filter_by(proposal_id=proposal.id).all()
            proposal_data['proposalOptions'] = [
                {'description': po.description, 'amount': float(po.amount or 0)}
                for po in proposal_options
            ]
        
        session['proposal_data'] = proposal_data
    except Exception as e:
        app.logger.error(f"Error processing proposal data: {str(e)}")
        flash('An error occurred while processing the proposal data', 'error')
        return redirect(url_for('home'))
    
    next_tab = request.args.get('next_tab', 'Heading')
    return render_template('create_proposal.html', next_tab=next_tab, proposal_data=proposal_data, bid=bid)


@app.route('/api/bid/<bid_id>', methods=['GET'])
def get_bid_data(bid_id):
    try:
        app.logger.info(f"Fetching bid data for bid_id: {bid_id}")
        bid = Bid.query.get(bid_id)
        if not bid:
            return jsonify({"error": "Bid not found"}), 404
        
        def safe_float(value):
            try:
                return float(value) if value is not None else None
            except (ValueError, TypeError):
                return None

        bid_data = {
            'bid_id': bid.bid_id,
            'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,
            'customer_name': bid.customer_name,
            'project_name': bid.project_name,
            'project_address': bid.project_address,
            'project_city': bid.project_city,
            'project_state': bid.project_state,
            'project_zip': bid.project_zip,
            'architect_name': bid.architect_name,
            'engineer_name': bid.engineer_name,
            'point_of_contact': bid.point_of_contact,
            'drains_labor_rate': safe_float(bid.drains_labor_rate),
            'irrigation_labor_rate': safe_float(bid.irrigation_labor_rate),
            'landscape_labor_rate': safe_float(bid.landscape_labor_rate),
            'maintenance_labor_rate': safe_float(bid.maintenance_labor_rate),
            'local_sales_tax': safe_float(bid.local_sales_tax),
            'total_budget': safe_float(bid.total_budget),
            'landscaping_total': safe_float(bid.landscaping_total),
            'drains_total': safe_float(bid.drains_total),
            'irrigation_total': safe_float(bid.irrigation_total),
            'maintenance_total': safe_float(bid.maintenance_total),
            'description': bid.description,
            'revision_number': bid.revision_number if hasattr(bid, 'revision_number') else None
        }

        app.logger.info(f"Successfully fetched bid data for bid_id: {bid_id}")
        app.logger.debug(f"Bid data: {bid_data}")  # Log the bid data for debugging
        return jsonify(bid_data)
    except Exception as e:
        app.logger.error(f"Error fetching bid data for bid_id {bid_id}: {str(e)}")
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500


@app.route('/save-project', methods=['POST'])
def save_project():
    try:
        data = request.json
        project_name = data.get('project_name')
        
        # Check if the project already exists
        project = Project.query.get(project_name)
        
        if project:
            # Update existing project
            project.project_address = data.get('project_address', project.project_address)
            project.project_state = data.get('project_state', project.project_state)
            project.project_city = data.get('project_city', project.project_city)
            project.project_zip = data.get('project_zip', project.project_zip)
        else:
            # Create new project
            project = Project(
                project_name=project_name,
                project_address=data.get('project_address'),
                project_state=data.get('project_state'),
                project_city=data.get('project_city'),
                project_zip=data.get('project_zip')
            )
            db.session.add(project)
        
        db.session.commit()
        return jsonify({"success": True, "message": "Project saved successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/create-proposal_report')
def create_proposal_report():
    proposal_data = session.get('proposal_data', {})
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    # Adjust y as needed
    y = 750
    
    # Use proposal_data to draw text on the PDF
    c.drawString(100, y, f"Bid ID: {proposal_data.get('bidID', 'N/A')}")
    # Continue for other fields
    
    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='proposal.pdf', mimetype='application/pdf')

@app.route('/submit-proposal-data', methods=['POST'])
def submit_proposal_data():
    proposal_data = request.form.to_dict()
    session['proposal_data'] = proposal_data
    
    # Save proposal data to the database
    bid_id = proposal_data.get('bidID')
    bid = Bid.query.get(bid_id)
    if bid:
        # Update other bid fields as necessary, but don't change the status
        db.session.commit()
    
    next_tab = proposal_data.get('next_tab', 'Heading')
    return redirect(url_for('create_proposal', bid_id=bid_id, next_tab=next_tab))

# New route to list proposals
@app.route('/proposals', methods=['GET'])
def list_proposals():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    proposals = Bid.query.filter_by(status='Proposal').paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "message": "Proposal saved successfully",
        "redirect": url_for('create_proposal', bid_id=bid_id, next_tab=next_tab)
    })
# New route to view a specific proposal
@app.route('/proposal/<bid_id>', methods=['GET'])
def view_proposal(bid_id):
    bid = Bid.query.get_or_404(bid_id)
    return render_template('view_proposal.html', proposal=bid)

# New route to generate PDF
@app.route('/generate-proposal-pdf/<bid_id>', methods=['GET'])
def generate_proposal_pdf(bid_id):
    bid = Bid.query.get_or_404(bid_id)
    
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    
    # Add content to the PDF
    p.drawString(100, 750, f"Proposal for Bid: {bid.bid_id}")
    p.drawString(100, 730, f"Customer: {bid.customer_name}")
    p.drawString(100, 710, f"Project: {bid.project_name}")
    # Add more details...
    
    p.showPage()
    p.save()
    
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f'proposal_{bid.bid_id}.pdf', mimetype='application/pdf')


@app.route('/add-blank-line-item', methods=['POST'])
def add_blank_line_item():
    data = request.json
    wrapper_id = data.get('wrapper_id')
    bid_id = data.get('bid_id')

    if not wrapper_id or not bid_id:
        return jsonify({'error': 'Missing wrapper_id or bid_id'}), 400

    try:
        # Create a new blank line item
        new_item = BidFactorCodeItems(
            bid_id=bid_id,
            category=wrapper_id.replace('Wrapper', '').lower(),
            part_number='',
            description='',
            factor_code='',
            quantity=1,
            cost=0,
            labor_hours=0,
            line_ext_cost=0,
            tax=0,
            additional_description=''
        )
        db.session.add(new_item)
        db.session.commit()

        # Get the total number of items for this category
        total_items = BidFactorCodeItems.query.filter_by(
            bid_id=bid_id, 
            category=wrapper_id.replace('Wrapper', '').lower()
        ).count()

        return jsonify({
            'success': True,
            'new_item_id': new_item.id,
            'total_items': total_items
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/auto-save-bid', methods=['POST'])
def auto_save_bid():
    try:
        app.logger.info("Received auto-save bid request")
        bid_data = request.json
        if not bid_data:
            raise BadRequest("No JSON data received")

        app.logger.info(f"Received bid data: {bid_data}")

        bid_id = bid_data.get('bid_id')
        if not bid_id:
            raise BadRequest("Bid ID is required")

        app.logger.info(f"Processing auto-save for bid with ID: {bid_id}")

        # Fetch existing bid or create new one
        bid = Bid.query.filter_by(bid_id=bid_id).first()
        if not bid:
            app.logger.info(f"Creating new bid with ID: {bid_id}")
            bid = Bid(bid_id=bid_id, bid_date=datetime.now().date())
            db.session.add(bid)
        else:
            app.logger.info(f"Updating existing bid with ID: {bid_id}")

        # Update heading info
        heading_info = bid_data.get('heading_info', {})
        
        # Handle customer information
        customer_name = heading_info.get('customer_name')
        if customer_name:
            customer = Customer.query.get(customer_name)
            if not customer:
                customer = Customer(customer_name=customer_name)
                db.session.add(customer)
            
            customer.customer_address = heading_info.get('customer_address', customer.customer_address)
            customer.customer_state = heading_info.get('customer_state', customer.customer_state)
            customer.customer_city = heading_info.get('customer_city', customer.customer_city)
            customer.customer_zip = heading_info.get('customer_zip', customer.customer_zip)
            
            bid.customer_name = customer_name

        # Update other bid fields
        bid.project_name = heading_info.get('project_name', bid.project_name)
        bid.project_address = heading_info.get('project_address', bid.project_address)
        bid.project_state = heading_info.get('project_state', bid.project_state)
        bid.project_city = heading_info.get('project_city', bid.project_city)
        bid.project_zip = heading_info.get('project_zip', bid.project_zip)

        # Update labor rates and sales tax
        labor_rates = bid_data.get('labor_rates', {})
        bid.drains_labor_rate = labor_rates.get('drains_labor_rate', bid.drains_labor_rate)
        bid.irrigation_labor_rate = labor_rates.get('irrigation_labor_rate', bid.irrigation_labor_rate)
        bid.landscape_labor_rate = labor_rates.get('landscape_labor_rate', bid.landscape_labor_rate)
        bid.maintenance_labor_rate = labor_rates.get('maintenance_labor_rate', bid.maintenance_labor_rate)
        bid.local_sales_tax = labor_rates.get('local_sales_tax', bid.local_sales_tax)

        # Save line items
        items_data = bid_data.get('items', {})
        for category, items in items_data.items():
            # Remove existing items for this category
            BidFactorCodeItems.query.filter_by(bid_id=bid_id, category=category).delete()
            
            for item in items:
                new_item = BidFactorCodeItems(
                    bid_id=bid_id,
                    category=category,
                    factor_code=item.get('factor_code', ''),
                    part_number=item.get('part_number', ''),
                    description=item.get('description', ''),
                    quantity=item.get('quantity', 0),
                    cost=item.get('cost', 0),
                    labor_hours=item.get('labor_hours', 0),
                    line_ext_cost=item.get('line_ext_cost', 0),
                    additional_description=item.get('additional_description', '')
                )
                db.session.add(new_item)

        db.session.commit()
        app.logger.info(f"Auto-save successful for bid ID: {bid_id}")
        return jsonify({"success": True, "message": "Bid auto-saved successfully"}), 200

    except BadRequest as e:
        db.session.rollback()
        app.logger.error(f"Bad request error during auto-save: {str(e)}")
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Unexpected error during auto-save: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"error": "An unexpected error occurred during auto-save", "details": str(e)}), 500
    
@app.route('/bid-job-estimating/<bid_id>', methods=['GET', 'POST'])
def bid_job_estimating(bid_id):
    bid = Bid.query.get_or_404(bid_id)
    
    if request.method == 'POST':
        # Update bid data
        bid.project_name = request.form['projectName']
        bid.description = request.form['description']
        bid.customer_name = request.form['customerName']
        bid.customer_address = request.form['customerAddress']
        bid.customer_state = request.form['customerState']
        bid.customer_city = request.form['customerCity']
        bid.customer_zip = request.form['customerZip']
        bid.drains_labor_rate = request.form['laborRateDrains']
        bid.irrigation_labor_rate = request.form['laborRateIrrigation']
        bid.landscape_labor_rate = request.form['laborRateLandscape']
        bid.maintenance_labor_rate = request.form['laborRateMaintenance']
        bid.local_sales_tax = request.form['localSalesTax']
        db.session.commit()
        return redirect(url_for('bid_management'))
    
    return render_template('Bid_Job_Estimating.html', bid=bid)
    
# Add this to handle unauthorized access
@login_manager.unauthorized_handler
def unauthorized():
    flash('You must be logged in to access this page.', 'error')
    return redirect(url_for('login', next=request.url))

# Modify your create_default_admin function
def create_default_admin():
    with current_app.app_context():
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin')
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()
            print("Default admin user created.")

@app.route('/insert', methods=['POST'])
def insert_item():
    insert_after = request.form['InsertAfter']
    part_num = request.form['PartNum']
    quantity = int(request.form['Quantity'])
    item = next((item for item in inventory if item['PartNum'] == part_num), None)
    if item:
        index = next((i for i, item in enumerate(session['bid_items']) if item['PartNum'] == insert_after), None)
        if index is not None:
            session['bid_items'].insert(index + 1, {**item, "Quantity": quantity, "Cost": float(item['Cost'])})
            session.modified = True  # Mark the session as modified to save changes
            total_cost = sum(item['Cost'] * item['Quantity'] for item in session['bid_items'])
            return jsonify(success=True, bid_items=session['bid_items'], total_cost=total_cost)
    return jsonify(success=False)

with app.app_context():
    db.create_all()

scheduler = BackgroundScheduler()
scheduler.add_job(func=update_factor_codes_cache, trigger="interval", minutes=60)
scheduler.start()

# Modify your main block to include the schema update
if __name__ == '__main__':
    with app.app_context():
        update_database_schema()
        db.create_all()
        create_default_admin()
    check_and_update_cache()
    run_simple('localhost', 5000, app, use_reloader=False, use_debugger=True)
    db = SQLAlchemy(app)