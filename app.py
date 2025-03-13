import base64
from flask import Flask, request, jsonify, render_template, session, send_file, current_app, redirect, url_for, flash, abort
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta, timezone
from io import BytesIO
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
from dotenv import load_dotenv
from fuzzywuzzy import process, fuzz
from sqlalchemy import or_, case, desc, select, union, func, literal, cast, String
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
from functools import wraps
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from itsdangerous import URLSafeTimedSerializer
import secrets
import random
import string
# Add these imports at the top of your main.py
from flask_mail import Mail, Message
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO
from datetime import datetime
from reportlab.lib.units import inch  # Make sure to import inch

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

# Add these configurations after creating your Flask app
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
# In your main.py, replace the hardcoded credentials with:
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')  # You should change this password after testing
app.config['MAIL_DEFAULT_SENDER'] = 'BuccolaReset@gmail.com'

# Initialize Flask-Mail
mail = Mail(app)

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

# Fix the Job model relationship
class Job(db.Model):
    __tablename__ = 'jobs'
    job_id = db.Column(db.String(5), primary_key=True)
    bid_id = db.Column(db.String, db.ForeignKey('bid.bid_id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='active')
    
    bid = db.relationship('Bid', backref=db.backref('job', uselist=False))
    # Changed this line to remove conflicting backref
    purchase_orders = db.relationship('PurchaseOrder', back_populates='job', lazy=True)

# Update the PurchaseOrder model
class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'
    po_number = db.Column(db.String(20), primary_key=True)
    job_id = db.Column(db.String(5), db.ForeignKey('jobs.job_id'))
    category = db.Column(db.String(20), nullable=False)
    vendor = db.Column(db.String(255))
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    date_needed = db.Column(db.DateTime)
    amount = db.Column(db.Float, default=0.0)
    items_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='in_progress')  # new, in_progress, completed
    finalized_at = db.Column(db.DateTime)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ship_to_job = db.Column(db.Boolean, default=True)

    # Define relationships
    job = db.relationship('Job', back_populates='purchase_orders')
    items = db.relationship('PurchaseOrderItem', 
                          back_populates='purchase_order',
                          lazy=True,
                          cascade='all, delete-orphan')
    # Update the comments relationship to match the Comment model
    comments = db.relationship('Comment', 
                             back_populates='purchase_order',
                             lazy=True,
                             cascade='all, delete-orphan')

    @classmethod
    def get_in_progress_po(cls, job_id, category):
        """Get the in-progress PO for a specific job and category"""
        return cls.query.filter_by(
            job_id=job_id,
            category=category,
            status='in_progress'
        ).first()



    @classmethod
    def has_in_progress_po(cls, job_id, category):
        """Check if there's an in-progress PO for the given job and category"""
        return cls.query.filter_by(
            job_id=job_id,
            category=category,
            status='in_progress'
        ).count() > 0

class PurchaseOrderItem(db.Model):
    __tablename__ = 'purchase_order_items'
    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(20), db.ForeignKey('purchase_orders.po_number'))
    part_number = db.Column(db.String(255))
    description = db.Column(db.Text)
    quantity = db.Column(db.Integer, default=1)
    unit_cost = db.Column(db.Float, default=0.0)
    total_cost = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))  # Add this line

    # Define relationships
    purchase_order = db.relationship('PurchaseOrder', back_populates='items')
    vendor = db.relationship('Vendor', foreign_keys=[vendor_id])

# Update the Comment model first
class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(20), db.ForeignKey('purchase_orders.po_number'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Define relationship to User
    user = db.relationship('User', backref=db.backref('comments', lazy=True))
    
    # Define relationship to PurchaseOrder without backref
    purchase_order = db.relationship('PurchaseOrder', back_populates='comments')

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)  # Added email field
    password_hash = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reset_token = db.Column(db.String(100), unique=True)
    reset_token_expiration = db.Column(db.DateTime)
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Proposal(db.Model):
    __tablename__ = 'proposals'
    id = db.Column(db.Integer, primary_key=True)
    bid_id = db.Column(db.String, db.ForeignKey('bid.bid_id'), nullable=False)
    customer_name = db.Column(db.String(255))
    project_name = db.Column(db.String(255))
    total_budget = db.Column(db.Float)

    # Include your new heading fields
    point_of_contact = db.Column(db.String(255))
    architect_name = db.Column(db.String(255))
    architect_specifications = db.Column(db.String(255))
    architect_dated = db.Column(db.String(255))
    architect_sheets = db.Column(db.String(255))
    engineer_name = db.Column(db.String(255))
    engineer_specifications = db.Column(db.String(255))
    engineer_dated = db.Column(db.String(255))
    engineer_sheets = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    special_notes = db.Column(db.Text)
    terms_conditions = db.Column(db.Text)
    revision_number = db.Column(db.Integer, default=1)
    exclusions = db.Column(db.Text)  # Added this line

    # Relationships
    bid = db.relationship('Bid', backref=db.backref('proposal', uselist=False))
    proposal_amounts = db.relationship('ProposalAmount', back_populates='proposal', cascade="all, delete-orphan")
    options = db.relationship('ProposalOption', back_populates='proposal', cascade="all, delete-orphan")
    components = db.relationship('ProposalComponent', back_populates='proposal', cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'bid_id': self.bid_id,
            'customer_name': self.customer_name,
            'project_name': self.project_name,
            'total_budget': float(self.total_budget) if self.total_budget else None,
            'special_notes': self.special_notes,
            'terms_conditions': self.terms_conditions,
            'revision_number': self.revision_number,
            'exclusions': self.exclusions,  # Added this line
            'proposal_amounts': [amount.to_dict() for amount in self.proposal_amounts],
            'options': [option.to_dict() for option in self.options],
            'components': [component.to_dict() for component in self.components]
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

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

class Vendor(db.Model):
    __tablename__ = 'vendors'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    
    # Address fields
    address1 = db.Column(db.String(255), nullable=True)
    address2 = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(2), nullable=True)
    zip_code = db.Column(db.String(10), nullable=True)
    
    # Contact information
    phone_number = db.Column(db.String(50), nullable=True)
    fax_number = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    contact_person = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<Vendor {self.company}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'company': self.company,
            'address1': self.address1,
            'address2': self.address2,
            'city': self.city,
            'state': self.state,
            'zip_code': self.zip_code,
            'phone_number': self.phone_number,
            'fax_number': self.fax_number,
            'email': self.email,
            'contact_person': self.contact_person
        }

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
    bid_amount = db.Column(db.Float, default=0.0)
    comments = db.Column(db.Text)  # New field for bid comments

    customer = db.relationship('Customer', back_populates='bids')
    project = db.relationship('Project', back_populates='bids')
    inventory = db.relationship('Inventory', back_populates='bids')
    sub_bids = db.relationship('SubBid', back_populates='bid', cascade="all, delete-orphan")
    factor_code_items = db.relationship('BidFactorCodeItems', back_populates='bid', 
                                        cascade="all, delete-orphan")
    urgency = db.Column(db.String(10), nullable=True)
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
    __tablename__ = 'sub_bid'
    sub_bid_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    cost = db.Column(db.Float)
    labor_hours = db.Column(db.Float)
    bid_id = db.Column(db.String, db.ForeignKey('bid.bid_id', ondelete='CASCADE'), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='unknown')
    total_cost = db.Column(db.Float, default=0.0)

    bid = db.relationship('Bid', back_populates='sub_bids')
    items = db.relationship('SubBidItem', 
                            back_populates='sub_bid', 
                            cascade='all, delete-orphan', 
                            passive_deletes=True)

class SubBidItem(db.Model):
    __tablename__ = 'sub_bid_items'
    id = db.Column(db.Integer, primary_key=True)
    sub_bid_id = db.Column(db.Integer, db.ForeignKey('sub_bid.sub_bid_id', ondelete='CASCADE'), nullable=False)
    part_number = db.Column(db.String(50))
    description = db.Column(db.String(255))
    additional_description = db.Column(db.String(255), nullable=True)
    factor_code = db.Column(db.String(50))
    quantity = db.Column(db.Float)
    cost = db.Column(db.Float)
    labor_hours = db.Column(db.Float)
    line_ext_cost = db.Column(db.Float)
    
    sub_bid = db.relationship('SubBid', 
                               back_populates='items', 
                               passive_deletes=True)
    

class BidAdjustment(db.Model):
    __tablename__ = 'bid_adjustments'
    id = db.Column(db.Integer, primary_key=True)
    bid_id = db.Column(db.String, db.ForeignKey('bid.bid_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    section = db.Column(db.String(50), nullable=False)  # Drains, Irrigation, etc.
    type = db.Column(db.String(50), nullable=False)     # Materials or Labor
    direction = db.Column(db.String(20), nullable=False) # increase or decrease
    percentage = db.Column(db.Float, nullable=False)
    original_values = db.Column(db.Text)  # JSON string of original values for undo
    is_active = db.Column(db.Boolean, default=True)  # To mark if undone
    
    bid = db.relationship('Bid', backref=db.backref('adjustments', lazy=True))
    user = db.relationship('User', backref=db.backref('adjustments', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'bid_id': self.bid_id,
            'user': {
                'id': self.user_id,
                'username': self.user.username if self.user else "Unknown User"
            },
            'timestamp': self.timestamp.isoformat(),
            'section': self.section,
            'type': self.type,
            'direction': self.direction,
            'percentage': self.percentage,
            'is_active': self.is_active
        }


class Tax(db.Model):
    __tablename__ = 'tax'
    zip_code = db.Column(db.String(10), primary_key=True)
    tax_rate = db.Column(db.Float, nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Tax zip_code={self.zip_code} tax_rate={self.tax_rate}>"

# Add this to your models section
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(50))  # e.g., 'login', 'create_bid', 'update_proposal'
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    
    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))

class RequestResetForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters long')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Reset Password')

def generate_purchase_order_pdf(po_data, show_costs=True):
    from reportlab.lib.colors import HexColor

    buffer = BytesIO()

    def wrap_text(text, width, font_name='Helvetica', font_size=9):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        words = text.split()
        lines = []
        current_line = []
        current_width = 0

        for word in words:
            word_width = stringWidth(word + ' ', font_name, font_size)
            if current_width + word_width <= width:
                current_line.append(word)
                current_width += word_width
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_width = word_width

        if current_line:
            lines.append(' '.join(current_line))
        return '\n'.join(lines)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=24,
        bottomMargin=36
    )

    elements = []
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='DescriptionText',
        fontSize=9,
        leading=11,
        alignment=0,
        fontName='Helvetica'
    ))

    # Additional description style (we'll embed this inline instead of separate paragraph)
    # We'll use inline styling directly (HTML-like) when building the combined paragraph text.

    styles.add(ParagraphStyle(
        name='CompanyInfo',
        fontSize=16,
        spaceAfter=6,
        leading=18,
        fontName='Helvetica-Bold'
    ))

    styles.add(ParagraphStyle(
        name='POInfo',
        fontSize=12,
        alignment=2,
        leading=14,
        fontName='Helvetica-Bold'
    ))

    styles.add(ParagraphStyle(
        name='NormalLeft',
        fontSize=10,
        leading=12,
        alignment=0,
    ))

    styles.add(ParagraphStyle(
        name='NormalRight',
        fontSize=10,
        leading=12,
        alignment=2,
    ))

    date_created = datetime.now().strftime("%m/%d/%Y")
    date_needed = po_data.get('date_needed')
    if isinstance(date_needed, str):
        try:
            date_needed = datetime.strptime(date_needed, '%Y-%m-%d').strftime("%m/%d/%Y")
        except ValueError:
            date_needed = None

    header_data = [
        [
            Paragraph("Buccola Landscape Services, Inc.", styles['CompanyInfo']),
            Paragraph("Purchase Order", styles['POInfo'])
        ],
        [
            Paragraph("2885 La Cresta Ave.", styles['NormalLeft']),
            Paragraph(f'PO #: {po_data["po_number"]}', styles['POInfo'])
        ],
        [
            Paragraph("Anaheim, CA 92806", styles['NormalLeft']),
            Paragraph(f'Date Created: {date_created}', styles['POInfo'])
        ],
        [
            Paragraph("(714)-630-4868", styles['NormalLeft']),
            Paragraph(f'Date Needed: {date_needed if date_needed else "N/A"}', styles['POInfo'])
        ]
    ]

    header_table = Table(header_data, colWidths=[doc.width * 0.7, doc.width * 0.3])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 20))

    vendor = po_data.get('vendor', {})
    project = po_data.get('project', {})

    if po_data.get('ship_to_job', True):
        ship_to_data = [
            Paragraph("<b>Ship To:</b>", styles['NormalLeft']),
            Paragraph(project.get('name', ''), styles['NormalLeft']),
            Paragraph(project.get('address', ''), styles['NormalLeft']),
            Paragraph(f"{project.get('city', '')}, {project.get('state', '')} {project.get('zip_code', '')}", styles['NormalLeft']),
            Paragraph(f"Contact: {project.get('point_of_contact', 'NONE')}", styles['NormalLeft'])
        ]
    else:
        ship_to_data = [
            Paragraph("<b>Ship To:</b>", styles['NormalLeft']),
            Paragraph("2885 La Cresta Ave.", styles['NormalLeft']),
            Paragraph("Anaheim, CA 92806", styles['NormalLeft']),
            Paragraph("(714)-630-4868", styles['NormalLeft']),
        ]

    bill_to_data = [
        Paragraph("<b>Vendor:</b>", styles['NormalLeft']),
        Paragraph(vendor.get('company', ''), styles['NormalLeft']),
        Paragraph(vendor.get('address1', ''), styles['NormalLeft']),
        Paragraph(f"{vendor.get('city', '')}, {vendor.get('state', '')} {vendor.get('zip_code', '')}", styles['NormalLeft'])
    ]

    address_data = [
        [bill_to_data[0], ship_to_data[0]],
        [bill_to_data[1], ship_to_data[1]],
        [bill_to_data[2], ship_to_data[2]],
        [bill_to_data[3], ship_to_data[3]]
    ]

    # If there's a contact row in ship_to_data
    if len(ship_to_data) > 4:
        address_data.append(['', ship_to_data[4]])

    address_table = Table(address_data, colWidths=[doc.width * 0.5, doc.width * 0.5])
    address_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(address_table)
    elements.append(Spacer(1, 20))

    # Set column widths for items
    if show_costs:
        col_widths = [
            doc.width * 0.2,  # Part Number
            doc.width * 0.4,  # Description
            doc.width * 0.1,  # Qty
            doc.width * 0.15, # Cost
            doc.width * 0.15  # Total
        ]
        items_data = [['Part Number', 'Description', 'Qty', 'Cost', 'Total']]
    else:
        col_widths = [
            doc.width * 0.3,  # Part Number
            doc.width * 0.5,  # Description
            doc.width * 0.2   # Qty
        ]
        items_data = [['Part Number', 'Description', 'Qty']]

    description_width = (doc.width * 0.4) - 12

    for item in po_data['items']:
        main_desc_text = wrap_text(item['description'], description_width)
        # Combine main and additional desc into single paragraph
        if item.get('additional_description'):
            # Insert a line break and then smaller, italicized text
            combined_description = f"{main_desc_text}<br/><font size='8' color='#555555'><i>{item['additional_description']}</i></font>"
        else:
            combined_description = main_desc_text

        desc_par = Paragraph(combined_description, styles['DescriptionText'])

        if show_costs:
            items_data.append([
                item['part_number'],
                desc_par,
                str(item['quantity']),
                f"${item['cost']:.2f}",
                f"${item['quantity'] * item['cost']:.2f}"
            ])
        else:
            items_data.append([
                item['part_number'],
                desc_par,
                str(item['quantity'])
            ])

    items_table = Table(items_data, colWidths=col_widths, hAlign='LEFT')

    row_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('GRID', (0, 0), (-1, 0), 0.5, colors.black)
    ]

    if show_costs:
        row_styles.append(('ALIGN', (2, 1), (4, -1), 'RIGHT'))  # Align Qty, Cost, Total
    else:
        row_styles.append(('ALIGN', (2, 1), (2, -1), 'RIGHT'))  # Align Qty

    # Apply style
    items_table.setStyle(TableStyle(row_styles))
    elements.append(items_table)

    if show_costs:
        material_total = sum(item['quantity'] * item['cost'] for item in po_data['items'])
        sales_tax = material_total * (po_data.get('tax_rate', 0) / 100)
        po_total = material_total + sales_tax

        elements.append(Spacer(1, 20))

        totals_data = [
            ['Material Total:', f"${material_total:.2f}"],
            ['Sales Tax:', f"${sales_tax:.2f}"],
            ['PO Total:', f"${po_total:.2f}"]
        ]

        totals_table = Table(totals_data, colWidths=[doc.width * 0.8, doc.width * 0.2], hAlign='RIGHT')
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(totals_table)
        elements.append(Spacer(1, 20))

    # Comments Section
    if 'comments' in po_data and po_data['comments']:
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("Comments:", ParagraphStyle(
            'CommentsHeader',
            parent=styles['Heading2'],
            fontSize=12,
            leading=14,
            spaceBefore=12,
            spaceAfter=6,
            fontName='Helvetica-Bold'
        )))

        for comment in po_data['comments']:
            # Just print comment text
            comment_paragraph = Paragraph(comment['text'], ParagraphStyle(
                'CommentStyle',
                parent=styles['Normal'],
                fontSize=10,
                leading=12,
                spaceBefore=4,
                spaceAfter=4,
                fontName='Helvetica'
            ))
            elements.append(comment_paragraph)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login', next=request.url))
        if not current_user.is_admin:
            flash('You do not have permission to access this page.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login', next=request.url))
        if not current_user.is_super_admin:
            flash('Only super administrators can access this page.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def staff_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/api/adjustments/<bid_id>', methods=['GET'])
