import csv

# Define the input and output file paths
input_file_path = r'C:\Users\Dev PC\Desktop\Cleaned_Inventory.txt'
output_file_path = r'C:\Users\Dev PC\Desktop\Final_Cleaned_Inventory.txt'

# Open the input file for reading
with open(input_file_path, 'r', newline='', encoding='ISO-8859-1') as infile:
    reader = csv.reader(infile)
    
    # Open the output file for writing
    with open(output_file_path, 'w', newline='', encoding='ISO-8859-1') as outfile:
        writer = csv.writer(outfile)
        
        # Process each row in the input file
        for row in reader:
            if row:  # Ensure the row is not empty
                # Remove the dollar sign from the cost column
                row[2] = row[2].replace('$', '')
                
                # Write the cleaned row to the output file
                writer.writerow(row)

print(f"Final cleaned data has been saved to {output_file_path}")
