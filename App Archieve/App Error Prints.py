from flask import Flask, request, jsonify, render_template, session, send_file, redirect, url_for
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from traceback import format_exc


app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:Tower99@localhost/flask_bids'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

class Customer(db.Model):
    customer_name = db.Column(db.String(255), primary_key=True)
    customer_address = db.Column(db.String(255))
    customer_state = db.Column(db.String(255))
    customer_city = db.Column(db.String(255))
    customer_zip = db.Column(db.String(255))
    bids = db.relationship('Bid', backref='customer', lazy=True)

class FactorCode(db.Model):
    factor_code = db.Column(db.String(255), primary_key=True)
    description = db.Column(db.String(255))
    labor_hours = db.Column(db.Integer)
    inventory_items = db.relationship('Inventory', backref='associated_factor', lazy=True)

class Inventory(db.Model):
    part_number = db.Column(db.String(255), primary_key=True)
    description = db.Column(db.String(255))
    cost = db.Column(db.Numeric)
    factor_code = db.Column(db.String(255), db.ForeignKey('factor_code.factor_code'))
    associated_factor = db.relationship('FactorCode', backref='inventory_items')

class SubBid(db.Model):
    sub_bid_id = db.Column(db.Integer, primary_key=True)
    sub_bid_name = db.Column(db.String(255))
    cost = db.Column(db.Numeric)
    labor_hours = db.Column(db.Integer)
    bids = db.relationship('Bid', backref='sub_bid', lazy=True)

class Bid(db.Model):
    bid_id = db.Column(db.Integer, primary_key=True)
    bid_date = db.Column(db.Date)
    customer_name = db.Column(db.String(255), db.ForeignKey('customer.customer_name'))
    drains_labor_rate = db.Column(db.Numeric)
    irrigation_labor_rate = db.Column(db.Numeric)
    landscape_labor_rate = db.Column(db.Numeric)
    maintenance_labor_rate = db.Column(db.Numeric)
    local_sales_tax = db.Column(db.Numeric)
    project_name = db.Column(db.String(255))
    project_address = db.Column(db.String(255))
    project_state = db.Column(db.String(255))
    project_city = db.Column(db.String(255))
    project_zip = db.Column(db.String(255))
    part_number = db.Column(db.String(255), db.ForeignKey('inventory.part_number'))
    sub_bid_number = db.Column(db.Integer, db.ForeignKey('sub_bid.sub_bid_id'))

@app.route('/inventory/manage', methods=['GET', 'POST'])
def manage_inventory():
    try:
        if request.method == 'POST':
            part_num = request.form.get('PartNum')
            description = request.form.get('Description')
            cost = request.form.get('Cost')
            factor_code = request.form.get('FactorCode')

            factor = FactorCode.query.filter_by(factor_code=factor_code).first()
            if not factor:
                raise ValueError("Error: Factor code not found.")

            inventory_item = Inventory.query.filter_by(part_number=part_num).first()
            if inventory_item:
                inventory_item.description = description
                inventory_item.cost = cost
                inventory_item.factor_code = factor_code
            else:
                new_item = Inventory(
                    part_number=part_num, 
                    description=description, 
                    cost=cost, 
                    factor_code=factor_code
                )
                db.session.add(new_item)
            db.session.commit()
            return redirect(url_for('manage_inventory'))

        inventory_items = Inventory.query.all()
        factors = FactorCode.query.all()
        return render_template('ManageInventory.html', inventory=inventory_items, factors=factors)
    except Exception as e:
        app.logger.error(f"Unhandled exception: {e}\n{format_exc()}")
        return jsonify(error=f"An error occurred: {str(e)}"), 500

