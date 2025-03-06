import pandas as pd
import psycopg2
from psycopg2 import sql
import logging
from decimal import Decimal

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load CSV file
csv_path = r"C:\Users\Dev PC\Documents\GitHub\Bid-Proposal\Cleaned_Factor.csv"
df = pd.read_csv(csv_path, dtype={'factor_code': str, 'labor_hours': str})

# Database connection parameters
db_params = {
    'dbname': 'flask_bids',
    'user': 'Rclick@pricebookdb',
    'password': 'Tall99Tower',
    'host': 'pricebookdb.postgres.database.azure.com',
    'port': 5432,
}

# Connect to the database
try:
    conn = psycopg2.connect(**db_params)
    cur = conn.cursor()
    logging.info("Successfully connected to the database.")

    # Check the current column definition
    cur.execute("SELECT column_name, data_type, numeric_precision, numeric_scale FROM information_schema.columns WHERE table_name = 'factor_code' AND column_name = 'labor_hours';")
    column_info = cur.fetchone()
    logging.info(f"Current labor_hours column definition: {column_info}")

    # Alter the table if necessary to ensure sufficient precision
    if column_info[1] != 'numeric' or column_info[2] < 10 or column_info[3] < 6:
        cur.execute("ALTER TABLE factor_code ALTER COLUMN labor_hours TYPE numeric(10,6);")
        logging.info("Altered labor_hours column to numeric(10,6)")

    # Iterate over the rows in the DataFrame and update labor_hours in the database
    for index, row in df.iterrows():
        factor_code = row['factor_code']
        labor_hours = row['labor_hours']
        logging.info(f"Processing factor_code {factor_code} with labor_hours {labor_hours}")

        # Check if the factor_code exists
        cur.execute("SELECT COUNT(*) FROM factor_code WHERE factor_code = %s", (factor_code,))
        if cur.fetchone()[0] == 0:
            logging.warning(f"Factor code {factor_code} does not exist in the database. Skipping.")
            continue

        # Update statement
        update_query = sql.SQL("""
            UPDATE factor_code
            SET labor_hours = %s::numeric(10,6)
            WHERE factor_code = %s
            RETURNING labor_hours
        """)

        # Execute the update statement
        cur.execute(update_query, (Decimal(labor_hours), factor_code))
        result = cur.fetchone()
        
        if result is None:
            logging.warning(f"No rows updated for factor_code {factor_code}. This should not happen if the factor_code exists.")
        else:
            updated_value = result[0]
            logging.info(f"Updated value in database for factor_code {factor_code}: {updated_value}")

            # Check if the updated value matches the input value
            if abs(Decimal(updated_value) - Decimal(labor_hours)) > Decimal('1E-6'):
                logging.warning(f"Mismatch for factor_code {factor_code}: Input {labor_hours}, Stored {updated_value}")

    # Commit the changes
    conn.commit()
    logging.info("All updates committed successfully.")

    # Verify a few values
    verify_codes = ['125', '1004', '1005', '1006']
    cur.execute(sql.SQL("SELECT factor_code, labor_hours::numeric(10,6) FROM factor_code WHERE factor_code IN %s"), (tuple(verify_codes),))
    verified_values = cur.fetchall()
    for code, value in verified_values:
        logging.info(f"Verified value for factor_code {code}: {value}")

except Exception as e:
    logging.error(f"An error occurred: {e}")
    conn.rollback()

finally:
    if conn:
        cur.close()
        conn.close()
        logging.info("Database connection closed.")

print("Script execution completed. Please check the log for details.")