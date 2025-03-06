import csv
import psycopg2
from psycopg2.extras import execute_values

def clean_phone_number(phone):
    if not phone:
        return None
    # Remove any non-numeric characters except + for international
    clean = ''.join(c for c in phone if c.isdigit() or c == '+')
    return clean if clean else None

def import_vendors(filename):
    # Azure PostgreSQL connection parameters
    conn = psycopg2.connect(
        host="pricebookdb.postgres.database.azure.com",
        port="5432",
        dbname="flask_bids",
        user="Rclick@pricebookdb",
        password="Tall99Tower",
        sslmode="require"
    )
    
    cursor = conn.cursor()
    
    try:
        vendors = []
        with open(filename, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            for row in csv_reader:
                # Clean and prepare the data
                company = row['name'].strip() if row['name'] else None
                if not company:  # Skip rows without a company name
                    continue
                    
                # Use contact as name, if no contact use company name
                name = row['contact'].strip() if row.get('contact') else company
                
                vendors.append((
                    name,
                    company,
                    row['addr1'].strip() if row['addr1'] else None,
                    row['addr2'].strip() if row['addr2'] else None,
                    row['city'].strip() if row['city'] else None,
                    row['state'].strip() if row['state'] else None,
                    row['zip'].strip() if row['zip'] else None,
                    clean_phone_number(row['Phone']) if row.get('Phone') else None,
                    clean_phone_number(row['Fax']) if row.get('Fax') else None,
                    row['email'].strip() if row.get('email') else None
                ))
        
        # Bulk insert using execute_values
        insert_query = """
            INSERT INTO vendors (
                name, company, address1, address2, city, state, 
                zip_code, phone_number, fax_number, email
            ) VALUES %s
            RETURNING id;
        """
        
        execute_values(cursor, insert_query, vendors)
        
        # Commit the transaction
        conn.commit()
        
        print(f"Successfully imported {len(vendors)} vendors")
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {str(e)}")
        raise
    
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    csv_file = r"C:\Users\Dev PC\Documents\GitHub\Bid-Proposal\VendorImport.csv"
    import_vendors(csv_file)