@app.route('/bid-management', methods=['GET', 'POST'])
def bid_management():
    try:
        if request.method == 'POST':
            bid_name = request.form.get('bidName')
            create_new_bid = request.form.get('createNewBid') == 'on'

            if create_new_bid:
                existing_bid = Bid.query.filter_by(name=bid_name).first()
                if existing_bid is None:
                    new_bid = Bid(name=bid_name)
                    db.session.add(new_bid)
                    db.session.commit()
                    return redirect(url_for('bid_management', bid_id=new_bid.id))
                else:
                    return "A bid with this name already exists.", 400
            else:
                selected_bid = Bid.query.filter_by(name=bid_name).first()
                if selected_bid:
                    return redirect(url_for('bid_management', bid_id=selected_bid.id))
                else:
                    return "Bid not found.", 404

        bids = Bid.query.all()
        return render_template('BidManagement.html', bids=bids)
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/new-bid')
def new_bid():
    try:
        session.setdefault('bid_items', [])
        total_cost = sum(item['Cost'] * item['Quantity'] for item in session['bid_items'])
        return render_template('Bid_Job_Estimating.html', bid_items=session['bid_items'], total_cost=total_cost)
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/')
def home():
    try:
        return render_template('Home.html')
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/add', methods=['POST'])
def add_item():
    try:
        part_num = request.form['PartNum']
        quantity = int(request.form['Quantity'])
        item = next((item for item in session['inventory'] if item['PartNum'] == part_num), None)
        if item:
            session['bid_items'].append({**item, "Quantity": quantity, "Cost": float(item['Cost'])})
            session.modified = True
            total_cost = sum(item['Cost'] * item['Quantity'] for item in session['bid_items'])
            return jsonify(success=True, bid_items=session['bid_items'], total_cost=total_cost)
        else:
            return jsonify(success=False), 404
    except Exception as e:
        return jsonify(error=str(e)), 500

# Continue to add error han@app.route('/factors/manage', methods=['GET', 'POST'])
def manage_factors():
    try:
        if request.method == 'POST':
            factor_id = request.form.get('Factor_ID')
            description = request.form.get('Description')
            labor_hours = request.form.get('LaborHours')

            factor = FactorCode.query.filter_by(factor_code=factor_id).first()
            if factor:
                factor.description = description
                factor.labor_hours = labor_hours
            else:
                new_factor = FactorCode(factor_code=factor_id, description=description, labor_hours=labor_hours)
                db.session.add(new_factor)
            db.session.commit()
            return redirect(url_for('manage_factors'))

        factors = FactorCode.query.all()
        return render_template('ManageFactors.html', factors=factors)
    except Exception as e:
        app.logger.error(f"Error managing factors: {e}")
        return jsonify(error=str(e)), 500

@app.route('/inventory/delete', methods=['POST'])
def delete_inventory_item():
    try:
        part_num = request.form.get('PartNum')
        Inventory.query.filter_by(part_number=part_num).delete()
        db.session.commit()
        return redirect(url_for('manage_inventory'))
    except Exception as e:
        app.logger.error(f"Error deleting inventory item: {e}")
        return jsonify(error=str(e)), 500

@app.route('/factors/delete', methods=['POST'])
def delete_factor_code():
    try:
        factor_id = request.form.get('Factor_ID')
        FactorCode.query.filter_by(factor_code=factor_id).delete()
        db.session.commit()
        return redirect(url_for('manage_factors'))
    except Exception as e:
        app.logger.error(f"Error deleting factor code: {e}")
        return jsonify(error=str(e)), 500

@app.route('/factors')
def get_factors():
    try:
        factors = FactorCode.query.all()
        return jsonify([{'factor_code': f.factor_code, 'description': f.description, 'labor_hours': f.labor_hours} for f in factors])
    except Exception as e:
        app.logger.error(f"Error fetching factors: {e}")
        return jsonify(error=str(e)), 500

@app.route('/inventory')
def get_inventory():
    try:
        inventory_items = Inventory.query.all()
        return jsonify([{'part_number': i.part_number, 'description': i.description, 'cost': str(i.cost)} for i in inventory_items])
    except Exception as e:
        app.logger.error(f"Error fetching inventory: {e}")
        return jsonify(error=str(e)), 500

@app.route('/add-update-bid', methods=['GET', 'POST'])
def add_update_bid():
    try:
        if request.method == 'POST':
            create_new_bid = request.form.get('CreateNewBid') == 'on'
            bid_name = request.form.get('BidName')

            if create_new_bid:
                existing_bid = Bid.query.filter_by(name=bid_name).first()
                if existing_bid is None:
                    new_bid = Bid(name=bid_name)
                    db.session.add(new_bid)
                    db.session.commit()
                    session['current_bid_id'] = new_bid.id
                    return redirect(url_for('new_bid'))
                else:
                    return "A bid with this name already exists.", 400
            # Add additional logic for updating existing bids if needed
        return render_template('AddUpdateBid.html')
    except Exception as e:
        app.logger.error(f"Error adding or updating a bid: {e}")
        return jsonify(error=str(e)), 500


if __name__ == '__main__':
    app.run(port=5000, debug=False)
