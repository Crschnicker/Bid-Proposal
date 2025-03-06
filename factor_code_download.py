import pandas as pd
import psycopg2
from psycopg2 import sql

# Load CSV file
csv_path = r"C:\Users\Dev PC\Documents\GitHub\Bid-Proposal\Cleaned_Factor.csv"
df = pd.read_csv(csv_path)

# Ensure that the factor_code column is treated as a string
df['factor_code'] = df['factor_code'].astype(str)

# Database connection parameters
db_params = {
    'dbname': 'flask_bids',
    'user': 'Rclick@pricebookdb',
    'password': 'Tall99Tower',
    'host': 'pricebookdb.postgres.database.azure.com',
    'port': 5432,
}

# Connect to the database
conn = psycopg2.connect(**db_params)

# SQL query to fetch the entire table
query = "SELECT * FROM factor_code"

# Load the table into a pandas DataFrame
df = pd.read_sql_query(query, conn)

# Close the database connection
conn.close()

# Path to save the CSV file
csv_path = r"C:\Users\Dev PC\Documents\GitHub\Bid-Proposal\Current_Factor_Code.csv"

# Save the DataFrame to a CSV file
df.to_csv(csv_path, index=False)

print(f"Table saved as CSV to {csv_path}")