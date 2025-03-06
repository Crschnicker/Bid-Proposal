import csv
import re

# Define the input and output file paths
input_file_path = r'C:\Users\Dev PC\Desktop\FactorMV.txt'
output_file_path = r'C:\Users\Dev PC\Desktop\Cleaned_FactorMV.txt'

# Regular expression to match scientific notation
scientific_notation_re = re.compile(r'[+-]?[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?')

def clean_value(value):
    """Remove surrounding quotes and leading/trailing whitespace from the value."""
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value

# Open the input file for reading
with open(input_file_path, 'r', newline='', encoding='ISO-8859-1') as infile:
    reader = csv.reader(infile)
    
    # Open the output file for writing
    with open(output_file_path, 'w', newline='', encoding='ISO-8859-1') as outfile:
        writer = csv.writer(outfile)
        
        # Write the header to the output file
        writer.writerow(['factor_code', 'part_number', 'quantity'])  # Adjusted header for the new table
        
        # Process each row in the input file
        for row in reader:
            if row:  # Ensure the row is not empty
                # Clean up the row
                factor_code = clean_value(row[0])  # Remove quotes and extra spaces from factor_code
                part_number = clean_value(row[1])  # Remove quotes and extra spaces from part_number

                # Clean and validate the quantity
                quantity_raw = clean_value(row[2])
                
                # Default to one if quantity is empty or invalid
                quantity = 1.0
                if quantity_raw:
                    try:
                        if scientific_notation_re.match(quantity_raw):
                            quantity = float(quantity_raw)  # Convert scientific notation to float
                        else:
                            quantity = float(re.sub(r'[^\d.]+', '', quantity_raw))  # Remove non-numeric except '.'
                    except ValueError:
                        print(f"Warning: Could not convert quantity '{quantity_raw}' to float. Defaulting to 1.0.")

                # Write the cleaned row to the output file
                writer.writerow([factor_code, part_number, quantity])

print(f"Cleaned data has been saved to {output_file_path}")
