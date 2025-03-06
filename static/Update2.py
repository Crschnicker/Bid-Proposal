import pandas as pd
import os
from datetime import datetime

def read_csv_with_encoding(file_path):
    """Try different encodings to read the CSV file"""
    encodings = ['utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"Error reading file with {encoding} encoding: {str(e)}")
            continue
    
    raise ValueError(f"Could not read file {file_path} with any of the attempted encodings")

def generate_unmatched_parts_report():
    print("Starting unmatched parts report generation...")
    
    try:
        # Read the CSV files
        base_path = os.path.join(os.path.dirname(__file__))
        
        # Read full inventory
        inventory_path = os.path.join(base_path, 'Full Inventory Sheet.csv')
        inventory_df = read_csv_with_encoding(inventory_path)
        print(f"Loaded {len(inventory_df)} items from inventory")
        
        # Read unmatched parts
        unmatched_path = os.path.join(base_path, 'unmatched_parts_20250106_083404.csv')
        unmatched_df = read_csv_with_encoding(unmatched_path)
        print(f"Loaded {len(unmatched_df)} unmatched parts")
        
        # Get the part numbers that were not matched
        unmatched_parts = set(unmatched_df['PartNum'])
        
        # Filter inventory to only include unmatched parts
        unmatched_details_df = inventory_df[inventory_df['PartNum'].isin(unmatched_parts)]
        
        # Generate output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(base_path, f'unmatched_parts_details_{timestamp}.csv')
        
        # Save to CSV with UTF-8 encoding
        unmatched_details_df.to_csv(output_file, index=False, encoding='utf-8')
        
        print(f"\nReport Summary:")
        print(f"Total inventory items: {len(inventory_df)}")
        print(f"Unmatched parts found in inventory: {len(unmatched_details_df)}")
        print(f"Total unmatched parts: {len(unmatched_df)}")
        print(f"\nUnmatched parts details saved to: {output_file}")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        print("Please check that both input files exist and are accessible.")

if __name__ == "__main__":
    generate_unmatched_parts_report()