@login_required
def get_adjustments(bid_id):
    """Get adjustment history for a bid"""
    try:
        # Add a check if the BidAdjustment class is defined
        if 'BidAdjustment' not in globals():
            return jsonify([]), 200  # Return empty array if model doesn't exist yet
            
        adjustments = BidAdjustment.query.filter_by(bid_id=bid_id).order_by(BidAdjustment.timestamp.desc()).all()
        return jsonify([adj.to_dict() for adj in adjustments])
    except Exception as e:
        app.logger.error(f"Error fetching adjustments: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/adjustments', methods=['POST'])
@login_required
def create_adjustment():
    """Create a new adjustment record"""
    try:
        data = request.json
        
        # Validate input
        required_fields = ['bid_id', 'section', 'type', 'direction', 'percentage', 'original_values']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        adjustment = BidAdjustment(
            bid_id=data['bid_id'],
            user_id=current_user.id,
            section=data['section'],
            type=data['type'],
            direction=data['direction'],
            percentage=data['percentage'],
            original_values=json.dumps(data['original_values'])
        )
        
        db.session.add(adjustment)
        db.session.commit()
        
        return jsonify(adjustment.to_dict()), 201
    except Exception as e:
        app.logger.error(f"Error creating adjustment: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/adjustments/<int:adjustment_id>/undo', methods=['POST'])
@login_required
def undo_adjustment(adjustment_id):
    """Undo an adjustment by ID"""
    try:
        adjustment = BidAdjustment.query.get_or_404(adjustment_id)
        
        # Only the user who made the adjustment or an admin can undo it
        if adjustment.user_id != current_user.id and not current_user.is_admin:
            return jsonify({"error": "Unauthorized to undo this adjustment"}), 403
        
        # Mark adjustment as inactive/undone
        adjustment.is_active = False
        db.session.commit()
        
        # Return the original values for client-side reversion
        return jsonify({
            'success': True,
            'adjustment_id': adjustment.id,
            'original_values': json.loads(adjustment.original_values)
        })
    except Exception as e:
        app.logger.error(f"Error undoing adjustment: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/api/purchase-orders/<po_number>/generate-pdf', methods=['GET'])
@staff_required
def generate_po_pdf(po_number):
    try:
        show_costs = request.args.get('show_costs', 'true').lower() == 'true'
        po = PurchaseOrder.query.get_or_404(po_number)
        
        if po.status != 'completed':
            return jsonify({
                'success': False,
                'message': 'Purchase order must be completed to generate PDF'
            }), 400

        # Get items with non-zero quantities
        active_items = PurchaseOrderItem.query.filter(
            PurchaseOrderItem.po_number == po_number,
            PurchaseOrderItem.quantity > 0
        ).all()

        # Get vendor info from first item
        vendor = None
        if active_items:
            vendor = Vendor.query.get(active_items[0].vendor_id) if active_items[0].vendor_id else None

        # Get project info and associated bid info
        job = Job.query.get(po.job_id)
        project = None
        bid = None
        if job:
            bid = job.bid
            if bid:
                project = Project.query.filter_by(project_name=bid.project_name).first()

        # Get any comments associated with this PO
        comments = Comment.query.filter_by(po_number=po_number).order_by(Comment.created_at.desc()).all()
        formatted_comments = [{
            'user': comment.user.username,
            'text': comment.text,
            'created_at': comment.created_at.strftime("%m/%d/%Y %I:%M %p")
        } for comment in comments]

        # Get additional descriptions from bid items if they exist
        bid_items_dict = {}
        if bid:
            bid_items = BidFactorCodeItems.query.filter_by(
                bid_id=bid.bid_id,
                category=po.category
            ).all()
            bid_items_dict = {
                item.part_number: item.additional_description
                for item in bid_items
                if item.additional_description
            }

        # Prepare data for PDF generation
        po_data = {
            'po_number': po_number,
            'date_needed': po.date_needed.strftime('%Y-%m-%d') if po.date_needed else None,
            'vendor': vendor.to_dict() if vendor else {},
            'project': {
                'name': project.project_name if project else '',
                'address': project.project_address if project else '',
                'city': project.project_city if project else '',
                'state': project.project_state if project else '',
                'zip_code': project.project_zip if project else '',
                'point_of_contact': project.point_of_contact if project else None
            },
            'items': [{
                'part_number': item.part_number,
                'description': item.description,
                'quantity': float(item.quantity),
                'cost': float(item.unit_cost),
                'additional_description': bid_items_dict.get(item.part_number, '')
            } for item in active_items],
            'tax_rate': float(bid.local_sales_tax) if bid else 0.0,
            'comments': formatted_comments,
            'ship_to_job': po.ship_to_job
        }

        # Generate PDF using the function
        buffer = generate_purchase_order_pdf(po_data, show_costs)

        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'PO-{po_number}{"-complete" if show_costs else "-no-cost"}.pdf'
        )

    except Exception as e:
        app.logger.error(f"Error generating PDF for PO {po_number}: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/field-order/<job_id>/<category>', methods=['POST'])
@staff_required
def generate_field_order(job_id, category):
    try:
        job = Job.query.get_or_404(job_id)
        bid = db.session.get(Bid, job.bid_id)
        
        if not bid:
            raise ValueError(f"Bid not found for job {job_id}")
            
        items = []
        bid_items = BidFactorCodeItems.query.filter_by(
            bid_id=bid.bid_id,
            category=category
        ).all()
        
        # Calculate bought quantities
        for item in bid_items:
            bought_qty = 0
            completed_pos = PurchaseOrder.query.filter_by(
                job_id=job_id, 
                category=category,
                status='completed'
            ).all()
            
            for po in completed_pos:
                po_items = PurchaseOrderItem.query.filter_by(
                    po_number=po.po_number,
                    part_number=item.part_number
                ).all()
                bought_qty += sum(poi.quantity for poi in po_items)
            
            # Remove the max(0, ...) so we keep zero or negative
            remaining_qty = item.quantity - bought_qty
            
            # Remove the condition so all items are included
            items.append({
                'part_number': item.part_number,
                'description': item.description,
                'remaining_qty': remaining_qty
            })

        # The rest of the code remains the same
        # Split items into two columns
        total_items = len(items)
        mid_point = (total_items + 1) // 2
        left_items = items[:mid_point]
        right_items = items[mid_point:]

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=6,
            leftMargin=6,
            topMargin=12,
            bottomMargin=12
        )
        
        styles = getSampleStyleSheet()
        table_width = (doc.width - 5) / 2
        
        styles.add(ParagraphStyle(
            'HeaderStyle',
            fontSize=10,
            fontName='Helvetica-Bold',
            alignment=1,
            leading=12
        ))
        
        styles.add(ParagraphStyle(
            'TitleStyle',
            fontSize=14,
            fontName='Helvetica-Bold',
            alignment=1,
            leading=16
        ))
        
        styles.add(ParagraphStyle(
            'DateStyle',
            fontSize=10,
            fontName='Helvetica',
            alignment=1
        ))

        elements = []
        
        left_content = Table(
            [
                [Paragraph(f"{category.title()}", styles['HeaderStyle'])],
                [Paragraph(f"{bid.project_name}", styles['HeaderStyle'])]
            ],
            style=TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ])
        )
        
        center_title = Table(
            [[Paragraph("Field Order Form", styles['TitleStyle'])]],
            style=TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ])
        )
        
        right_content = Paragraph(
            f"{datetime.now().strftime('%A, %B %d, %Y')}", 
            styles['DateStyle']
        )
        
        header_table = Table(
            [[left_content, center_title, right_content]], 
            colWidths=[doc.width/3 - 4, doc.width/3 + 8, doc.width/3 - 4],
            style=TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ])
        )
        
        elements.append(header_table)
        elements.append(Spacer(1, 8))
        
        def create_column_table(items_list, total_rows):
            data = [['Part #', 'Description', 'Rem', 'Ord']]
            
            for item in items_list:
                data.append([
                    item['part_number'],
                    item['description'][:35],
                    str(item['remaining_qty']),
                    ''
                ])
            
            while len(data) < total_rows + 1:
                data.append(['', '', '', ''])
                
            return Table(
                data,
                colWidths=[57, 152, 32, 32],
                style=TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 7),
                    ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 1),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ])
            )

        max_rows = max(len(left_items), len(right_items))
        left_table = create_column_table(left_items, max_rows)
        right_table = create_column_table(right_items, max_rows)
        
        two_col_table = Table(
            [[left_table, None, right_table]], 
            colWidths=[table_width, 5, table_width],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 1),
                ('RIGHTPADDING', (0, 0), (-1, -1), 1),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ])
        )
        
        elements.append(two_col_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'field-order-{job_id}-{category}.pdf'
        )
        
    except Exception as e:
        app.logger.error(f"Error generating field order: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500



@app.route('/add-update-project', methods=['POST'])
@staff_required
def add_update_project():
    try:
        data = request.form
        project_name = data.get('project_name')
        
        project = Project.query.get(project_name)
        action = 'update_project' if project else 'create_project'
        
        if project:
            # Store old values for audit
            old_data = {
                'address': project.project_address,
                'state': project.project_state,
                'city': project.project_city,
                'zip': project.project_zip,
                'point_of_contact': project.point_of_contact,
                'contact_phone_number': project.contact_phone_number
            }
            
            # Update project
            project.project_address = data.get('project_address')
            project.project_state = data.get('project_state')
            project.project_city = data.get('project_city')
            project.project_zip = data.get('project_zip')
            project.point_of_contact = data.get('point_of_contact')
            project.contact_phone_number = data.get('contact_phone_number')
            
            # Log changes
            changes = []
            for field, old_value in old_data.items():
                new_value = getattr(project, f'project_{field}' if field not in ['point_of_contact', 'contact_phone_number'] else field)
                if old_value != new_value:
                    changes.append(f"{field}: '{old_value}' → '{new_value}'")
            
            if changes:
                log_audit('update_project', 
                         f"Updated project '{project_name}'. Changes: {', '.join(changes)}")
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
            
            # Log creation
            log_audit('create_project', 
                     f"Created new project '{project_name}' with POC: {data.get('point_of_contact')}, "
                     f"Address: {data.get('project_address')}, {data.get('project_city')}, {data.get('project_state')}")
            message = "New project created successfully."

        db.session.commit()
        return jsonify({"success": True, "message": message})
    except Exception as e:
        db.session.rollback()
        log_audit(f"{action}_error", f"Error processing project {project_name}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/add-sub-bid-to-main', methods=['POST'])
@csrf.exempt  # Exempt CSRF protection if necessary
@staff_required
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
@staff_required
def save_proposal():
    try:
        data = request.json
        
        # Log raw incoming data
        app.logger.info('[SAVE_PROPOSAL] Received request to save proposal.')
        app.logger.debug(f'[SAVE_PROPOSAL] Full payload: {data}')
        
        proposal_id = data.get('bid_id')  # Your frontend calls it "bid_id"
        version_number = data.get('revision_number')
        
        app.logger.debug(f'[SAVE_PROPOSAL] Looking for proposal with bid_id={proposal_id}, revision={version_number}')

        # Get or create proposal
        proposal = Proposal.query.filter_by(bid_id=proposal_id, revision_number=version_number).first()
        is_new = proposal is None
        
        if is_new:
            app.logger.info(f'[SAVE_PROPOSAL] Creating NEW proposal because none found.')
            proposal = Proposal(bid_id=proposal_id, revision_number=version_number)
            db.session.add(proposal)
            db.session.flush()  # Ensures proposal.id is assigned
        else:
            app.logger.info(f'[SAVE_PROPOSAL] Updating EXISTING proposal ID={proposal.id}, revision={proposal.revision_number}')

        # Clear existing components/lines
        app.logger.debug(f'[SAVE_PROPOSAL] Deleting old components/lines for proposal {proposal.id}')
        ProposalComponentLine.query.filter(
            ProposalComponentLine.component_id.in_(
                ProposalComponent.query
                    .filter_by(proposal_id=proposal.id)
                    .with_entities(ProposalComponent.id)
            )
        ).delete(synchronize_session=False)
        ProposalComponent.query.filter_by(proposal_id=proposal.id).delete(synchronize_session=False)
        
        # Add new components and lines
        components = data.get('components', [])
        app.logger.debug(f'[SAVE_PROPOSAL] Rebuilding {len(components)} components.')
        
        for comp_data in components:
            component = ProposalComponent(
                proposal_id=proposal.id,
                type=comp_data.get('type', 'section'),  
                name=comp_data.get('name', 'Unnamed Component')
            )
            db.session.add(component)
            db.session.flush()  # So the component.id is ready for lines
            app.logger.debug(f'[SAVE_PROPOSAL] -> Created component ID={component.id}, name={component.name}')
            
            # Add lines for this component
            for line_data in comp_data.get('lines', []):
                line = ProposalComponentLine(
                    component_id=component.id,
                    name=line_data.get('name', 'Unnamed Line'),
                    value=float(line_data.get('value', 0))
                )
                db.session.add(line)
        
        # Handle options
        app.logger.debug('[SAVE_PROPOSAL] Clearing old proposal options.')
        ProposalOption.query.filter_by(proposal_id=proposal.id).delete()
        for option_data in data.get('options', []):
            new_option = ProposalOption(
                proposal_id=proposal.id,
                description=option_data.get('description', ''),
                amount=float(option_data.get('amount', 0))
            )
            db.session.add(new_option)
        
        # Update basic proposal fields
        proposal.customer_name = data.get('customer_name')
        proposal.project_name = data.get('job_name')
        proposal.total_budget = float(data.get('total_budget', 0))
        
        # Update your heading fields here:
        proposal.point_of_contact = data.get('point_of_contact')
        proposal.architect_name = data.get('architect_name')
        proposal.architect_specifications = data.get('architect_specifications')
        proposal.architect_dated = data.get('architect_dated')
        proposal.architect_sheets = data.get('architect_sheets')
        proposal.engineer_name = data.get('engineer_name')
        proposal.engineer_specifications = data.get('engineer_specifications')
        proposal.engineer_dated = data.get('engineer_dated')
        proposal.engineer_sheets = data.get('engineer_sheets')      


        # For arrays, we store them as JSON strings:
        raw_special_notes = data.get('special_notes', [])
        raw_terms_conditions = data.get('terms_conditions', [])
        proposal.special_notes = json.dumps(raw_special_notes)
        proposal.terms_conditions = json.dumps(raw_terms_conditions)
        
        # Exclusions (string)
        if 'exclusions' in data:
            proposal.exclusions = data.get('exclusions')
        
        app.logger.debug(f'[SAVE_PROPOSAL] Final proposal fields -> '
                         f'customer_name={proposal.customer_name}, '
                         f'project_name={proposal.project_name}, '
                         f'total_budget={proposal.total_budget}, '
                         f'exclusions={proposal.exclusions}, '
                         f'special_notes={proposal.special_notes}, '
                         f'terms_conditions={proposal.terms_conditions}')
        
        db.session.commit()
        app.logger.info(f'[SAVE_PROPOSAL] Proposal saved successfully! (proposal_id={proposal_id}, revision={version_number}, is_new={is_new})')
        
        return jsonify({
            'success': True,
            'message': 'Proposal saved successfully',
            'proposal_id': proposal_id
        }), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[SAVE_PROPOSAL] ERROR: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


def handle_proposal_components(proposal, data, is_new):
    """Helper function to handle proposal components with audit logging"""
    try:
        # Store old components for comparison if updating
        old_components = {comp.id: comp for comp in proposal.components} if not is_new else {}
        
        # Clear existing components
        if not is_new:
            # Log removal of old components
            for comp in proposal.components:
                log_audit('remove_proposal_component',
                         f"Removed component {comp.name} from proposal {proposal.bid_id}")

        ProposalComponentLine.query.filter(
            ProposalComponentLine.component_id.in_(
                ProposalComponent.query.with_entities(ProposalComponent.id)
                .filter_by(proposal_id=proposal.id)
            )
        ).delete(synchronize_session=False)
        ProposalComponent.query.filter_by(proposal_id=proposal.id).delete(synchronize_session=False)

        # Add new components
        for component_data in data.get('components', []):
            new_component = ProposalComponent(
                proposal_id=proposal.id,
                type=component_data['type'],
                name=component_data['name']
            )
            db.session.add(new_component)
            
            # Log new component
            log_audit('add_proposal_component',
                     f"Added {component_data['type']} component '{component_data['name']}' "
                     f"to proposal {proposal.bid_id}")
            
            # Add component lines
            for line_data in component_data.get('lines', []):
                new_line = ProposalComponentLine(
                    component=new_component,
                    name=line_data['name'],
                    value=line_data['value']
                )
                db.session.add(new_line)
                
                # Log new line
                log_audit('add_proposal_component_line',
                         f"Added line item '{line_data['name']}' with value {line_data['value']} "
                         f"to component '{component_data['name']}'")

    except Exception as e:
        error_msg = f"Error handling proposal components: {str(e)}"
        app.logger.error(error_msg)
        log_audit('handle_components_error', error_msg)
        raise

@app.route('/audit', methods=['GET'])
@admin_required
def audit_report():
    try:
        # Initialize default values
        audit_logs = None
        action_types = []
        users = []
        current_filters = {
            'start_date': None,
            'end_date': None,
            'action_type': None,
            'username': None
        }

        # Get filter parameters
        current_filters['start_date'] = request.args.get('start_date')
        current_filters['end_date'] = request.args.get('end_date')
        current_filters['action_type'] = request.args.get('action_type')
        current_filters['username'] = request.args.get('username')
        
        # Base query
        query = AuditLog.query.join(User, AuditLog.user_id == User.id, isouter=True)
        
        # Apply filters
        if current_filters['start_date']:
            try:
                start_date = datetime.strptime(current_filters['start_date'], '%Y-%m-%d')
                query = query.filter(AuditLog.timestamp >= start_date)
            except ValueError:
                flash('Invalid start date format', 'error')
        
        if current_filters['end_date']:
            try:
                # Add one day to include the entire end date
                end_date = datetime.strptime(current_filters['end_date'], '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(AuditLog.timestamp < end_date)
            except ValueError:
                flash('Invalid end date format', 'error')
        
        if current_filters['action_type']:
            query = query.filter(AuditLog.action == current_filters['action_type'])
            
        if current_filters['username']:
            query = query.filter(User.username == current_filters['username'])
            
        # Get unique action types for the filter dropdown
        action_types = db.session.query(AuditLog.action).distinct().all()
        action_types = [action[0] for action in action_types if action[0]]
        
        # Get all users for the filter dropdown
        users = User.query.order_by(User.username).all()
        
        # Paginate results
        page = request.args.get('page', 1, type=int)
        per_page = 50
        
        audit_logs = query.order_by(AuditLog.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False)
        
        return render_template(
            'audit_report.html',
            audit_logs=audit_logs,
            action_types=action_types,
            users=users,
            current_filters=current_filters
        )
        
    except Exception as e:
        app.logger.error(f"Error in audit report: {str(e)}")
        flash(f'Error generating audit report: {str(e)}', 'error')
        return redirect(url_for('home'))

def get_category_mapping():
    """Return the mapping of actions to categories."""
    return {
        # Authentication & User Management
        'login': 'Authentication',
        'login_failed': 'Authentication',
        'password_reset': 'Authentication',
        'create_user': 'User Management',
        'update_user': 'User Management',
        'delete_user': 'User Management',
        
        # Bids
        'create_bid': 'Bids',
        'update_bid': 'Bids',
        'delete_bid': 'Bids',
        'save_sub_bid_success': 'Bids',
        'update_sub_bid': 'Bids',
        'update_sub_bid_item': 'Bids',
        'bid_error': 'Bids',
        
        # Proposals
        'create_proposal': 'Proposals',
        'update_proposal': 'Proposals',
        'save_proposal_success': 'Proposals',
        'save_proposal_error': 'Proposals',
        
        # Projects
        'create_project': 'Projects',
        'update_project': 'Projects',
        'update_project_error': 'Projects',
        
        # Customers
        'create_customer': 'Customers',
        'update_customer': 'Customers',
        'delete_customer': 'Customers',
        'customer_management_error': 'Customers',
        
        # Inventory
        'create_inventory': 'Inventory',
        'update_inventory': 'Inventory',
        'delete_inventory': 'Inventory',
        'inventory_error': 'Inventory',
        
        # Factor Codes
        'create_factor_code': 'Factor Codes',
        'update_factor_code': 'Factor Codes',
        'delete_factor_code': 'Factor Codes',
        'factor_code_error': 'Factor Codes',
        
        # Tax Management
        'create_tax_rate': 'Tax',
        'update_tax_rate': 'Tax',
        'tax_rate_error': 'Tax'
    }

def get_category(action):
    """Helper function to get the category for an audit action."""
    mapping = get_category_mapping()
    
    # Check if the action contains 'error'
    if 'error' in action.lower():
        return 'Error'
        
    return mapping.get(action, 'Other')


@app.route('/audit/pdf', methods=['GET'])
@admin_required
def generate_audit_pdf():
    try:
        # Get filter parameters and handle None values
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        action_type = request.args.get('action_type')
        username = request.args.get('username')

        # Base query - Updated to use SQLAlchemy 2.0 style
        query = db.session.query(AuditLog).join(User)

        # Apply filters only if they have valid values
        if start_date and start_date != 'None':
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(AuditLog.timestamp >= start_date)
            except ValueError:
                pass

        if end_date and end_date != 'None':
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(AuditLog.timestamp < end_date)
            except ValueError:
                pass

        if action_type and action_type != 'None':
            query = query.filter(AuditLog.action == action_type)

        if username and username != 'None':
            query = query.filter(User.username == username)

        # Get the audit logs ordered by timestamp - Updated to use SQLAlchemy 2.0 style
        audit_logs = query.order_by(AuditLog.timestamp.desc()).all()

        # Create PDF buffer with a larger page size for better content fitting
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),  # Now properly imported
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        # Define styles
        styles = getSampleStyleSheet()

        # Custom title style with corporate blue color
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Title'],
            fontSize=24,
            textColor=colors.HexColor('#1a365d'),  # Darker blue for professionalism
            spaceAfter=20,
            alignment=1,
            fontName='Helvetica-Bold'
        )

        # Custom header style
        header_style = ParagraphStyle(
            'CustomHeader',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2c5282'),  # Professional blue
            spaceBefore=12,
            spaceAfter=12,
            fontName='Helvetica-Bold'
        )

        # Custom normal text style
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#2d3748'),  # Dark gray for readability
            spaceBefore=2,
            spaceAfter=2,
            fontName='Helvetica'
        )

        # Prepare story (content) for the PDF
        story = []

        # Add title
        story.append(Paragraph("Audit Trail Report", title_style))
        
        # Add generation timestamp with more professional formatting
        story.append(Paragraph(
            f"Report Generated: {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}",
            normal_style
        ))

        # Add filter information
        filter_info = []
        if start_date and start_date != 'None':
            filter_info.append(f"Start Date: {start_date.strftime('%B %d, %Y')}")
        if end_date and end_date != 'None':
            filter_info.append(f"End Date: {(end_date - timedelta(days=1)).strftime('%B %d, %Y')}")
        if action_type and action_type != 'None':
            filter_info.append(f"Action Type: {action_type.replace('_', ' ').title()}")
        if username and username != 'None':
            filter_info.append(f"User: {username}")

        if filter_info:
            story.append(Spacer(1, 15))
            story.append(Paragraph("Report Filters", header_style))
            for info in filter_info:
                story.append(Paragraph(info, normal_style))

        # Custom header text style with white color
        header_text_style = ParagraphStyle(
            'HeaderText',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.white,
            fontName='Helvetica-Bold'
        )

        # Create table data with Paragraph objects for proper text wrapping
        data = [[
            Paragraph('Timestamp', header_text_style),
            Paragraph('User', header_text_style),
            Paragraph('Action', header_text_style),
            Paragraph('Details', header_text_style)
        ]]
        
        for log in audit_logs:
            # Ensure proper text wrapping for potentially long content
            details = log.details or 'No details provided'
            # Escape any HTML characters in the details
            details = details.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            data.append([
                Paragraph(log.timestamp.strftime('%Y-%m-%d<br/>%H:%M:%S'), normal_style),
                Paragraph(log.user.username if log.user else 'System', normal_style),
                Paragraph(log.action.replace('_', ' ').title(), normal_style),
                Paragraph(details, normal_style)
            ])

        # Calculate column widths for landscape orientation
        page_width = landscape(letter)[0] - doc.leftMargin - doc.rightMargin
        col_widths = [
            page_width * 0.15,  # Timestamp
            page_width * 0.15,  # User
            page_width * 0.15,  # Action
            page_width * 0.55   # Details - More space for long text
        ]

        # Create and style the table
        table_style = TableStyle([
            # Header style
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            
            # Content style
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2d3748')),
            
            # Improved spacing and padding
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),

            # Refined grid style
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('LINEABOVE', (0, 0), (-1, 0), 2, colors.HexColor('#2c5282')),
            ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#2c5282')),
            
            # Row styling for better readability
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')]),

            # Alignment and word wrapping
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ])

        # Create the table with automatic height adjustment
        table = Table(data, colWidths=col_widths, repeatRows=1, splitByRow=True)
        table.setStyle(table_style)

        # Add space before the table
        story.append(Spacer(1, 20))
        story.append(table)

        # Build the PDF
        doc.build(story)
        buffer.seek(0)

        # Generate filename with current timestamp
        filename = f'audit_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        
        return send_file(
            buffer,
            download_name=filename,
            as_attachment=True,
            mimetype='application/pdf'
        )
    
    except Exception as e:
        current_app.logger.error(f"Error generating PDF: {str(e)}")
        return jsonify({"error": "Failed to generate PDF report"}), 500
    

