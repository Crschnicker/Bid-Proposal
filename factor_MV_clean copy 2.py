import csv

# Define file paths
factor_mv_file = r'C:\Users\Dev PC\Desktop\Cleaned_FactorMV.txt'
valid_inventory_file = r'C:\Users\Dev PC\Desktop\Valid_Cleaned_Inventory.txt'
valid_factors_file = r'C:\Users\Dev PC\Desktop\Cleaned_Factor.txt'
output_file = r'C:\Users\Dev PC\Desktop\Filtered_FactorMV.txt'

# Read valid part numbers from the inventory file
valid_part_numbers = set()
with open(valid_inventory_file, 'r', newline='', encoding='ISO-8859-1') as inventory_file:
    inventory_reader = csv.DictReader(inventory_file)
    for row in inventory_reader:
        valid_part_numbers.add(row['part_number'].strip())

# Read valid factor codes from the factor file
valid_factor_codes = set()
with open(valid_factors_file, 'r', newline='', encoding='ISO-8859-1') as factors_file:
    factors_reader = csv.DictReader(factors_file)
    for row in factors_reader:
        valid_factor_codes.add(row['factor_code'].strip())

# Process the FactorMV file
with open(factor_mv_file, 'r', newline='', encoding='ISO-8859-1') as factor_mv_file:
    reader = csv.DictReader(factor_mv_file)
    fieldnames = reader.fieldnames

    # Open the output file for writing
    with open(output_file, 'w', newline='', encoding='ISO-8859-1') as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()

        # Filter rows
        for row in reader:
            factor_code = row['factor_code'].strip()
            part_number = row['part_number'].strip()

            if factor_code in valid_factor_codes and part_number in valid_part_numbers:
                writer.writerow(row)

print(f"Filtered data has been saved to {output_file}")