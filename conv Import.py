import csv
from app import app, db, Inventory, ConversionCode, inventory_conversion_code

def import_conversion_codes(csv_file_path):
    with app.app_context():
        try:
            with open(csv_file_path, 'r') as file:
                csv_reader = csv.DictReader(file)
                for row in csv_reader:
                    part_number = row['PartNum']
                    conversion_code = row['Conversion Code']

                    # Ensure the conversion code exists
                    code_entry = ConversionCode.query.filter_by(code=conversion_code).first()
                    if not code_entry:
                        code_entry = ConversionCode(code=conversion_code)
                        db.session.add(code_entry)
                        db.session.commit()  # Commit to get the ID for the relationship

                    # Ensure the inventory item exists
                    inventory_item = Inventory.query.get(part_number)
                    if not inventory_item:
                        print(f"Warning: Part number {part_number} not found in inventory")
                        continue

                    # Link the inventory item with the conversion code
                    association = db.session.query(inventory_conversion_code).filter_by(
                        inventory_part_number=part_number,
                        conversion_code=conversion_code
                    ).first()
                    if not association:
                        db.session.execute(
                            inventory_conversion_code.insert().values(
                                inventory_part_number=part_number,
                                conversion_code=conversion_code
                            )
                        )

                db.session.commit()
                print("Conversion codes imported successfully")

        except Exception as e:
            db.session.rollback()
            print(f"Error importing conversion codes: {e}")

if __name__ == "__main__":
    csv_file_path = r"C:\Users\Dev PC\Documents\GitHub\Bid-Proposal\ConversionCodes.csv"
    import_conversion_codes(csv_file_path)