# Update the login route with audit logging
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username').lower()
        password = request.form.get('password')
        
        user = User.query.filter(func.lower(User.username) == username).first()
        
        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            login_user(user)
            
            # Add audit log for successful login
            log_audit('login', f'User {username} logged in successfully', user.id)
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home'))
        else:
            # Add audit log for failed login attempt
            log_audit('login_failed', f'Failed login attempt for username: {username}')
            flash('Invalid username or password', 'error')
    return render_template('login.html')


@app.route('/api/purchase-order/save', methods=['POST'])
@staff_required
def save_purchase_order():
    try:
        data = request.json
        if not data or not data.get('po_number'):
            return jsonify({'success': False, 'message': 'Invalid data'}), 400

        # Get or create PO
        po = PurchaseOrder.query.get(data['po_number'])
        if not po:
            parts = data['po_number'].split('-')
            if len(parts) != 3:
                return jsonify({'success': False, 'message': 'Invalid PO number format'}), 400

            job_id, category_code, _ = parts
            category_map = {
                'D': 'drains',
                'I': 'irrigation',
                'L': 'landscape',
                'M': 'maintenance',
                'S': 'subcontract'
            }
            category = category_map.get(category_code)

            po = PurchaseOrder(
                po_number=data['po_number'],
                job_id=job_id,
                category=category,
                status='in_progress'
            )
            db.session.add(po)
            log_audit('create_purchase_order', f"Created new purchase order {data['po_number']}")
        else:
            log_audit('update_purchase_order', f"Updated purchase order {data['po_number']}")

        # Update PO details
        po.date_needed = datetime.strptime(data['date_needed'], '%Y-%m-%d') if data.get('date_needed') else None
        po.ship_to_job = data.get('ship_to_job', True)
        po.last_updated = datetime.utcnow()

        # Remove old items
        PurchaseOrderItem.query.filter_by(po_number=po.po_number).delete()
        
        total_amount = 0
        items_count = 0
        
        for item_data in data.get('items', []):
            if float(item_data.get('order_qty', 0)) > 0 or item_data.get('description', '').strip():
                new_item = PurchaseOrderItem(
                    po_number=po.po_number,
                    part_number=item_data['part_number'],
                    description=item_data['description'],  # use the custom description here
                    quantity=float(item_data['order_qty']),
                    unit_cost=float(item_data['order_cost']),
                    total_cost=float(item_data['order_qty']) * float(item_data['order_cost']),
                    vendor_id=item_data.get('vendor_id')
                )
                db.session.add(new_item)
                total_amount += new_item.total_cost
                items_count += 1

        # Update PO totals
        po.amount = total_amount
        po.items_count = items_count

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Purchase order saved successfully',
            'po_number': po.po_number,
            'status': po.status,
            'job_id': po.job_id  # Include job_id for redirecting
        })

    except Exception as e:
        db.session.rollback()
        log_audit('save_purchase_order_error', f"Error saving purchase order: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/purchase-order/<po_number>/finalize', methods=['POST'])
@staff_required
def finalize_purchase_order(po_number):
    try:
        original_po = PurchaseOrder.query.get_or_404(po_number)
        validation_errors = []

        if original_po.status != 'in_progress':
            validation_errors.append(f'Purchase order must be in progress (current status: {original_po.status})')

        active_items = PurchaseOrderItem.query.filter(
            PurchaseOrderItem.po_number == po_number,
            PurchaseOrderItem.quantity > 0
        ).all()

        if not active_items:
            validation_errors.append('Cannot finalize purchase order with no items')

        # Collect vendor IDs from active items
        vendors_map = {}
        for item in active_items:
            if not item.vendor_id:
                validation_errors.append(f'Missing vendor for {item.part_number} - {item.description}')
            else:
                vendors_map.setdefault(item.vendor_id, []).append(item)

        if not original_po.date_needed:
            validation_errors.append('Date needed is required')

        if validation_errors:
            return jsonify({
                'success': False,
                'message': 'Validation failed',
                'errors': validation_errors
            }), 400

        # Get associated bid and project
        job = Job.query.get(original_po.job_id)
        bid = job.bid if job else None
        project = Project.query.filter_by(project_name=bid.project_name).first() if bid else None

        # Parse original PO number: JOBID-CATEGORY-SEQ
        parts = po_number.split('-')
        if len(parts) != 3:
            return jsonify({'success': False, 'message': 'Invalid PO number format'}), 400

        job_id, cat_code, base_seq_str = parts
        base_seq = int(base_seq_str)

        # If there's only one vendor, we just finalize the original PO with that vendor's items.
        # If multiple vendors, first vendor gets the original number, and subsequent vendors get incremented numbers.
        vendor_ids = list(vendors_map.keys())
        vendor_count = len(vendor_ids)

        finalized_po_details = []

        # Clear original items - we'll reassign them below
        PurchaseOrderItem.query.filter_by(po_number=po_number).delete()
        db.session.commit()

        # We'll use a helper function to generate PO data and PDFs
        def finalize_vendor_po(po_number, vendor_id, items_for_vendor, main_po=False):
            # Create/update PO
            if main_po:
                # Use the existing PO entry for the first vendor
                vendor_po = original_po
                vendor_po.status = 'completed'
                vendor_po.finalized_at = datetime.utcnow()
            else:
                # Create a new PO for subsequent vendors
                vendor_po = PurchaseOrder(
                    po_number=po_number,
                    job_id=original_po.job_id,
                    category=original_po.category,
                    date_needed=original_po.date_needed,
                    ship_to_job=original_po.ship_to_job,
                    status='completed',
                    finalized_at=datetime.utcnow(),
                    date_created=datetime.utcnow()
                )
                db.session.add(vendor_po)
                db.session.flush()

            # Add items to this vendor PO
            material_total = 0
            for v_item in items_for_vendor:
                new_item = PurchaseOrderItem(
                    po_number=vendor_po.po_number,
                    part_number=v_item.part_number,
                    description=v_item.description,
                    quantity=v_item.quantity,
                    unit_cost=v_item.unit_cost,
                    total_cost=v_item.quantity * v_item.unit_cost,
                    vendor_id=v_item.vendor_id
                )
                db.session.add(new_item)
                material_total += new_item.total_cost

            vendor_po.items_count = len(items_for_vendor)
            sales_tax = material_total * (float(bid.local_sales_tax) / 100) if bid and bid.local_sales_tax else 0.0
            vendor_po.amount = material_total + sales_tax

            db.session.commit()

            # Get vendor info
            vendor = Vendor.query.get(vendor_id)

            # Prepare PO data for PDF
            po_data = {
                'po_number': vendor_po.po_number,
                'date_needed': vendor_po.date_needed.strftime('%Y-%m-%d') if vendor_po.date_needed else None,
                'vendor': vendor.to_dict() if vendor else {},
                'project': {
                    'name': project.project_name if project else '',
                    'address': project.project_address if project else '',
                    'city': project.project_city if project else '',
                    'state': project.project_state if project else '',
                    'zip_code': project.project_zip if project else '',
                    'point_of_contact': project.point_of_contact if project else None
                },
                'items': [{
                    'part_number': itm.part_number,
                    'description': itm.description,
                    'quantity': float(itm.quantity),
                    'cost': float(itm.unit_cost),
                    'additional_description': ''
                } for itm in items_for_vendor],
                'tax_rate': float(bid.local_sales_tax) if bid and bid.local_sales_tax else 0.0,
                'comments': [],  # no new comments are added here, implement if needed
                'ship_to_job': vendor_po.ship_to_job
            }

            # Generate PDFs
            complete_pdf_buffer = generate_purchase_order_pdf(po_data, show_costs=True)
            complete_pdf_bytes = complete_pdf_buffer.read()
            complete_pdf_base64 = base64.b64encode(complete_pdf_bytes).decode('utf-8')

            no_cost_pdf_buffer = generate_purchase_order_pdf(po_data, show_costs=False)
            no_cost_pdf_bytes = no_cost_pdf_buffer.read()
            no_cost_pdf_base64 = base64.b64encode(no_cost_pdf_bytes).decode('utf-8')

            finalized_po_details.append({
                'po_number': vendor_po.po_number,
                'finalized_at': vendor_po.finalized_at.isoformat() if vendor_po.finalized_at else None,
                'complete_pdf': complete_pdf_base64,
                'no_cost_pdf': no_cost_pdf_base64
            })

        if vendor_count == 1:
            # Single vendor: finalize with original PO number
            single_vendor_id = vendor_ids[0]
            finalize_vendor_po(po_number, single_vendor_id, vendors_map[single_vendor_id], main_po=True)
        else:
            # Multiple vendors:
            # First vendor uses original PO number
            first_vendor_id = vendor_ids[0]
            finalize_vendor_po(po_number, first_vendor_id, vendors_map[first_vendor_id], main_po=True)

            # Subsequent vendors get incremented numbers
            current_seq = base_seq
            for vendor_id in vendor_ids[1:]:
                current_seq += 1
                new_po_number = f"{job_id}-{cat_code}-{current_seq}"
                finalize_vendor_po(new_po_number, vendor_id, vendors_map[vendor_id], main_po=False)

        return jsonify({
            'success': True,
            'message': 'Purchase order(s) finalized successfully',
            'finalized_pos': finalized_po_details,
            'redirect_url': f'/purchase-orders?job_id={original_po.job_id}'
        })

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error finalizing purchase order {po_number}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Error finalizing purchase order: {str(e)}"
        }), 500


