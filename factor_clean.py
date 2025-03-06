import csv
import re

# Define the input and output file paths
input_file_path = r'C:\Users\Dev PC\Desktop\Factor.txt'
output_file_path = r'C:\Users\Dev PC\Desktop\Cleaned_Factor.txt'

# Regular expression to match scientific notation
scientific_notation_re = re.compile(r'[+-]?[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?')

def clean_description(description):
    """Remove surrounding quotes from description and preserve internal quotes."""
    description = description.strip()
    # Remove surrounding quotes but keep internal ones
    if description.startswith('"') and description.endswith('"'):
        description = description[1:-1]
    return description

# Open the input file for reading
with open(input_file_path, 'r', newline='', encoding='ISO-8859-1') as infile:
    reader = csv.reader(infile)
    
    # Open the output file for writing
    with open(output_file_path, 'w', newline='', encoding='ISO-8859-1') as outfile:
        writer = csv.writer(outfile)
        
        # Write the header to the output file
        writer.writerow(['factor_code', 'labor_hours', 'description'])
        
        # Process each row in the input file
        for row in reader:
            if row:  # Ensure the row is not empty
                # Clean up the row
                factor_code = row[0].strip().replace('"', '')  # Remove quotes and extra spaces from factor_code

                # Clean and validate the labor_hours
                labor_hours_raw = row[1].strip().replace('"', '').replace('$', '')
                
                # Default to zero if labor_hours is empty or invalid
                labor_hours = 0.0
                if labor_hours_raw:
                    try:
                        if scientific_notation_re.match(labor_hours_raw):
                            labor_hours = float(labor_hours_raw)  # Convert scientific notation to float
                        else:
                            labor_hours = float(re.sub(r'[^\d.]+', '', labor_hours_raw))  # Remove non-numeric except '.'
                    except ValueError:
                        print(f"Warning: Could not convert labor_hours '{labor_hours_raw}' to float. Defaulting to 0.0.")

                # Clean the description and remove surrounding quotes but preserve internal quotes
                description = clean_description(row[2])

                # Write the cleaned row to the output file
                writer.writerow([factor_code, labor_hours, description])

print(f"Cleaned data has been saved to {output_file_path}")
