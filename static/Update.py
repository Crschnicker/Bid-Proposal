import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
import os
from datetime import datetime

def clean_cost(cost):
    if pd.isna(cost) or cost == '':
        return 0.0
    if isinstance(cost, str):
        # Remove commas and convert to float
        return float(cost.replace(',', ''))
    return float(cost)

def update_inventory_pricing():
    print("Starting inventory price update process...")
    
    # Read the CSV file
    csv_path = os.path.join(os.path.dirname(__file__), 'Updated Pricing.csv')
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} items from CSV file")
    
    # Clean up the data
    df['Cost'] = df['Cost'].apply(clean_cost)  # Handle commas and convert to float
    df['PartNum'] = df['PartNum'].str.strip()  # Remove any whitespace
    
    try:
        # Database connection
        conn = psycopg2.connect(
            dbname="flask_bids",
            user="",  # Update with your username
            password="",      # Update with your password
            host="pricebookdb.postgres.database.azure.com"
        )
        cur = conn.cursor()
        
        # Get list of existing part numbers
        cur.execute("SELECT part_number FROM inventory")
        existing_parts = {row[0] for row in cur.fetchall()}
        print(f"Found {len(existing_parts)} existing parts in inventory")
        
        # Separate matched and unmatched parts
        matched_df = df[df['PartNum'].isin(existing_parts)]
        unmatched_df = df[~df['PartNum'].isin(existing_parts)]
        
        # Update prices for matching parts
        if not matched_df.empty:
            update_query = """
                UPDATE inventory 
                SET cost = %s 
                WHERE part_number = %s
            """
            update_data = [(float(row['Cost']), row['PartNum']) for _, row in matched_df.iterrows()]
            
            # Process in batches of 500
            batch_size = 500
            total_batches = (len(update_data) + batch_size - 1) // batch_size
            
            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min((batch_num + 1) * batch_size, len(update_data))
                batch_data = update_data[start_idx:end_idx]
                
                execute_batch(cur, update_query, batch_data)
                print(f"Processed {end_idx}/{len(update_data)} items")
                conn.commit()  # Commit each batch
            
        # Save unmatched parts to CSV if any exist
        if not unmatched_df.empty:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unmatched_file = os.path.join(os.path.dirname(__file__),  
                                        f'unmatched_parts_{timestamp}.csv')
            unmatched_df.to_csv(unmatched_file, index=False)
            print(f"Unmatched parts saved to: {unmatched_file}")
        
        # Print summary
        print(f"\nSummary:")
        print(f"Successfully updated {len(matched_df)} part prices")
        print(f"Found {len(unmatched_df)} unmatched parts")
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        conn.rollback()
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    update_inventory_pricing()
