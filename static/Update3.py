import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
import os
from datetime import datetime

def clean_factor_code(x):
    if pd.isna(x) or str(x).strip() == '':
        return None
    # Clean the factor code string
    value = str(x).strip()
    # If it ends with .0, remove the decimal portion
    if value.endswith('.0'):
        return value.split('.')[0]
    return value

def clean_data(df):
    # Clean up the data
    df['Cost'] = df['Cost'].apply(lambda x: 
        float(str(x).replace(',', '')) if pd.notnull(x) and str(x).strip() != '' else 0.0)
    df['PartNum'] = df['PartNum'].str.strip()
    df['Description'] = df['Description'].fillna('')
    # Only convert empty or null values to None, and only strip decimal from 999.0
    df['Factor Code'] = df['Factor Code'].apply(clean_factor_code)
    return df

def insert_new_inventory():
    print("Starting inventory insertion process...")
    conn = None
    skipped_items = []
    
    try:
        # Read the CSV file
        base_path = os.path.join(os.path.dirname(__file__))
        
        # Load and clean data
        df = pd.read_csv(os.path.join(base_path, 'AddMissingParts.csv'))
        df = clean_data(df)
        print(f"Loaded {len(df)} items from CSV file")
        
        # Database connection
        conn = psycopg2.connect(
            dbname="flask_bids",
            user="",  # Update with your username
            password="",      # Update with your password
            host="pricebookdb.postgres.database.azure.com"
        )
        cur = conn.cursor()
        
        # Get existing part numbers
        cur.execute("SELECT part_number FROM inventory")
        existing_parts = {row[0] for row in cur.fetchall()}
        
        # Get valid factor codes
        cur.execute("SELECT factor_code FROM factor_code")
        valid_factor_codes = {str(row[0]) for row in cur.fetchall()}
        print(f"Found {len(valid_factor_codes)} valid factor codes")
        
        # Filter to only new parts
        new_parts_df = df[~df['PartNum'].isin(existing_parts)]
        print(f"Found {len(new_parts_df)} new parts to insert")
        
        if not new_parts_df.empty:
            successful_inserts = 0
            
            # Process each row
            for _, row in new_parts_df.iterrows():
                factor_code = clean_factor_code(row['Factor Code'])
                skip_reason = None
                
                # Validate the row
                if row['PartNum'] in existing_parts:
                    skip_reason = "Part number already exists"
                elif factor_code is not None and factor_code not in valid_factor_codes:
                    skip_reason = f"Invalid factor code: {factor_code}"
                
                if skip_reason:
                    skipped_row = row.to_dict()
                    skipped_row['Reason'] = skip_reason
                    skipped_items.append(skipped_row)
                    continue
                
                # Insert valid item
                insert_query = """
                    INSERT INTO inventory (part_number, description, cost, factor_code)
                    VALUES (%s, %s, %s, %s)
                """
                try:
                    cur.execute(insert_query, (
                        row['PartNum'],
                        row['Description'],
                        row['Cost'],
                        factor_code
                    ))
                    conn.commit()
                    successful_inserts += 1
                    
                    if successful_inserts % 50 == 0:  # Print progress every 50 items
                        print(f"Processed {successful_inserts} items")
                        
                except Exception as e:
                    conn.rollback()
                    skipped_row = row.to_dict()
                    skipped_row['Reason'] = f"Database error: {str(e)}"
                    skipped_items.append(skipped_row)
            
            print(f"\nSuccessfully inserted {successful_inserts} new parts")
            
            # Save skipped items to CSV
            if skipped_items:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                skipped_file = os.path.join(base_path, f'skipped_items_{timestamp}.csv')
                skipped_df = pd.DataFrame(skipped_items)
                # Reorder columns to put Reason first
                cols = ['Reason'] + [col for col in skipped_df.columns if col != 'Reason']
                skipped_df = skipped_df[cols]
                skipped_df.to_csv(skipped_file, index=False)
                print(f"Saved {len(skipped_items)} skipped items to: {skipped_file}")
                
                # Print summary of reasons
                print("\nSkipped items summary:")
                reason_counts = skipped_df['Reason'].value_counts()
                for reason, count in reason_counts.items():
                    print(f"- {reason}: {count} items")
            
        else:
            print("No new parts to insert")
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        if conn is not None:
            conn.rollback()
    finally:
        if conn is not None:
            if 'cur' in locals():
                cur.close()
            conn.close()

if __name__ == "__main__":
    insert_new_inventory()