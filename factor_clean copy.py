import openpyxl
import psycopg2
from psycopg2 import sql
from datetime import datetime

# Excel file path
excel_file = r'C:\Users\Dev PC\Documents\GitHub\Bid-Proposal\Corrected_FactorMV.xlsx'

# Database connection parameters
# Database connection parameters
db_params = {
    'dbname': 'flask_bids',
    'user': 'Rclick@pricebookdb',
    'password': 'Tall99Tower',
    'host': 'pricebookdb.postgres.database.azure.com',
    'port': 5432,
}

# Mapping for specific part numbers
part_number_mapping = {
    1274413: '12-2248',
    40283: '12-3002',
    140612: '12-3011',
    456859: '10-5500',
    949906: '10-4500',
    1293234: '10-5440',
    1300539: '10-5460',
    1307844: '10-5480',
    1315148: '11-3150'
}

def clean_part_number(value):
    if isinstance(value, (int, float)):
        # Check if the value is in our mapping
        return part_number_mapping.get(int(value), str(int(value)))
    elif isinstance(value, datetime):
        # Convert datetime to string in the format "MM-DD"
        return value.strftime("%m-%d")
    elif isinstance(value, str):
        # If it's already a string, return it as is
        return value
    else:
        # For any other type, convert to string
        return str(value)

def read_excel_and_convert(file_path):
    workbook = openpyxl.load_workbook(file_path)
    sheet = workbook.active
    data = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if len(row) >= 3 and all(cell is not None for cell in row[:3]):
            factor_code, part_number, quantity = row[0], row[1], row[2]
            try:
                cleaned_part_number = clean_part_number(part_number)
                data.append((str(factor_code), cleaned_part_number, float(quantity)))
            except ValueError:
                print(f"Skipping invalid row: {row[:3]}")
    return data

def update_database(data):
    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    select_query = sql.SQL("""
        SELECT id FROM factor_code_items
        WHERE factor_code = %s AND part_number = %s
    """)

    update_query = sql.SQL("""
        UPDATE factor_code_items
        SET quantity = %s
        WHERE id = %s
    """)

    insert_query = sql.SQL("""
        INSERT INTO factor_code_items (factor_code, part_number, quantity)
        VALUES (%s, %s, %s)
    """)

    rows_updated = 0
    rows_inserted = 0
    rows_skipped = 0

    for item in data:
        factor_code, part_number, quantity = item
        
        # Check if the part number exists in the inventory table
        cursor.execute("SELECT part_number FROM inventory WHERE part_number = %s", (part_number,))
        if not cursor.fetchone():
            print(f"Skipping row with invalid part number: {item}")
            rows_skipped += 1
            continue
        
        # Check if the record exists
        cursor.execute(select_query, (factor_code, part_number))
        result = cursor.fetchone()
        
        if result:
            # Update existing record
            cursor.execute(update_query, (quantity, result[0]))
            rows_updated += 1
        else:
            # Insert new record
            cursor.execute(insert_query, (factor_code, part_number, quantity))
            rows_inserted += 1

    conn.commit()
    cursor.close()
    conn.close()

    return rows_updated, rows_inserted, rows_skipped

# Main execution
if __name__ == "__main__":
    excel_data = read_excel_and_convert(excel_file)
    updated, inserted, skipped = update_database(excel_data)
    print(f"Database update complete.")
    print(f"Rows updated: {updated}")
    print(f"Rows inserted: {inserted}")
    print(f"Rows skipped: {skipped}")
    print(f"Total rows processed: {len(excel_data)}")