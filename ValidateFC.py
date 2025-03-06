import csv

# Define the paths to your files
inventory_file_path = r'C:\Users\Dev PC\Desktop\Final_Cleaned_Inventory.txt'
output_cleaned_inventory_path = r'C:\Users\Dev PC\Desktop\Valid_Cleaned_Inventory.txt'
factor_codes_file_path = r'C:\Users\Dev PC\Desktop\Cleaned_Factor.txt'

# Read valid factor codes from the factor_code table
valid_factor_codes = set()
with open(factor_codes_file_path, 'r', newline='', encoding='ISO-8859-1') as factor_file:
    reader = csv.DictReader(factor_file)
    for row in reader:
        valid_factor_codes.add(row['factor_code'])

# Filter the inventory file to only include rows with valid factor codes
with open(inventory_file_path, 'r', newline='', encoding='ISO-8859-1') as inventory_file, \
     open(output_cleaned_inventory_path, 'w', newline='', encoding='ISO-8859-1') as output_file:
    reader = csv.DictReader(inventory_file)
    writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames)
    writer.writeheader()
    for row in reader:
        if row['factor_code'] in valid_factor_codes:
            writer.writerow(row)

print(f"Cleaned data with valid factor codes saved to {output_cleaned_inventory_path}")