@app.route('/api/purchase-order/<po_number>/comments/<int:comment_id>', methods=['PUT'])
@staff_required
def edit_comment(po_number, comment_id):
    try:
        data = request.json
        new_text = data.get('text')
        
        if not new_text:
            return jsonify({'success': False, 'message': 'Comment text is required'}), 400
        
        comment = Comment.query.filter_by(id=comment_id, po_number=po_number).first()
        if not comment:
            return jsonify({'success': False, 'message': 'Comment not found'}), 404

        # Check if the user is authorized to edit (depending on your requirements)
        # For simplicity, let's just allow any staff user to edit
        comment.text = new_text
        db.session.commit()

        return jsonify({'success': True, 'message': 'Comment updated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/purchase-order/<po_number>/comments/<int:comment_id>', methods=['DELETE'])
@staff_required
def delete_comment(po_number, comment_id):
    try:
        comment = Comment.query.filter_by(id=comment_id, po_number=po_number).first()
        if not comment:
            return jsonify({'success': False, 'message': 'Comment not found'}), 404

        # Check if user is authorized to delete (depending on your requirements)
        db.session.delete(comment)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Comment deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/purchase-order/<po_number>/reopen', methods=['POST'])
@staff_required
def reopen_purchase_order(po_number):
    try:
        po = PurchaseOrder.query.get_or_404(po_number)
        if po.status == 'completed':
            # Make sure there's no other in-progress PO in this category for the same job
            existing_in_progress = PurchaseOrder.get_in_progress_po(po.job_id, po.category)
            if existing_in_progress and existing_in_progress.po_number != po_number:
                return jsonify({
                    'success': False,
                    'message': 'Another purchase order is already in progress for this category'
                }), 400
            # Reopen the PO
            po.status = 'in_progress'
            po.finalized_at = None
            db.session.commit()
            log_audit('reopen_purchase_order', f"Reopened purchase order {po_number}")
            return jsonify({'success': True, 'message': 'Purchase order reopened successfully'})
        else:
            # If it's already in progress or new, no need to reopen
            return jsonify({'success': True, 'message': 'No change needed'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/purchase-orders/<job_id>')
@staff_required
def get_purchase_orders(job_id):
    try:
        category = request.args.get('category', 'all')
        
        # Base query
        query = PurchaseOrder.query.filter_by(job_id=job_id)
        
        # Apply category filter if specified
        if category != 'all':
            query = query.filter_by(category=category)
            
        # Define the status ordering without using case
        def status_order(status):
            if status == 'in_progress':
                return 0
            elif status == 'completed':
                return 1
            return 2
            
        # Get all POs and sort them in Python
        purchase_orders = query.all()
        purchase_orders.sort(key=lambda po: (status_order(po.status), po.date_created), reverse=True)
        
        pos_data = [{
            'po_number': po.po_number,
            'date_created': po.date_created.isoformat() if po.date_created else None,
            'items_count': po.items_count,
            'amount': float(po.amount) if po.amount is not None else 0.0,
            'category': po.category,
            'status': po.status,
            'vendor': po.vendor,
            'last_updated': po.last_updated.isoformat() if po.last_updated else None,
            'finalized_at': po.finalized_at.isoformat() if po.finalized_at else None
        } for po in purchase_orders]
        
        return jsonify({
            'success': True,
            'purchase_orders': pos_data
        })
        
    except Exception as e:
        app.logger.error(f"Error fetching purchase orders for job {job_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error fetching purchase orders: {str(e)}'
        }), 500

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

# Update the send_reset_email function to ensure timezone-aware datetime
def send_reset_email(user):
    token = secrets.token_urlsafe(32)
    user.reset_token = token
    # Make sure to store timezone-aware datetime
    user.reset_token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    db.session.commit()
    
    reset_url = url_for('reset_password_with_token', token=token, _external=True)
    
    try:
        msg = Message('Password Reset Request',
                    recipients=[user.email])
        msg.body = f'''To reset your password, visit the following link:

{reset_url}

If you did not make this request, simply ignore this email and no changes will be made.

This link will expire in 1 hour.
'''
        mail.send(msg)
        flash('An email has been sent with instructions to reset your password.', 'success')
    except Exception as e:
        app.logger.error(f"Error sending email: {str(e)}")
        # For testing/development, still show the reset URL
        flash(f'Error sending email. For testing, use this link: {reset_url}', 'warning')
    
    return token


@app.route('/reset-password-request', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    form = RequestResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            send_reset_email(user)
            flash('Check your email for instructions to reset your password.', 'info')
            return redirect(url_for('login'))
        else:
            flash('No account found with that email address.', 'error')
    
    return render_template('password_reset_request.html', form=form)

# 3. User Management - Track password resets
@app.route('/reset-password', methods=['POST'])
@admin_required
def reset_password():
    data = request.get_json()
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({
            'success': False,
            'message': 'User ID is required.'
        }), 400
        
    target_user = User.query.get(user_id)
    if not target_user:
        return jsonify({
            'success': False,
            'message': 'User not found.'
        }), 404
        
    try:
        # Generate a random password
        new_password = ''.join(random.choices(string.ascii_letters + string.digits, k=7))
        
        # Update user's password
        target_user.set_password(new_password)
        db.session.commit()
        
        # Log the password reset
        log_audit('password_reset', 
                 f"Password reset for user '{target_user.username}' by {current_user.username}")
        
        return jsonify({
            'success': True,
            'message': f'Password reset successfully. New password: {new_password}',
            'password': new_password
        })
        
    except Exception as e:
        db.session.rollback()
        log_audit('password_reset_error', 
                 f"Error resetting password for user {target_user.username}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error resetting password: {str(e)}'
        }), 500


# Update the route function with proper datetime handling
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    user = User.query.filter_by(reset_token=token).first()
    
    if user is None:
        flash('Invalid reset token.', 'error')
        return redirect(url_for('reset_password_request'))
    
    # Convert reset_token_expiration to UTC if it's not None
    expiration_time = user.reset_token_expiration
    if expiration_time is not None:
        # Make naive datetime timezone-aware
        if expiration_time.tzinfo is None:
            expiration_time = expiration_time.replace(tzinfo=timezone.utc)
        
        if expiration_time < datetime.now(timezone.utc):
            user.reset_token = None
            user.reset_token_expiration = None
            db.session.commit()
            flash('The password reset link has expired.', 'error')
            return redirect(url_for('reset_password_request'))
        
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.reset_token = None
        user.reset_token_expiration = None
        db.session.commit()
        flash('Your password has been updated! You can now log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('reset_password.html', form=form, token=token)

@app.route('/api/subbids/<int:subbid_id>/items', methods=['GET'])
@staff_required
def get_subbid_items(subbid_id):
    try:
        subbid = SubBid.query.get_or_404(subbid_id)
        items = SubBidItem.query.filter_by(sub_bid_id=subbid_id).all()
        
        items_data = [{
            'id': item.id,
            'part_number': item.part_number,
            'description': item.description,
            'additional_description': item.additional_description,  # Add this line
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
@staff_required
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
@staff_required
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
@staff_required
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

@app.route('/api/search-jobs', methods=['GET'])
@staff_required
def search_jobs():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({
            'success': True,
            'jobs': []
        })

    try:
        # Search across Job, Bid, Project, and Customer tables
        # First, get job IDs from Jobs table
        job_results = Job.query.filter(
            Job.job_id.ilike(f'%{query}%')
        ).all()
        job_ids = set(job.job_id for job in job_results)

        # Search in Bids table for project name and customer name matches
        bid_results = Bid.query.filter(
            db.or_(
                Bid.project_name.ilike(f'%{query}%'),
                Bid.customer_name.ilike(f'%{query}%'),
                Bid.project_address.ilike(f'%{query}%')
            )
        ).all()

        # Get jobs from matching bids
        for bid in bid_results:
            job = Job.query.filter_by(bid_id=bid.bid_id).first()
            if job:
                job_ids.add(job.job_id)

        # Get full details for all matching jobs
        matching_jobs = []
        for job_id in job_ids:
            job = Job.query.get(job_id)
            if job and job.bid:
                # Get project details if available
                project = Project.query.filter_by(project_name=job.bid.project_name).first()
                
                matching_jobs.append({
                    'job_number': job.job_id,
                    'project_name': job.bid.project_name if job.bid else '',
                    'customer_name': job.bid.customer_name if job.bid else '',
                    'project_address': project.project_address if project else job.bid.project_address if job.bid else ''
                })

        # Sort results by job number
        matching_jobs.sort(key=lambda x: x['job_number'])

        return jsonify({
            'success': True,
            'jobs': matching_jobs
        })

    except Exception as e:
        app.logger.error(f"Error searching jobs: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error searching jobs: {str(e)}'
        }), 500

@app.route('/search-engineers', methods=['GET'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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
            # Check if a job exists for this bid
            job = Job.query.filter_by(bid_id=bid.bid_id).first()
            
            bids_data.append({
                'bid_id': bid.bid_id,
                'project_name': bid.project_name,
                'customer_name': bid.customer_name,
                'engineer_name': bid.engineer_name,
                'architect_name': bid.architect_name,
                'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,
                'point_of_contact': bid.point_of_contact,
                'local_sales_tax': float(bid.local_sales_tax) if bid.local_sales_tax else None,
                'urgency': bid.urgency,  # Include urgency
                'job_id': job.job_id if job else None  # Include job_id
            })

        return jsonify({
            'bids': bids_data,
            'current_page': page,
            'pages': pages,
            'total': total_items
        })
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500
    

@app.route('/get_next_bid_id', methods=['GET'])
@staff_required
def get_next_bid_id():
    try:
        # Get the latest bid ID from the database
        latest_bid = Bid.query.order_by(Bid.bid_id.desc()).first()
        
        if latest_bid:
            # If there are existing bids, increment the last one
            last_id = latest_bid.bid_id
            # Use a more robust parsing method
            try:
                # Extract only the numeric part, assuming the format starts with 'B' followed by digits
                numeric_part = ''.join(filter(str.isdigit, last_id))
                num = int(numeric_part) + 1 if numeric_part else 1
            except (ValueError, TypeError):
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
@staff_required
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
@staff_required
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
@admin_required
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
@staff_required
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
@staff_required
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
@staff_required
def save_tax_rate():
    try:
        data = request.json
        if not data:
            error_msg = "No tax rate data provided"
            log_audit('tax_rate_error', error_msg)
            return jsonify({'error': error_msg}), 400

        zip_code = data.get('zip_code')
        tax_rate = data.get('tax_rate')
        
        if not zip_code:
            error_msg = "Missing zip_code"
            log_audit('tax_rate_error', error_msg)
            return jsonify({'error': error_msg}), 400
        
        if tax_rate is None:
            error_msg = "Missing tax_rate"
            log_audit('tax_rate_error', error_msg)
            return jsonify({'error': error_msg}), 400
        
        try:
            tax_rate = float(tax_rate)
        except ValueError:
            error_msg = f"Invalid tax_rate value: {tax_rate}"
            log_audit('tax_rate_error', error_msg)
            return jsonify({'error': error_msg}), 400
        
        # Query for existing tax record
        tax = Tax.query.filter_by(zip_code=zip_code).first()
        
        if tax:
            # Store old value for comparison
            old_rate = tax.tax_rate
            
            # Update existing record
            tax.tax_rate = tax_rate
            tax.last_updated = datetime.utcnow()
            
            if old_rate != tax_rate:
                log_audit('update_tax_rate', 
                         f"Updated tax rate for zip code {zip_code}. "
                         f"Rate changed: {old_rate}% → {tax_rate}%")
        else:
            # Create new tax record
            tax = Tax(
                zip_code=zip_code, 
                tax_rate=tax_rate,
                last_updated=datetime.utcnow()
            )
            db.session.add(tax)
            
            log_audit('create_tax_rate', 
                     f"Created new tax rate entry for zip code {zip_code} "
                     f"with rate {tax_rate}%")
        
        db.session.commit()
        return jsonify({
            'success': True, 
            'message': 'Tax rate saved successfully'
        })
        
    except SQLAlchemyError as e:
        db.session.rollback()
        error_msg = f"Database error saving tax rate: {str(e)}"
        log_audit('tax_rate_error', error_msg)
        return jsonify({
            'success': False, 
            'message': error_msg
        }), 500
        
    except Exception as e:
        db.session.rollback()
        error_msg = f"Unexpected error saving tax rate: {str(e)}"
        log_audit('tax_rate_error', error_msg)
        return jsonify({
            'success': False, 
            'message': error_msg
        }), 500

@app.route('/customer-management', methods=['GET', 'POST'])
@staff_required
def customer_management():
    if request.method == 'POST':
        customer_data = {
            'name': request.form.get('customer_name'),
            'address': request.form.get('customer_address'),
            'state': request.form.get('customer_state'),
            'city': request.form.get('customer_city'),
            'zip': request.form.get('customer_zip')
        }

        existing_customer = Customer.query.get(customer_data['name'])

        try:
            if existing_customer:
                # Store old values for audit
                old_data = {
                    'address': existing_customer.customer_address,
                    'state': existing_customer.customer_state,
                    'city': existing_customer.customer_city,
                    'zip': existing_customer.customer_zip
                }
                
                # Update customer
                existing_customer.customer_address = customer_data['address']
                existing_customer.customer_state = customer_data['state']
                existing_customer.customer_city = customer_data['city']
                existing_customer.customer_zip = customer_data['zip']
                
                # Log changes
                changes = []
                for field, old_value in old_data.items():
                    new_value = customer_data[field]
                    if old_value != new_value:
                        changes.append(f"{field}: '{old_value}' → '{new_value}'")
                
                if changes:
                    log_audit('update_customer', 
                             f"Updated customer '{customer_data['name']}'. Changes: {', '.join(changes)}")
                flash("Customer updated successfully.", "success")
            else:
                # Create new customer
                new_customer = Customer(
                    customer_name=customer_data['name'],
                    customer_address=customer_data['address'],
                    customer_state=customer_data['state'],
                    customer_city=customer_data['city'],
                    customer_zip=customer_data['zip']
                )
                db.session.add(new_customer)
                
                # Log creation
                log_audit('create_customer', 
                         f"Created new customer '{customer_data['name']}' with "
                         f"address: {customer_data['address']}, {customer_data['city']}, "
                         f"{customer_data['state']}")
                flash("New customer created successfully.", "success")

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log_audit(f"{'update' if existing_customer else 'create'}_customer_error",
                     f"Error processing customer {customer_data['name']}: {str(e)}")
            flash(f"An error occurred: {str(e)}", "error")

        return redirect(url_for('customer_management'))

    # For GET request
    page = request.args.get('page', 1, type=int)
    per_page = 20
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
@admin_required
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
@admin_required
def add_item_to_conversion_code():
    data = request.json
    code = data.get('code')
    part_number = data.get('part_number')
    csrf_token = data.get('csrf_token')

    if not all([code, part_number, csrf_token]):
        error_msg = "Missing required fields"
        log_audit('conversion_code_error', 
                 f"Attempt to add item without required fields. "
                 f"Code: {code}, Part: {part_number}")
        return jsonify({'success': False, 'message': error_msg}), 400

    try:
        # Ensure the part number exists in the Inventory
        inventory_item = Inventory.query.filter_by(part_number=part_number).first()
        if not inventory_item:
            error_msg = "Part number not found in inventory"
            log_audit('conversion_code_error', 
                     f"Attempt to add non-existent part {part_number} "
                     f"to conversion code {code}")
            return jsonify({'success': False, 'message': error_msg}), 400

        # Add the item to the conversion code
        conversion_code = ConversionCode.query.filter_by(code=code).first()
        if conversion_code:
            # Check if the item is already associated
            if inventory_item in conversion_code.inventory_items:
                log_audit('conversion_code_warning', 
                         f"Attempt to add duplicate part {part_number} "
                         f"to conversion code {code}")
                return jsonify({
                    'success': False, 
                    'message': 'Item already exists in conversion code'
                }), 400
                
            conversion_code.inventory_items.append(inventory_item)
            db.session.commit()
            
            log_audit('add_conversion_code_item', 
                     f"Added part {part_number} ({inventory_item.description}) "
                     f"to conversion code {code}")
            
            return jsonify({'success': True, 'code': code}), 200
        else:
            error_msg = "Conversion code not found"
            log_audit('conversion_code_error', 
                     f"Attempt to add item to non-existent code {code}")
            return jsonify({'success': False, 'message': error_msg}), 400

    except Exception as e:
        db.session.rollback()
        error_msg = f"Error adding item to conversion code: {str(e)}"
        log_audit('conversion_code_error', 
                 f"Error adding part {part_number} to code {code}: {str(e)}")
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/search-conversion-codes', methods=['GET'])
@staff_required
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
@admin_required
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
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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
                'additional_description': item.additional_description,            
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
                'point_of_contact': bid.point_of_contact,
                'bid_amount': bid.bid_amount or 0.0,
                'comments': bid.comments  # Add this line to include the comments field
            }
        }
        return jsonify(response_data), 200
    except Exception as e:
        app.logger.error(f"Error fetching bid items: {str(e)}")
        return jsonify({"error": "An error occurred while fetching bid items"}), 500



def generate_weekly_bid_schedule_pdf():
    # Create a buffer for the PDF
    buffer = BytesIO()
    
    # Create the PDF document in landscape orientation
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), 
                            rightMargin=36, leftMargin=36, 
                            topMargin=36, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = styles['Title']
    heading_style = styles['Normal']
    heading_style.fontSize = 10
    
    # Create a small paragraph style for project and customer
    small_text_style = ParagraphStyle(
        'SmallText',
        parent=styles['Normal'],
        fontSize=6,
        leading=8
    )
    
    # Title
    elements.append(Paragraph("Weekly Bid Schedule", title_style))
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%B %d, %Y')}", heading_style))
    elements.append(Spacer(1, 12))
    
    # Fetch and sort all bids
    try:
        bids = Bid.query.all()
    except Exception as e:
        current_app.logger.error(f"Error fetching bids: {str(e)}")
        return None
    
    # Define urgency order for sorting
    # Ensure A is first, then B, then C, then R
    urgency_order = {'A': 0, 'B': 1, 'C': 2, 'R': 3, None: 4}
    
    sorted_bids = sorted(
        bids,
        key=lambda bid: (
            urgency_order.get(bid.urgency, 4),  # Urgency sorted ascending
            -bid.bid_date.toordinal() if bid.bid_date else float('inf')  # Date Needed sorted descending
        )
    )
    
    # Prepare table data with all bids
    table_data = [
        ['Urgency', 'Bid #', 'Job Description', 'Builder', 'Date Needed', 'Date Start', 'Estimator', 'Comments']
    ]
    
    # Add bid rows
    for bid in reversed(sorted_bids):
        # Create paragraphs with small font for project and customer
        project_para = Paragraph(str(bid.project_name), small_text_style)
        customer_para = Paragraph(str(bid.customer_name), small_text_style)
        
        # Modify urgency display
        display_urgency = 'A-High' if bid.urgency == 'A' else (
            'B-Med' if bid.urgency == 'B' else (
            'C-Low' if bid.urgency == 'C' else (
            'R-Review' if bid.urgency == 'R' else str(bid.urgency or '-'))))
        
        table_data.append([
            display_urgency,
            str(bid.bid_id),
            project_para,
            customer_para,
            bid.bid_date.strftime('%m/%d/%Y') if bid.bid_date else 'N/A',
            bid.date_created.strftime('%m/%d/%Y') if bid.date_created else 'N/A',
            '', # % Take Off - left blank as requested
            str(bid.comments or '')
        ])
    
    # Create table with column widths adjusted for landscape
    table = Table(table_data, 
                  repeatRows=1, 
                  colWidths=[0.75*inch, 1*inch, 1.5*inch, 1.5*inch, 1*inch, 1*inch, 1*inch, 2*inch])
    
    # Style the table
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.white),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),  # Header font
        ('FONTSIZE', (0,1), (-1,-1), 7),  # Data font
        ('BOTTOMPADDING', (0,0), (-1,0), 3),
        ('BACKGROUND', (0,1), (-1,-1), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('WORDWRAP', (0,0), (-1,-1), 1)
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    
    # Move buffer position to the beginning
    buffer.seek(0)
    
    # Return the PDF as a file
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='weekly_bid_schedule.pdf'
    )

# Add this route to your Flask application
@app.route('/weekly-bid-schedule-pdf')
@staff_required
def weekly_bid_schedule_pdf():
    from flask import current_app
    try:
        pdf_response = generate_weekly_bid_schedule_pdf()
        if pdf_response is None:
            flash('Failed to generate PDF. Please check the logs.', 'error')
            return redirect(url_for('bid_management'))
        return pdf_response
    except Exception as e:
        current_app.logger.error(f"Error generating weekly bid schedule PDF: {str(e)}")
        flash('An error occurred while generating the PDF', 'error')
        return redirect(url_for('bid_management'))

@app.route('/get-proposal-items/<bid_id>')
@staff_required
def get_proposal_items(bid_id):
    """
    Returns JSON containing all relevant proposal data for the specified bid_id + revision_number (if any).
    Includes heading fields from both the Bid table (like bid_date, local_sales_tax) and
    from the Proposal table (like architect_name, point_of_contact).
    """
    try:
        version_number = request.args.get('revision_number', type=int)
        app.logger.info(f"Fetching proposal items for bid_id: {bid_id} and version: {version_number}")

        # 1) Get the bid and associated project
        bid = Bid.query.filter_by(bid_id=bid_id).first_or_404()
        project = Project.query.filter_by(project_name=bid.project_name).first()

        # 2) Get the correct proposal (use latest if no version_number provided)
        if version_number is not None:
            proposal = Proposal.query.filter_by(bid_id=bid_id, revision_number=version_number).first_or_404()
        else:
            proposal = Proposal.query.filter_by(bid_id=bid_id).order_by(Proposal.revision_number.desc()).first_or_404()
            version_number = proposal.revision_number

        # 3) Possibly get the Customer record
        customer = Customer.query.filter_by(customer_name=bid.customer_name).first()

        # 4) Gather all proposal components and their lines
        components = []
        for comp in proposal.components:
            component_dict = {
                'type': comp.type,
                'name': comp.name,
                'lines': []
            }
            for line in comp.lines:
                component_dict['lines'].append({
                    'name': line.name,
                    'value': float(line.value) if line.value is not None else 0.0
                })
            components.append(component_dict)

        app.logger.debug(f"Found components: {components}")

        # 5) Gather all proposal options
        options = []
        for option in proposal.options:
            options.append({
                'description': option.description,
                'amount': float(option.amount) if option.amount else 0.0
            })
        app.logger.debug(f"Found options: {options}")

        # 6) Build the JSON response
        response_data = {
            # A) Labor rates from Bid table
            'labor_rates': {
                'drains_labor_rate': float(bid.drains_labor_rate) if bid.drains_labor_rate is not None else None,
                'irrigation_labor_rate': float(bid.irrigation_labor_rate) if bid.irrigation_labor_rate is not None else None,
                'landscape_labor_rate': float(bid.landscape_labor_rate) if bid.landscape_labor_rate is not None else None,
                'maintenance_labor_rate': float(bid.maintenance_labor_rate) if bid.maintenance_labor_rate is not None else None,
                'local_sales_tax': float(bid.local_sales_tax) if bid.local_sales_tax is not None else None
            },

            # B) Proposal info (pulls from BOTH Bid + Proposal)
            'proposal_info': {
                'bid_id': proposal.bid_id,
                'project_name': bid.project_name,
                'project_city': project.project_city if project else None,
                'customer_name': proposal.customer_name,
                'special_notes': json.loads(proposal.special_notes) if proposal.special_notes else [],
                'terms_conditions': json.loads(proposal.terms_conditions) if proposal.terms_conditions else [],
                'revision_number': proposal.revision_number,
                'total_budget': float(proposal.total_budget) if proposal.total_budget else None,
                'bid_date': bid.bid_date.strftime('%Y-%m-%d') if bid.bid_date else None,
                'drains_total': float(bid.drains_total) if bid.drains_total else None,
                'irrigation_total': float(bid.irrigation_total) if bid.irrigation_total else None,
                'landscaping_total': float(bid.landscaping_total) if bid.landscaping_total else None,
                'maintenance_total': float(bid.maintenance_total) if bid.maintenance_total else None,
                'exclusions': proposal.exclusions,

                # NEW: Extra heading fields stored in Proposal
                'point_of_contact': proposal.point_of_contact,
                'architect_name': proposal.architect_name,
                'architect_specifications': proposal.architect_specifications,
                'architect_dated': proposal.architect_dated,
                'architect_sheets': proposal.architect_sheets,
                'engineer_name': proposal.engineer_name,
                'engineer_specifications': proposal.engineer_specifications,
                'engineer_dated': proposal.engineer_dated,
                'engineer_sheets': proposal.engineer_sheets,
            },

            # C) Customer info from Customer table
            'customer_info': {
                'address': customer.customer_address if customer else None,
                'city': customer.customer_city if customer else None,
                'state': customer.customer_state if customer else None,
                'zip': customer.customer_zip if customer else None,
                'phone': getattr(customer, 'customer_phone', None),
                'fax': getattr(customer, 'customer_fax', None)
            },

            # D) Components & Options arrays
            'components': components,
            'options': options
        }

        app.logger.debug(f"Response data: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        app.logger.error(f"Error fetching proposal items: {str(e)}")
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500

@app.route('/api/get-next-job-number', methods=['GET'])
def get_next_job_number():
    try:
        # Query the database for all job IDs
        job_numbers = db.session.query(Job.job_id).all()
        
        # Convert all job numbers to integers for comparison
        existing_numbers = []
        for job in job_numbers:
            try:
                num = int(job[0])
                if num >= 6050:  # Only consider numbers >= 6000
                    existing_numbers.append(num)
            except ValueError:
                continue
        
        if not existing_numbers:
            # If no valid job numbers exist, start from 6000
            next_job_number = '6000'
        else:
            # Get the highest number and increment
            highest_number = max(existing_numbers)
            if highest_number < 6000:
                next_job_number = '6000'
            else:
                next_job_number = str(highest_number + 1)
        
        return jsonify({
            'success': True,
            'next_job_number': next_job_number
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
    
@app.route('/purchase-orders')
@staff_required
def Manage_Purchase_Orders():
    job_id = request.args.get('job_id')
    return render_template('ManagePurchaseOrders.html', job_id=job_id)

@app.route('/delete_customer/<path:customer_name>', methods=['POST'])
@admin_required
def delete_customer(customer_name):
    app.logger.info(f"Attempting to delete customer: {customer_name}")
    decoded_customer_name = unquote(customer_name)
    customer = Customer.query.get_or_404(decoded_customer_name)
    try:
        # Check if the customer is associated with any bids
        associated_bids = Bid.query.filter_by(customer_name=decoded_customer_name).all()
        if associated_bids:
            app.logger.warning(f"Customer {decoded_customer_name} has associated bids and cannot be deleted")
            return jsonify({
                'success': False, 
                'message': 'This customer has associated bids and cannot be deleted. Please remove all bids for this customer first.'
            }), 400

        db.session.delete(customer)
        db.session.commit()
        app.logger.info(f"Customer {decoded_customer_name} deleted successfully")
        return jsonify({'success': True, 'message': 'Customer deleted successfully.'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting customer {decoded_customer_name}: {str(e)}")
        return jsonify({'success': False, 'message': f'Error deleting customer: {str(e)}'}), 500

@app.route('/save-factor-code-items/<int:bid_id>', methods=['POST'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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

@app.route('/api/subbids/<bid_id>', methods=['POST'])
@staff_required
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

@app.route('/manage-users', methods=['GET', 'POST'])
@admin_required
def manage_users():
    if request.method == 'POST':
        user_data = {
            'username': request.form.get('username'),
            'email': request.form.get('email'),
            'password': request.form.get('password'),
            'role': request.form.get('role'),
            'user_id': request.form.get('user_id')
        }
        
        try:
            # Validate required fields for new users
            if not user_data['user_id'] and not all([user_data['username'], 
                                                    user_data['email'], 
                                                    user_data['password'], 
                                                    user_data['role']]):
                log_audit('user_management_error', 'Attempt to create user with missing required fields')
                return jsonify({
                    'success': False,
                    'message': 'All fields are required for new users.'
                }), 400
                
            if user_data['user_id']:
                # Editing existing user
                target_user = User.query.get(user_data['user_id'])
                if not target_user:
                    log_audit('user_management_error', 
                             f"Attempt to edit non-existent user ID: {user_data['user_id']}")
                    return jsonify({
                        'success': False,
                        'message': 'User not found.'
                    }), 404
                
                # Store old values for audit
                old_data = {
                    'username': target_user.username,
                    'email': target_user.email,
                    'is_admin': target_user.is_admin,
                    'is_super_admin': target_user.is_super_admin
                }
                
                # Permission checks for editing
                if current_user.is_super_admin:
                    if int(user_data['user_id']) == current_user.id:
                        log_audit('user_management_error', 
                                 f"Super admin attempted to modify own account: {current_user.username}")
                        return jsonify({
                            'success': False,
                            'message': 'Cannot modify your own account.'
                        }), 403
                else:
                    if target_user.is_admin or target_user.is_super_admin:
                        log_audit('user_management_error', 
                                 f"Non-super admin attempted to modify admin account: {target_user.username}")
                        return jsonify({
                            'success': False,
                            'message': 'You do not have permission to modify admin accounts.'
                        }), 403
                
                # Update user fields
                changes = []
                if user_data['username'] and user_data['username'] != target_user.username:
                    changes.append(f"username: '{target_user.username}' → '{user_data['username']}'")
                    target_user.username = user_data['username']
                if user_data['email'] and user_data['email'] != target_user.email:
                    changes.append(f"email: '{target_user.email}' → '{user_data['email']}'")
                    target_user.email = user_data['email']
                if user_data['password']:
                    changes.append("password: updated")
                    target_user.set_password(user_data['password'])
                if user_data['role'] and current_user.is_super_admin:
                    new_is_admin = (user_data['role'] == 'admin')
                    new_is_super_admin = (user_data['role'] == 'super_admin')
                    if new_is_admin != target_user.is_admin:
                        changes.append(f"admin status: {target_user.is_admin} → {new_is_admin}")
                    if new_is_super_admin != target_user.is_super_admin:
                        changes.append(f"super admin status: {target_user.is_super_admin} → {new_is_super_admin}")
                    target_user.is_admin = new_is_admin
                    target_user.is_super_admin = new_is_super_admin
                
                if changes:
                    log_audit('update_user', 
                             f"Updated user '{target_user.username}'. Changes: {', '.join(changes)}")
                
            else:
                # Creating new user
                # Check for existing username or email
                existing_user = User.query.filter(
                    db.or_(
                        User.username == user_data['username'],
                        User.email == user_data['email']
                    )
                ).first()
                
                if existing_user:
                    log_audit('user_management_error', 
                             f"Attempt to create user with existing username/email: {user_data['username']}")
                    return jsonify({
                        'success': False,
                        'message': 'Username or email already exists.'
                    }), 400
                    
                # Permission checks for creation
                if not current_user.is_super_admin and user_data['role'] in ['admin', 'super_admin']:
                    log_audit('user_management_error', 
                             f"Non-super admin attempted to create admin account: {user_data['username']}")
                    return jsonify({
                        'success': False,
                        'message': 'Only super administrators can create admin accounts.'
                    }), 403
                
                # Create new user
                new_user = User(
                    username=user_data['username'],
                    email=user_data['email'],
                    is_admin=(user_data['role'] == 'admin'),
                    is_super_admin=(user_data['role'] == 'super_admin')
                )
                new_user.set_password(user_data['password'])
                db.session.add(new_user)
                
                log_audit('create_user', 
                         f"Created new user '{user_data['username']}' with role '{user_data['role']}'")
            
            db.session.commit()
            return jsonify({'success': True, 'message': 'User operation completed successfully'})
            
        except Exception as e:
            db.session.rollback()
            error_msg = f"Error in user management: {str(e)}"
            log_audit('user_management_error', error_msg)
            return jsonify({
                'success': False,
                'message': error_msg
            }), 500
            
    # GET request - display users
    if current_user.is_super_admin:
        users = User.query.order_by(User.username).all()
    else:
        users = User.query.filter(
            db.or_(
                User.id == current_user.id,
                db.and_(
                    User.is_admin == False,
                    User.is_super_admin == False
                )
            )
        ).order_by(User.username).all()
        
    return render_template(
        'user_management.html',
        users=users,
        is_super_admin=current_user.is_super_admin,
        current_user_id=current_user.id
    )

@app.route('/update-user', methods=['POST'])
@super_admin_required
def update_user():
    if not current_user.is_admin:
        return jsonify({
            'success': False,
            'message': 'You do not have permission to perform this action.'
        }), 403

    data = request.get_json()
    user_id = data.get('user_id')
    username = data.get('username')
    email = data.get('email')  # Get email from request
    role = data.get('role')

    user = User.query.get(user_id)
    if not user:
        return jsonify({
            'success': False,
            'message': 'User not found.'
        }), 404

    # Check permissions
    if not current_user.is_super_admin and user.is_admin:
        return jsonify({
            'success': False,
            'message': 'Only super administrators can modify admin accounts.'
        }), 403

    try:
        # Check if username or email is being changed and if it's available
        if username != user.username:
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                return jsonify({
                    'success': False,
                    'message': 'Username already exists.'
                }), 400
            user.username = username

        if email != user.email:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                return jsonify({
                    'success': False,
                    'message': 'Email already exists.'
                }), 400
            user.email = email

        # Only super admin can change roles
        if current_user.is_super_admin:
            user.is_admin = (role == 'admin')

        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'User updated successfully.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error updating user: {str(e)}'
        }), 500

@app.route('/delete-user', methods=['POST'])
@super_admin_required
def delete_user():
    if not current_user.is_admin:
        return jsonify({
            'success': False,
            'message': 'You do not have permission to perform this action.'
        }), 403

    data = request.get_json()
    user_id = data.get('user_id')
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({
            'success': False,
            'message': 'User not found.'
        }), 404

    # Prevent deleting super admin
    if user.is_super_admin:
        return jsonify({
            'success': False,
            'message': 'Super administrator account cannot be deleted.'
        }), 403

    # Check permissions
    if not current_user.is_super_admin and user.is_admin:
        return jsonify({
            'success': False,
            'message': 'Only super administrators can delete admin accounts.'
        }), 403

    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'User deleted successfully.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error deleting user: {str(e)}'
        }), 500

@app.route('/api/part-history/<job_id>/<part_number>')
@staff_required
def get_part_history(job_id, part_number):
    try:
        # Get all POs for this job
        pos = PurchaseOrder.query.filter(
            PurchaseOrder.job_id == job_id,
            PurchaseOrder.status.in_(['completed', 'in_progress'])
        ).all()

        history = []
        for po in pos:
            # Get item from each PO
            item = PurchaseOrderItem.query.filter_by(
                po_number=po.po_number,
                part_number=part_number
            ).first()

            if item and item.quantity > 0:
                vendor = Vendor.query.get(item.vendor_id) if item.vendor_id else None
                history.append({
                    'po_number': po.po_number,
                    'date': po.date_created.isoformat(),
                    'vendor_name': vendor.name if vendor else 'N/A',
                    'quantity': float(item.quantity),
                    'unit_cost': float(item.unit_cost)
                })

        return jsonify({
            'success': True,
            'history': sorted(history, key=lambda x: x['date'], reverse=True)
        })

    except Exception as e:
        app.logger.error(f"Error fetching part history: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/update-purchase-order/<po_number>')
@staff_required
def update_purchase_order(po_number):
    try:
        # Attempt to get the purchase order; 404 if not found
        po = PurchaseOrder.query.get_or_404(po_number)
        
        # Attempt to get the job associated with this PO; 404 if not found
        job = Job.query.get_or_404(po.job_id)

        # Get the associated bid
        bid = job.bid
        if bid is None:
            app.logger.error(f"No associated bid found for job {job.job_id} while loading PO {po_number}")
            flash('Associated bid not found for this purchase order', 'error')
            return redirect(url_for('purchase_orders'))

        # If the PO is not in progress, set it to in_progress so it can be edited
        if po.status != 'in_progress':
            po.status = 'in_progress'
            db.session.commit()

        # Get all items actually used in this PO
        po_items = PurchaseOrderItem.query.filter_by(po_number=po_number).all()

        # Prepare dicts for quantities and costs
        bought_quantities = {}
        bid_quantities = {}
        bid_costs = {}

        # Get factor code items for this category
        factor_items = [item for item in bid.factor_code_items if item.category == po.category]

        # Populate bid_quantities and bid_costs if factor items exist
        for item in factor_items:
            bid_quantities[item.part_number] = item.quantity
            bid_costs[item.part_number] = item.cost

        # Calculate bought quantities from other completed POs
        other_po_items = PurchaseOrderItem.query\
            .join(PurchaseOrder, PurchaseOrder.po_number == PurchaseOrderItem.po_number)\
            .filter(
                PurchaseOrder.job_id == job.job_id,
                PurchaseOrder.category == po.category,
                PurchaseOrder.status == 'completed',
                PurchaseOrder.po_number != po_number
            ).all()

        for item in other_po_items:
            bought_quantities[item.part_number] = bought_quantities.get(item.part_number, 0) + item.quantity

        # Calculate budget and actual amounts
        budget_field = f'{po.category}_total'
        budget_amount = getattr(bid, budget_field, 0) or 0
        actual_amount = sum(p.amount for p in job.purchase_orders 
                            if p.category == po.category and p.status == 'completed') or 0
        percent_complete = (actual_amount / budget_amount * 100) if budget_amount > 0 else 0

        return render_template('update_purchase_order.html',
            po_number=po_number,
            purchase_order=po,
            job=job,
            bid=bid,
            category=po.category,
            po_items=po_items,
            bought_quantities=bought_quantities,
            bid_quantities=bid_quantities,
            bid_costs=bid_costs,
            budget_amount=budget_amount,
            actual_amount=actual_amount,
            percent_complete=percent_complete,
            now=datetime.utcnow()
        )

    except HTTPException as http_err:
        app.logger.error(f"HTTPException while loading PO {po_number}: {str(http_err)}")
        flash('Could not load the purchase order.', 'error')
        return redirect(url_for('purchase_orders'))

    except Exception as e:
        app.logger.error(f"Error updating purchase order {po_number}: {str(e)}", exc_info=True)
        flash('An error occurred while loading the purchase order', 'error')
        return redirect(url_for('purchase_orders'))



@app.route('/api/customer/<string:customer_name>', methods=['PUT'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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

def get_all_group_members_from_db():
    # Build queries for each table and unify them
    architects = select(
        Architect.id,
        Architect.name,
        Architect.company,
        Architect.phone_number,
        Architect.address.label('address1'),
        db.literal('').label('address2'),
        db.literal('').label('city'),
        db.literal('').label('state'),
        db.literal('').label('zip_code'),
        db.literal('').label('fax_number'),
        db.literal('').label('email'),
        db.literal('Architect').label('category')
    )

    engineers = select(
        Engineer.id,
        Engineer.name,
        Engineer.company,
        Engineer.phone_number,
        Engineer.address.label('address1'),
        db.literal('').label('address2'),
        db.literal('').label('city'),
        db.literal('').label('state'),
        db.literal('').label('zip_code'),
        db.literal('').label('fax_number'),
        db.literal('').label('email'),
        db.literal('Engineer').label('category')
    )

    vendors = select(
        Vendor.id,
        Vendor.name,
        Vendor.company,
        Vendor.phone_number,
        Vendor.address1,
        Vendor.address2,
        Vendor.city,
        Vendor.state,
        Vendor.zip_code,
        Vendor.fax_number,
        Vendor.email,
        db.literal('Vendor').label('category')
    )

    union_query = union(architects, engineers, vendors).alias('union_query')
    query = select(union_query).order_by(union_query.c.name)

    results = db.session.execute(query).fetchall()
    all_members = [
        {
            'id': m.id,
            'name': m.name,
            'category': m.category,
            'company': m.company,
            'address1': m.address1 or '',
            'address2': m.address2 or '',
            'city': m.city or '',
            'state': m.state or '',
            'zip_code': m.zip_code or '',
            'phone_number': m.phone_number or '',
            'fax_number': m.fax_number or '',
            'email': m.email or ''
        }
        for m in results
    ]
    return all_members


@app.route('/manage-groups', methods=['GET', 'POST'])
@staff_required
def manage_groups():
    if request.method == 'POST':
        member_id = request.form.get('member_id')
        name = request.form.get('name')
        category = request.form.get('category')
        company = request.form.get('company')
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
                    if member:
                        member.name = name
                        member.company = company
                        member.address1 = request.form.get('address1')
                        member.address2 = request.form.get('address2')
                        member.city = request.form.get('city')
                        member.state = request.form.get('state')
                        member.zip_code = request.form.get('zip_code')
                        member.phone_number = phone_number
                        member.fax_number = request.form.get('fax_number')
                        member.email = request.form.get('email')
                else:
                    return jsonify({'success': False, 'error': 'Invalid category'})

                if member:
                    if category != 'Vendor':
                        member.name = name
                        member.company = company
                        member.address = request.form.get('address1')
                        member.phone_number = phone_number

                    db.session.commit()
                    return jsonify({'success': True, 'message': 'Member updated successfully'})
                else:
                    return jsonify({'success': False, 'error': 'Member not found'})
            else:
                # Add new member
                if category == 'Architect':
                    new_member = Architect(
                        name=name,
                        company=company,
                        address=request.form.get('address1'),
                        phone_number=phone_number
                    )
                elif category == 'Engineer':
                    new_member = Engineer(
                        name=name,
                        company=company,
                        address=request.form.get('address1'),
                        phone_number=phone_number
                    )
                elif category == 'Vendor':
                    new_member = Vendor(
                        name=name,
                        company=company,
                        address1=request.form.get('address1'),
                        address2=request.form.get('address2'),
                        city=request.form.get('city'),
                        state=request.form.get('state'),
                        zip_code=request.form.get('zip_code'),
                        phone_number=phone_number,
                        fax_number=request.form.get('fax_number'),
                        email=request.form.get('email')
                    )
                else:
                    return jsonify({'success': False, 'error': 'Invalid category'})

                db.session.add(new_member)
                db.session.commit()

                member_data = {
                    'id': new_member.id,
                    'name': new_member.name,
                    'category': category,
                    'company': new_member.company,
                    'phone_number': new_member.phone_number
                }

                if category == 'Vendor':
                    member_data.update({
                        'address1': new_member.address1,
                        'address2': new_member.address2,
                        'city': new_member.city,
                        'state': new_member.state,
                        'zip_code': new_member.zip_code,
                        'fax_number': new_member.fax_number,
                        'email': new_member.email
                    })
                else:
                    member_data['address'] = new_member.address

                return jsonify({
                    'success': True,
                    'message': 'New member added successfully',
                    'member': member_data
                })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

    # For GET request - Load ALL members
    all_group_members = get_all_group_members_from_db()
    return render_template('manage_groups.html', all_group_members=all_group_members)

@app.route('/delete-group-member/<int:member_id>/<category>', methods=['POST'])
@admin_required
def delete_group_member(member_id, category):
    if category == 'Architect':
        member = db.session.get(Architect, member_id)
    elif category == 'Engineer':
        member = db.session.get(Engineer, member_id)
    elif category == 'Vendor':
        member = db.session.get(Vendor, member_id)
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
@staff_required
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
@staff_required
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
@staff_required
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


@app.route('/bid-management', methods=['GET', 'POST'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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
@admin_required
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
@admin_required
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
@staff_required
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
@admin_required
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

# 3. Enhanced project management route with detailed audit logging
@app.route('/manage-projects', methods=['GET', 'POST'])
@staff_required
def manage_projects():
    if request.method == 'POST':
        project_name = request.form.get('project_name')
        project_data = {
            'address': request.form.get('project_address'),
            'state': request.form.get('project_state'),
            'city': request.form.get('project_city'),
            'zip': request.form.get('project_zip'),
            'point_of_contact': request.form.get('point_of_contact'),
            'contact_phone_number': request.form.get('contact_phone_number')
        }

        existing_project = Project.query.filter_by(project_name=project_name).first()

        try:
            if existing_project:
                # Store old values for comparison
                old_data = {
                    'address': existing_project.project_address,
                    'state': existing_project.project_state,
                    'city': existing_project.project_city,
                    'zip': existing_project.project_zip,
                    'point_of_contact': existing_project.point_of_contact,
                    'contact_phone_number': existing_project.contact_phone_number
                }
                
                # Update project
                existing_project.project_address = project_data['address']
                existing_project.project_state = project_data['state']
                existing_project.project_city = project_data['city']
                existing_project.project_zip = project_data['zip']
                existing_project.point_of_contact = project_data['point_of_contact']
                existing_project.contact_phone_number = project_data['contact_phone_number']
                
                # Log changes
                changes = []
                for field, old_value in old_data.items():
                    new_value = project_data[field]
                    if old_value != new_value:
                        changes.append(f"{field}: '{old_value}' → '{new_value}'")
                
                if changes:
                    log_audit('update_project', 
                             f"Updated project '{project_name}'. Changes: {', '.join(changes)}")
                flash("Project updated successfully.", "success")
            else:
                # Create new project
                new_project = Project(
                    project_name=project_name,
                    project_address=project_data['address'],
                    project_state=project_data['state'],
                    project_city=project_data['city'],
                    project_zip=project_data['zip'],
                    point_of_contact=project_data['point_of_contact'],
                    contact_phone_number=project_data['contact_phone_number']
                )
                db.session.add(new_project)
                
                # Log creation
                log_audit('create_project', 
                         f"Created new project '{project_name}' with POC: {project_data['point_of_contact']}, "
                         f"Address: {project_data['address']}, {project_data['city']}, {project_data['state']}")
                flash("New project created successfully.", "success")

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            log_audit(f"{'update' if existing_project else 'create'}_project_error",
                     f"Error processing project {project_name}: {str(e)}")
            flash(f"An error occurred: {str(e)}", "error")

        return redirect(url_for('manage_projects'))

    # For GET request - list projects with pagination
    page = request.args.get('page', 1, type=int)
    per_page = 20
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
@staff_required
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
@staff_required
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
@login_required
def home():
    # Basic homepage with links to other parts of the application
    return render_template('Home.html')

@app.route('/add', methods=['POST'])
@staff_required
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
@admin_required
def update_factor():
    try:
        factor_id = request.form.get('Factor_ID')
        description = request.form.get('Description')
        labor_hours = request.form.get('LaborHours')

        if not factor_id:
            raise ValueError("Factor ID is required")

        factor = FactorCode.query.filter_by(factor_code=factor_id).first()
        if not factor:
            raise ValueError(f"Factor with ID {factor_id} not found")

        # Store old values for audit log
        old_values = {
            'description': factor.description,
            'labor_hours': factor.labor_hours
        }

        # Update the factor
        factor.description = description
        if labor_hours is not None:
            try:
                factor.labor_hours = float(labor_hours)
            except ValueError:
                raise ValueError("Labor Hours must be a valid number")

        # Prepare audit log message with changes
        changes = []
        if old_values['description'] != description:
            changes.append(f"description: '{old_values['description']}' → '{description}'")
        if old_values['labor_hours'] != factor.labor_hours:
            changes.append(f"labor hours: {old_values['labor_hours']} → {factor.labor_hours}")

        db.session.commit()

        # Log the changes
        if changes:
            log_audit('update_factor_code', 
                     f"Updated factor code '{factor_id}'. Changes: {', '.join(changes)}")

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
        log_audit('update_factor_code_error', f"Error updating factor {factor_id}: {str(ve)}")
        return jsonify({'success': False, 'message': str(ve)}), 400

    except Exception as e:
        db.session.rollback()
        log_audit('update_factor_code_error', f"Unexpected error updating factor {factor_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'An unexpected error occurred'}), 500

    finally:
        db.session.close()


# Add this new route to your Flask application
@app.route('/update-factor-code-item', methods=['POST'])
@staff_required
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
@admin_required
def manage_factors():
    if request.method == 'POST':
        factor_data = {
            'factor_code': request.form.get('Factor_ID'),
            'description': request.form.get('Description'),
            'labor_hours': request.form.get('LaborHours')
        }

        try:
            factor = FactorCode.query.filter_by(factor_code=factor_data['factor_code']).first()
            is_new = not factor

            if is_new:
                factor = FactorCode(
                    factor_code=factor_data['factor_code'],
                    description=factor_data['description'],
                    labor_hours=float(factor_data['labor_hours']) if factor_data['labor_hours'] else None
                )
                db.session.add(factor)
                log_audit('create_factor_code', 
                         f"Created new factor code '{factor_data['factor_code']}' "
                         f"with {factor_data['labor_hours']} labor hours")
            else:
                # Store old values for comparison
                old_data = {
                    'description': factor.description,
                    'labor_hours': factor.labor_hours
                }
                
                # Update values
                factor.description = factor_data['description']
                if factor_data['labor_hours'] is not None:
                    try:
                        factor.labor_hours = float(factor_data['labor_hours'])
                    except ValueError:
                        log_audit('factor_code_error', 
                                 f"Invalid labor hours value: {factor_data['labor_hours']}")
                        return jsonify({'success': False, 'message': 'Invalid labor hours value'}), 400

                # Log changes
                changes = []
                if old_data['description'] != factor.description:
                    changes.append(f"description: '{old_data['description']}' → '{factor.description}'")
                if old_data['labor_hours'] != factor.labor_hours:
                    changes.append(f"labor hours: {old_data['labor_hours']} → {factor.labor_hours}")
                
                if changes:
                    log_audit('update_factor_code', 
                             f"Updated factor code '{factor_data['factor_code']}'. "
                             f"Changes: {', '.join(changes)}")

            db.session.commit()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': True,
                    'message': f"Factor code {'added' if is_new else 'updated'} successfully",
                    'factor': {
                        'factor_code': factor.factor_code,
                        'description': factor.description,
                        'labor_hours': str(factor.labor_hours) if factor.labor_hours is not None else 'N/A',
                        'items': [],
                        'total_material_cost': '0.00'
                    }
                })

            return redirect(url_for('manage_factors'))

        except Exception as e:
            db.session.rollback()
            error_msg = f"Error managing factor code: {str(e)}"
            log_audit('factor_code_error', error_msg)
            return jsonify({'success': False, 'message': error_msg}), 500

    # GET request handling with pagination
    page = request.args.get('page', 1, type=int)
    query = request.args.get('query', '').strip()
    ITEMS_PER_PAGE = 10

    if query:
        factors_query = FactorCode.query.filter(FactorCode.factor_code.ilike(f'%{query}%'))
    else:
        factors_query = FactorCode.query

    total_items = factors_query.count()
    total_pages = ceil(total_items / ITEMS_PER_PAGE)
    factors = factors_query.offset((page - 1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()

    # Fetch additional data for display
    serialized_factors = []
    for factor in factors:
        items = FactorCodeItems.query.filter_by(factor_code=factor.factor_code).all()
        total_cost = sum(
            (item.inventory_item.cost or 0) * item.quantity
            for item in items
            if item.inventory_item is not None
        )
        
        serialized_factors.append({
            'factor_code': factor.factor_code,
            'description': factor.description,
            'labor_hours': str(factor.labor_hours) if factor.labor_hours is not None else 'N/A',
            'items': [{
                'part_number': item.inventory_item.part_number,
                'description': item.inventory_item.description,
                'quantity': str(item.quantity),
                'cost': str(item.inventory_item.cost * item.quantity if item.inventory_item.cost else 0)
            } for item in items if item.inventory_item],
            'total_material_cost': str(total_cost)
        })

    return render_template(
        'ManageFactors.html',
        factors=serialized_factors,
        current_page=page,
        total_pages=total_pages,
        query=query
    )

@app.route('/delete_bid/<bid_id>', methods=['POST'])
@staff_required
def delete_bid(bid_id):
    try:
        # First, check for associated jobs
        job = Job.query.filter_by(bid_id=bid_id).first()
        
        if job:
            # If a job exists, we need to handle it
            # Option 1: Prevent deletion
            flash(f'Cannot delete bid {bid_id}. A job is associated with this bid.', 'error')
            return redirect(url_for('bid_management'))
            
            # Option 2: If you want to delete the job as well, uncomment these lines:
            # db.session.delete(job)

        # Fetch the bid
        bid = Bid.query.filter_by(bid_id=bid_id).first()
        
        if not bid:
            flash(f'Bid {bid_id} not found.', 'error')
            return redirect(url_for('bid_management'))

        # Delete related records
        with db.session.no_autoflush:
            # Delete SubBidItems first
            SubBidItem.query.filter(
                SubBidItem.sub_bid_id.in_(
                    db.session.query(SubBid.sub_bid_id)
                    .filter(SubBid.bid_id == bid_id)
                )
            ).delete(synchronize_session=False)

            # Delete SubBids
            SubBid.query.filter_by(bid_id=bid_id).delete(synchronize_session=False)

            # Delete BidFactorCodeItems
            BidFactorCodeItems.query.filter_by(bid_id=bid_id).delete(synchronize_session=False)

            # Delete associated proposal data
            proposal = Proposal.query.filter_by(bid_id=bid_id).first()
            if proposal:
                ProposalComponentLine.query.filter(
                    ProposalComponentLine.component_id.in_(
                        ProposalComponent.query
                        .with_entities(ProposalComponent.id)
                        .filter_by(proposal_id=proposal.id)
                    )
                ).delete(synchronize_session=False)
                
                ProposalComponent.query.filter_by(proposal_id=proposal.id).delete(synchronize_session=False)
                ProposalAmount.query.filter_by(proposal_id=proposal.id).delete(synchronize_session=False)
                ProposalOption.query.filter_by(proposal_id=proposal.id).delete(synchronize_session=False)
                
                db.session.delete(proposal)

            # Delete BidAdjustments
            BidAdjustment.query.filter_by(bid_id=bid_id).delete(synchronize_session=False)

            # Finally, delete the bid
            db.session.delete(bid)

        # Commit the transaction
        db.session.commit()

        # Log the deletion
        log_audit('delete_bid', f"Deleted bid {bid_id}")

        flash('Bid deleted successfully.', 'success')
        return redirect(url_for('bid_management'))

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting bid {bid_id}: {str(e)}", exc_info=True)
        log_audit('delete_bid_error', f"Error deleting bid {bid_id}: {str(e)}")
        flash(f'Error deleting bid: {str(e)}', 'error')
        return redirect(url_for('bid_management'))
    
# 6. Enhanced inventory management route with audit logging
@app.route('/inventory/manage', methods=['GET', 'POST'])
@admin_required
def manage_inventory():
    if request.method == 'POST':
        inventory_data = {
            'part_num': request.form.get('PartNum'),
            'description': request.form.get('Description'),
            'cost': request.form.get('Cost'),
            'factor_code': request.form.get('FactorCode')
        }

        try:
            # Validate and convert cost to float
            try:
                inventory_data['cost'] = float(inventory_data['cost']) if inventory_data['cost'] else 0.0
            except ValueError:
                inventory_data['cost'] = 0.0

            # Ensure factor code exists
            factor = FactorCode.query.filter_by(factor_code=inventory_data['factor_code']).first()
            if not factor:
                log_audit('inventory_error', 
                         f"Attempted to use non-existent factor code: {inventory_data['factor_code']}")
                return jsonify({"error": "Factor code not found."}), 404

            # Check if updating or creating new item
            inventory_item = Inventory.query.filter_by(part_number=inventory_data['part_num']).first()
            
            if inventory_item:
                # Store old values for comparison
                old_data = {
                    'description': inventory_item.description,
                    'cost': inventory_item.cost,
                    'factor_code': inventory_item.factor_code
                }
                
                # Update existing item
                inventory_item.description = inventory_data['description']
                inventory_item.cost = inventory_data['cost']
                inventory_item.factor_code = inventory_data['factor_code']
                
                # Log changes
                changes = []
                for field, old_value in old_data.items():
                    new_value = inventory_data[field if field != 'part_num' else 'part_number']
                    if old_value != new_value:
                        changes.append(f"{field}: '{old_value}' → '{new_value}'")
                
                if changes:
                    log_audit('update_inventory', 
                             f"Updated inventory item '{inventory_data['part_num']}'. "
                             f"Changes: {', '.join(changes)}")
            else:
                # Create new item
                new_item = Inventory(
                    part_number=inventory_data['part_num'],
                    description=inventory_data['description'],
                    cost=inventory_data['cost'],
                    factor_code=inventory_data['factor_code']
                )
                db.session.add(new_item)
                
                log_audit('create_inventory', 
                         f"Created new inventory item '{inventory_data['part_num']}' "
                         f"with cost {inventory_data['cost']}")

            db.session.commit()
            return redirect(url_for('manage_inventory'))

        except Exception as e:
            db.session.rollback()
            error_msg = f"Error managing inventory item {inventory_data['part_num']}: {str(e)}"
            log_audit('inventory_error', error_msg)
            app.logger.error(error_msg)
            return jsonify({"error": str(e)}), 500

    # For GET request
    # Pagination and search logic remains the same...
    page = request.args.get('page', 1, type=int)
    ITEMS_PER_PAGE = 50
    
    part_number_search = request.args.get('part_number_search', '').strip()
    description_search = request.args.get('description_search', '').strip()

    if part_number_search:
        query = Inventory.query.filter(Inventory.part_number.ilike(f"%{part_number_search}%"))
    elif description_search:
        query = Inventory.query.filter(Inventory.description.ilike(f"%{description_search}%"))
    else:
        query = Inventory.query

    total_items = query.count()
    inventory_items = query.offset((page - 1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()
    total_pages = ceil(total_items / ITEMS_PER_PAGE)
    factors = FactorCode.query.all()

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
@admin_required
def update_inventory():
    try:
        part_num = request.form.get('PartNum')
        description = request.form.get('Description')
        cost = request.form.get('Cost')
        factor_code = request.form.get('FactorCode')

        try:
            cost = float(cost) if cost else 0.0
        except ValueError:
            return jsonify({"success": False, "message": "Invalid cost value"}), 400

        inventory_item = Inventory.query.filter_by(part_number=part_num).first()
        if inventory_item:
            old_data = {
                'description': inventory_item.description,
                'cost': inventory_item.cost,
                'factor_code': inventory_item.factor_code
            }
            
            inventory_item.description = description
            inventory_item.cost = cost
            inventory_item.factor_code = factor_code
            
            # Log the changes
            changes = []
            if old_data['description'] != description:
                changes.append(f"description: '{old_data['description']}' → '{description}'")
            if old_data['cost'] != cost:
                changes.append(f"cost: {old_data['cost']} → {cost}")
            if old_data['factor_code'] != factor_code:
                changes.append(f"factor code: {old_data['factor_code']} → {factor_code}")
                
            log_audit('update_inventory', 
                     f"Updated inventory item '{part_num}'. Changes: {', '.join(changes)}")
            
            db.session.commit()
            return jsonify({"success": True, "message": "Inventory item updated successfully"})
        else:
            return jsonify({"success": False, "message": "Inventory item not found"}), 404
            
    except Exception as e:
        db.session.rollback()
        log_audit('update_inventory_error', f"Error updating inventory item {part_num}: {str(e)}")
        return jsonify({'success': False, 'message': f'Error occurred: {str(e)}'}), 500

@app.route('/inventory/check-delete', methods=['POST'])
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
def get_inventory():
    inventory_data = cache.get('inventory')
    if inventory_data is None:
        update_inventory_cache()
        inventory_data = cache.get('inventory')
    return jsonify(inventory_data)


@app.route('/factors/add_item', methods=['POST'])
@admin_required
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
@staff_required
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
@staff_required
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
@staff_required
def get_factors():
    factor_data = cache.get('factor_codes')
    if factor_data is None:
        update_factor_codes_cache()
        factor_data = cache.get('factor_codes')
    return jsonify(factor_data)

@app.route('/add-update-bid', methods=['POST'])
@staff_required
def add_update_bid():
    bid_id = request.form.get('bidID')
    project_name = request.form.get('projectName')
    customer_name = request.form.get('customerName')
    tax_rate_str = request.form.get('taxRate', '').strip()
    urgency = request.form.get('urgency')  # Get the urgency value
    engineer_name = request.form.get('engineerName')
    architect_name = request.form.get('architectName')
    point_of_contact = request.form.get('pointOfContact')

    # Gracefully handle empty or invalid tax rate
    if not tax_rate_str:
        tax_rate = 0.0
    else:
        try:
            tax_rate = float(tax_rate_str)
        except ValueError:
            tax_rate = 0.0

    # Check if project exists
    project = Project.query.filter_by(project_name=project_name).first()
    if not project:
        return jsonify({
            "success": False,
            "message": "Selected project not found.",
            "missing_entity": "project",
            "project_name": project_name
        })

    # Check if customer exists
    customer = Customer.query.filter_by(customer_name=customer_name).first()
    if not customer:
        return jsonify({
            "success": False,
            "message": "Selected customer not found.",
            "missing_entity": "customer",
            "customer_name": customer_name
        })

    existing_bid = Bid.query.filter_by(bid_id=bid_id).first()
    try:
        if existing_bid:
            existing_bid.project_name = project_name
            existing_bid.customer_name = customer_name
            existing_bid.engineer_name = engineer_name
            existing_bid.architect_name = architect_name
            existing_bid.point_of_contact = point_of_contact
            existing_bid.local_sales_tax = tax_rate
            existing_bid.urgency = urgency  # Set urgency field
            message = "Bid updated successfully."
        else:
            new_bid = Bid(
                bid_id=bid_id,
                project_name=project_name,
                description=request.form.get('description'),
                customer_name=customer_name,
                bid_date=datetime.now().date(),
                local_sales_tax=tax_rate,
                point_of_contact=point_of_contact,
                engineer_name=engineer_name,
                architect_name=architect_name,
                urgency=urgency  # Set urgency field
            )
            db.session.add(new_bid)
            message = "New bid created successfully."

        db.session.commit()
        return jsonify({"success": True, "message": message, "bid_id": bid_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"An error occurred: {str(e)}"})


@app.route('/add-update-customer', methods=['POST'])
@staff_required
def add_update_customer():
    data = request.form
    customer_name = data.get('customer_name')
    
    if not customer_name:
        return jsonify({"success": False, "message": "Customer name is required"})

    existing_customer = Customer.query.get(customer_name)
    if existing_customer:
        # Update existing customer fields if needed
        existing_customer.customer_address = data.get('customer_address')
        existing_customer.customer_state = data.get('customer_state')
        existing_customer.customer_city = data.get('customer_city')
        existing_customer.customer_zip = data.get('customer_zip')
        message = "Customer updated successfully."
    else:
        # Create new customer
        new_customer = Customer(
            customer_name=customer_name,
            customer_address=data.get('customer_address'),
            customer_state=data.get('customer_state'),
            customer_city=data.get('customer_city'),
            customer_zip=data.get('customer_zip')
        )
        db.session.add(new_customer)
        message = "New customer created successfully."

    try:
        db.session.commit()
        return jsonify({"success": True, "message": message})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})



@app.route('/get-factor-code-labor-hours/<factor_code>', methods=['GET'])
@staff_required
def get_factor_code_labor_hours(factor_code):
    factor = FactorCode.query.filter_by(factor_code=factor_code).first()
    if factor:
        return jsonify({'labor_hours': factor.labor_hours})
    else:
        return jsonify({'error': 'Factor code not found'}), 404
    
@app.route('/save-sub-bid', methods=['POST'])
@staff_required
def save_sub_bid():
    try:
        app.logger.info("Received save-sub-bid request")
        sub_bid_data = request.json
        if not sub_bid_data:
            error_msg = "No sub-bid data received"
            log_audit('sub_bid_error', error_msg)
            raise BadRequest(error_msg)

        bid_id = sub_bid_data.get('bid_id')
        sub_bid_id = sub_bid_data.get('sub_bid_id')
        
        if not bid_id:
            error_msg = "Bid ID is required"
            log_audit('sub_bid_error', error_msg)
            raise BadRequest(error_msg)

        # Fetch or create sub-bid
        is_new = sub_bid_id is None
        if sub_bid_id:
            sub_bid = SubBid.query.get(sub_bid_id)
            if not sub_bid:
                error_msg = f"Sub-bid with ID {sub_bid_id} not found"
                log_audit('sub_bid_error', error_msg)
                raise BadRequest(error_msg)
        else:
            sub_bid = SubBid(bid_id=bid_id)
            db.session.add(sub_bid)

        # Update sub-bid details
        sub_bid.name = sub_bid_data.get('name')
        sub_bid.category = sub_bid_data.get('category')
        sub_bid.total_cost = sub_bid_data.get('total_cost', 0)
        sub_bid.labor_hours = sub_bid_data.get('labor_hours', 0)

        # Handle sub-bid items
        SubBidItem.query.filter_by(sub_bid_id=sub_bid.sub_bid_id).delete()
        
        for item_data in sub_bid_data.get('items', []):
            new_item = SubBidItem(
                sub_bid_id=sub_bid.sub_bid_id,
                part_number=item_data.get('part_number'),
                description=item_data.get('description'),
                additional_description=item_data.get('additional_description', ''),  # Add this line
                factor_code=item_data.get('factor_code'),
                quantity=float(item_data.get('quantity', 0)),
                cost=float(item_data.get('cost', 0)),
                labor_hours=float(item_data.get('labor_hours', 0)),
                line_ext_cost=float(item_data.get('line_ext_cost', 0))
            )
            db.session.add(new_item)

        db.session.commit()
        
        return jsonify({
            "success": True, 
            "sub_bid_id": sub_bid.sub_bid_id,
            "message": f"Sub-bid {'created' if is_new else 'updated'} successfully"
        })

    except Exception as e:
        db.session.rollback()
        error_msg = f"Error saving sub-bid: {str(e)}"
        log_audit('sub_bid_error', error_msg)
        return jsonify({
            "success": False, 
            "error": error_msg
        }), 500
    
    
@app.route('/save-bid', methods=['POST'])
@staff_required
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
        
        # Handle bid_amount specifically
        if 'bid_amount' in heading_info:
            try:
                bid_amount = float(heading_info['bid_amount'])
                bid.bid_amount = bid_amount
                app.logger.info(f"Set bid_amount to: {bid_amount}")
            except (ValueError, TypeError):
                app.logger.warning(f"Invalid bid_amount value: {heading_info['bid_amount']}")
                # Keep existing value or default if conversion fails
        
        # Handle comments field
        if 'comments' in heading_info:
            bid.comments = heading_info['comments']
            app.logger.info(f"Set comments to: {heading_info['comments']}")
        
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
@staff_required
def api_proposals():
    if request.method == 'GET':
        """
        Return only the LATEST revision per bid_id.
        In other words, for each distinct bid_id, we get the row
        with the maximum revision_number.
        """
        # 1) Build a subquery that finds the (bid_id, max_revision)
        subq = db.session.query(
            Proposal.bid_id,
            db.func.max(Proposal.revision_number).label('max_rev')
        ).group_by(Proposal.bid_id).subquery()

        # 2) Join the main table with that subquery so we only get the “latest” row
        # for each bid_id
        latest_proposals = (
            db.session.query(Proposal)
            .join(
                subq,
                (Proposal.bid_id == subq.c.bid_id)
                & (Proposal.revision_number == subq.c.max_rev)
            )
            .order_by(Proposal.created_at.desc())
        )

        # 3) Prepare the response data
        proposals_data = []
        for proposal in latest_proposals:
            proposals_data.append({
                'bid_id': proposal.bid_id,
                'project_name': proposal.project_name,
                'customer_name': proposal.customer_name,
                'revision_number': proposal.revision_number,
            })

        return jsonify({'proposals': proposals_data}), 200
    elif request.method == 'POST':
        """
        Create a brand-new proposal revision by copying the existing
        highest revision. If none exists, we start with revision_number=1.
        """
        try:
            data = request.get_json()
            bid_id = data.get('bid_id')
            if not bid_id:
                return jsonify({'success': False, 'message': 'Missing bid_id'}), 400

            # Check if the Bid exists
            bid = Bid.query.filter_by(bid_id=bid_id).first()
            if not bid:
                return jsonify({'success': False, 'message': 'Bid not found'}), 404

            # Find the LATEST existing proposal for this bid_id
            old_proposal = (
                Proposal.query
                .filter_by(bid_id=bid_id)
                .order_by(Proposal.revision_number.desc())
                .first()
            )

            if old_proposal:
                new_revision = old_proposal.revision_number + 1
            else:
                new_revision = 1

            # Create the new proposal row by copying from old_proposal or from scratch
            new_proposal = Proposal(
                bid_id=bid_id,
                customer_name=old_proposal.customer_name if old_proposal else bid.customer_name,
                project_name=old_proposal.project_name if old_proposal else bid.project_name,
                total_budget=old_proposal.total_budget if old_proposal else bid.total_budget,
                revision_number=new_revision,
                # copy heading fields if old_proposal exists
                point_of_contact=(old_proposal.point_of_contact if old_proposal else ''),
                architect_name=(old_proposal.architect_name if old_proposal else ''),
                architect_specifications=(old_proposal.architect_specifications if old_proposal else ''),
                architect_dated=(old_proposal.architect_dated if old_proposal else ''),
                architect_sheets=(old_proposal.architect_sheets if old_proposal else ''),
                engineer_name=(old_proposal.engineer_name if old_proposal else ''),
                engineer_specifications=(old_proposal.engineer_specifications if old_proposal else ''),
                engineer_dated=(old_proposal.engineer_dated if old_proposal else ''),
                engineer_sheets=(old_proposal.engineer_sheets if old_proposal else ''),
                special_notes=(old_proposal.special_notes if old_proposal else '[]'),
                terms_conditions=(old_proposal.terms_conditions if old_proposal else '[]'),
                exclusions=(old_proposal.exclusions if old_proposal else None),
            )
            db.session.add(new_proposal)
            db.session.flush()  # so that new_proposal.id is assigned

            # If you want to copy the "components" from the old_proposal:
            if old_proposal:
                for comp in old_proposal.components:
                    new_comp = ProposalComponent(
                        proposal_id=new_proposal.id,
                        type=comp.type,
                        name=comp.name,
                    )
                    db.session.add(new_comp)
                    db.session.flush()

                    # copy lines
                    for line in comp.lines:
                        new_line = ProposalComponentLine(
                            component_id=new_comp.id,
                            name=line.name,
                            value=line.value
                        )
                        db.session.add(new_line)

                # If you want to copy the “options” from old_proposal:
                for opt in old_proposal.options:
                    new_opt = ProposalOption(
                        proposal_id=new_proposal.id,
                        description=opt.description,
                        amount=opt.amount
                    )
                    db.session.add(new_opt)

            db.session.commit()

            return jsonify({
                'success': True,
                'message': f'Created new revision {new_revision} for bid {bid_id}'
            }), 201

        except SQLAlchemyError as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'Database error', 'error': str(e)}), 500
        except Exception as e:
            return jsonify({'success': False, 'message': 'An error occurred', 'error': str(e)}), 500


@app.route('/api/proposal/<bid_id>', methods=['GET'])
@staff_required
def get_proposal_data(bid_id):
    # 1) read the "revision" param from the URL
    revision = request.args.get('revision', type=int)
    
    # 2) load that specific revision if given, else fallback to LATEST
    if revision is not None:
        proposal = Proposal.query.filter_by(bid_id=bid_id, revision_number=revision).first_or_404()
    else:
        proposal = Proposal.query.filter_by(bid_id=bid_id).order_by(Proposal.revision_number.desc()).first_or_404()

    # 3) if not found -> 404 (the .first_or_404() handles that)
    # 4) build your JSON just like before...
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

    return jsonify(proposal_data), 200




@app.route('/create-proposal')
@staff_required
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
@staff_required
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

def log_audit(action, details, user_id=None):
    """Helper function to create audit log entries"""
    try:
        if not user_id and current_user.is_authenticated:
            user_id = current_user.id
            
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            details=details,
        )
        db.session.add(audit_entry)
        db.session.commit()
    except Exception as e:
        app.logger.error(f"Error logging audit: {str(e)}")
        db.session.rollback()


@app.route('/save-project', methods=['POST'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
def view_proposal(bid_id):
    bid = Bid.query.get_or_404(bid_id)
    return render_template('view_proposal.html', proposal=bid)

# New route to generate PDF
@app.route('/generate-proposal-pdf/<bid_id>', methods=['GET'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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


@app.route('/api/create-job', methods=['POST'])
@admin_required
def create_job():
    try:
        data = request.get_json()
        bid_id = data.get('bid_id')
        job_id = data.get('job_id')

        # Check if job already exists
        existing_job = Job.query.get(job_id)
        if existing_job:
            return jsonify({
                'success': False,
                'message': 'Job already exists with this ID'
            }), 400

        # Create new job record
        new_job = Job(
            job_id=job_id,
            bid_id=bid_id
        )
        db.session.add(new_job)
        
        # Copy items from landscape to maintenance
        # 1. Fetch all landscape items for this bid
        landscape_items = BidFactorCodeItems.query.filter_by(bid_id=bid_id, category='landscape').all()

        # 2. Clear out any existing maintenance items to ensure a clean mirror
        BidFactorCodeItems.query.filter_by(bid_id=bid_id, category='maintenance').delete()

        # 3. Insert duplicated items into the maintenance category
        for item in landscape_items:
            new_item = BidFactorCodeItems(
                bid_id=item.bid_id,
                category='maintenance',
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

        db.session.commit()

        log_audit('create_job', f"Created new job {job_id} from bid {bid_id} and mirrored landscape items to maintenance")
        
        return jsonify({
            'success': True,
            'message': f'Job created successfully with ID: {job_id}'
        })

    except Exception as e:
        db.session.rollback()
        log_audit('create_job_error', f"Error creating job from bid {bid_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500



@app.route('/api/job/<job_id>')
@staff_required
def get_job(job_id):
    try:
        app.logger.info(f"Fetching job with ID: {job_id}")
        job = Job.query.get(job_id)
        
        if not job:
            app.logger.warning(f"Job not found with ID: {job_id}")
            return jsonify({
                'success': False,
                'message': f'Job {job_id} not found'
            }), 404

        bid = Bid.query.get(job.bid_id)
        if not bid:
            app.logger.warning(f"Associated bid not found for job ID: {job_id}")
            return jsonify({
                'success': False,
                'message': f'Associated bid not found for job {job_id}'
            }), 404

        project = Project.query.filter_by(project_name=bid.project_name).first()

        job_data = {
            'success': True,
            'job': {
                'job_number': job.job_id,
                'project_name': bid.project_name,
                'customer_name': bid.customer_name,
                'project_address': project.project_address if project else bid.project_address,
                'created_at': job.created_at.isoformat() if job.created_at else None,
                'status': job.status
            }
        }
        
        app.logger.info(f"Successfully fetched job data: {job_data}")
        return jsonify(job_data)

    except Exception as e:
        app.logger.error(f"Error fetching job {job_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error fetching job: {str(e)}'
        }), 500

@app.route('/api/purchase-orders/next-number/<job_id>/<category>')
@staff_required
def get_next_po_number(job_id, category):
    try:
        # Get category letter
        category_letter = category[0].upper()
        
        # Find the highest PO number for this job and category using SQL for better performance
        last_po = db.session.query(
            PurchaseOrder.po_number
        ).filter(
            PurchaseOrder.job_id == job_id,
            PurchaseOrder.po_number.like(f'{job_id}-{category_letter}-%')
        ).order_by(
            # Use a custom ordering that properly handles numeric sequences
            db.func.cast(
                db.func.substring(
                    PurchaseOrder.po_number,
                    db.func.length(job_id) + 4  # Skip job_id, hyphen, category letter, hyphen
                ),
                db.Integer
            ).desc()
        ).first()
        
        if last_po:
            # Extract the numeric portion and increment
            try:
                last_number = int(last_po.po_number.split('-')[-1])
                next_number = last_number + 1
            except (ValueError, IndexError):
                # If there's any issue parsing the last number, start from 1
                app.logger.warning(f"Error parsing last PO number: {last_po.po_number}")
                next_number = 1
        else:
            next_number = 1
            
        next_po_number = f"{job_id}-{category_letter}-{next_number}"
        
        app.logger.info(f"Generated next PO number: {next_po_number}")
        return jsonify({
            'success': True,
            'next_po_number': next_po_number
        })
        
    except Exception as e:
        app.logger.error(f"Error generating next PO number: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
    
@app.route('/api/purchase-orders/<po_number>', methods=['DELETE'])
@admin_required
def delete_purchase_order(po_number):
    try:
        po = PurchaseOrder.query.get_or_404(po_number)
        db.session.delete(po)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Purchase order {po_number} deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# Add this helper route for debugging
@app.route('/api/debug/job/<job_id>')
@staff_required
def debug_job(job_id):
    try:
        # Query the job
        job = Job.query.get(job_id)
        if not job:
            return jsonify({'error': 'Job not found'})
            
        # Get related bid
        bid = Bid.query.get(job.bid_id)
        
        # Get purchase orders
        pos = PurchaseOrder.query.filter_by(job_id=job_id).all()
        
        return jsonify({
            'job': {
                'job_id': job.job_id,
                'bid_id': job.bid_id,
                'created_at': job.created_at.isoformat() if job.created_at else None,
                'status': job.status
            },
            'bid': {
                'bid_id': bid.bid_id if bid else None,
                'project_name': bid.project_name if bid else None,
                'customer_name': bid.customer_name if bid else None
            } if bid else None,
            'purchase_orders': [{
                'po_number': po.po_number,
                'vendor': po.vendor,
                'amount': po.amount,
                'status': po.status
            } for po in pos]
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/create-purchase-order/<po_number>')
@staff_required
def create_purchase_order(po_number):
    try:
        # Parse job_id, category from PO number (format: 00001-L-1)
        parts = po_number.split('-')
        if len(parts) != 3:
            flash('Invalid PO number format', 'error')
            return redirect(url_for('Manage_Purchase_Orders'))

        job_id, category_code, sequence = parts

        # Map category code to full category name
        category_map = {
            'D': 'drains',
            'I': 'irrigation',
            'L': 'landscape',
            'M': 'maintenance',
            'S': 'subcontract'
        }
        category = category_map.get(category_code)
        if not category:
            flash('Invalid category code', 'error')
            return redirect(url_for('Manage_Purchase_Orders'))

        # Get job and associated bid
        job = Job.query.get_or_404(job_id)
        bid = job.bid
        if not bid:
            flash('Associated bid not found', 'error')
            return redirect(url_for('Manage_Purchase_Orders'))

        # Get bid items for this category
        bid_items = BidFactorCodeItems.query.filter_by(
            bid_id=bid.bid_id,
            category=category
        ).all()

        # Calculate bought quantities for each bid item
        bought_quantities = {}
        for item in bid_items:
            completed_pos = PurchaseOrder.query.filter_by(
                job_id=job_id,
                category=category,
                status='completed'
            ).all()

            total_bought = 0
            for cpo in completed_pos:
                po_items = PurchaseOrderItem.query.filter_by(
                    po_number=cpo.po_number,
                    part_number=item.part_number
                ).all()
                total_bought += sum(poi.quantity for poi in po_items)

            bought_quantities[item.part_number] = total_bought

        # Retrieve the PO if it exists
        po = PurchaseOrder.query.get(po_number)
        
        # If PO doesn't exist, create it in 'in_progress' status so comments and items can be added
        if not po:
            po = PurchaseOrder(
                po_number=po_number,
                job_id=job_id,
                category=category,
                status='in_progress',
                date_created=datetime.utcnow()
            )
            db.session.add(po)
            db.session.commit()

        # Initialize a dict to store previously saved info (if any)
        saved_items = {}
        existing_items = PurchaseOrderItem.query.filter_by(po_number=po_number).all()
        for ei in existing_items:
            vendor_id = ei.vendor_id
            vendor_name = ''
            if vendor_id:
                vendor = Vendor.query.get(vendor_id)
                vendor_name = vendor.name if vendor else ''
            saved_items[ei.part_number] = {
                'order_qty': ei.quantity,
                'order_cost': ei.unit_cost,
                'vendor_id': vendor_id,
                'vendor_name': vendor_name
            }

        # Calculate budget and actual amounts
        budget_amount = getattr(bid, f'{category}_total', 0) or 0
        actual_amount = sum([ppo.amount for ppo in job.purchase_orders if ppo.category == category and ppo.status == 'completed']) or 0

        # Calculate percent complete
        percent_complete = (actual_amount / budget_amount * 100) if budget_amount > 0 else 0

        return render_template('create_purchase_order.html',
            now=datetime.now(),
            po_number=po_number,
            job=job,
            bid=bid,
            category=category,
            bid_items=bid_items,
            bought_quantities=bought_quantities,
            budget_amount=budget_amount,
            actual_amount=actual_amount,
            percent_complete=percent_complete,
            saved_items=saved_items
        )

    except Exception as e:
        current_app.logger.error(f"Error creating purchase order: {str(e)}")
        flash('An error occurred while creating the purchase order', 'error')
        return redirect(url_for('Manage_Purchase_Orders'))



@app.route('/search-vendors')
@staff_required
def search_vendors():
    query = request.args.get('query', '').strip()
    app.logger.info(f"Searching vendors with query: {query}")

    try:
        # Use ILIKE for case-insensitive partial matching
        vendors = Vendor.query.filter(
            db.or_(
                Vendor.name.ilike(f'%{query}%'),
                Vendor.company.ilike(f'%{query}%'),
                Vendor.phone_number.ilike(f'%{query}%')  # Added phone number search
            )
        ).limit(10).all()

        app.logger.info(f"Found {len(vendors)} vendors")
        
        results = [{
            'id': vendor.id,
            'name': vendor.name,
            'company': vendor.company,
            'phone_number': vendor.phone_number
        } for vendor in vendors]

        app.logger.debug(f"Search results: {results}")
        return jsonify(results)

    except Exception as e:
        app.logger.error(f"Error searching vendors: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug/vendors')
@staff_required
def debug_vendors():
    try:
        vendors = Vendor.query.limit(10).all()
        return jsonify([{
            'id': v.id,
            'name': v.name,
            'company': v.company,
            'phone_number': v.phone_number
        } for v in vendors])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/purchase-order/<po_number>/comments', methods=['GET', 'POST'])
@staff_required
def handle_po_comments(po_number):
    if request.method == 'GET':
        try:
            comments = Comment.query.filter_by(po_number=po_number)\
                .order_by(Comment.created_at.desc()).all()
            
            return jsonify({
                'success': True,
                'comments': [{
                    'id': comment.id,
                    'user': comment.user.username,
                    'text': comment.text,
                    'created_at': comment.created_at.isoformat()
                } for comment in comments]
            })

        except Exception as e:
            app.logger.error(f"Error fetching PO comments: {str(e)}")
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500

    elif request.method == 'POST':
        try:
            data = request.json
            text = data.get('text')
            
            if not text:
                return jsonify({
                    'success': False,
                    'message': 'Comment text is required'
                }), 400
                
            comment = Comment(
                po_number=po_number,
                user_id=current_user.id,
                text=text
            )
            db.session.add(comment)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'comment': {
                    'id': comment.id,
                    'user': current_user.username,
                    'text': comment.text,
                    'created_at': comment.created_at.isoformat()
                }
            })

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error adding comment: {str(e)}")
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500


@app.route('/api/purchase-order/<po_number>/history')
@staff_required
def get_purchase_order_history(po_number):
    try:
        # Get audit logs related to this PO
        audit_logs = AuditLog.query.filter(
            AuditLog.details.like(f'%{po_number}%')
        ).order_by(AuditLog.timestamp.desc()).all()

        history = [{
            'timestamp': log.timestamp.isoformat(),
            'user': log.user.username if log.user else 'System',
            'action': log.action,
            'details': log.details
        } for log in audit_logs]

        return jsonify({
            'success': True,
            'history': history
        })

    except Exception as e:
        app.logger.error(f"Error fetching PO history: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/purchase-order/<po_number>/comments', methods=['GET', 'POST'])
@staff_required
def handle_purchase_order_comments(po_number):
    if request.method == 'GET':
        try:
            comments = Comment.query.filter_by(
                po_number=po_number
            ).order_by(Comment.created_at.desc()).all()

            return jsonify({
                'success': True,
                'comments': [{
                    'id': comment.id,
                    'user': comment.user.username,
                    'text': comment.text,
                    'created_at': comment.created_at.isoformat()
                } for comment in comments]
            })

        except Exception as e:
            app.logger.error(f"Error fetching PO comments: {str(e)}")
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500

    elif request.method == 'POST':
        try:
            data = request.json
            comment = Comment(
                po_number=po_number,
                user_id=current_user.id,
                text=data.get('text')
            )
            db.session.add(comment)
            db.session.commit()

            return jsonify({
                'success': True,
                'comment': {
                    'id': comment.id,
                    'user': current_user.username,
                    'text': comment.text,
                    'created_at': comment.created_at.isoformat()
                }
            })

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error adding comment: {str(e)}")
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500

@app.route('/view-purchase-order/<po_number>')
@staff_required
def view_purchase_order(po_number):
    # This will be implemented next
    return "View Purchase Order page coming soon"

@app.route('/insert', methods=['POST'])
@staff_required
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)