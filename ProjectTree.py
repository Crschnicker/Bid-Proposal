import os
from pathlib import Path

def generate_tree(directory, prefix="", ignore_patterns=None):
    """
    Generate a tree structure of the given directory.
    
    Args:
        directory (str): The root directory to start from
        prefix (str): Prefix for the current item (used for recursion)
        ignore_patterns (list): List of patterns to ignore (e.g., ['.git', '__pycache__', 'venv'])
    
    Returns:
        str: String representation of the directory tree
    """
    if ignore_patterns is None:
        ignore_patterns = ['.git', '__pycache__', 'node_modules', 'venv', '.env']
    
    # Initialize output string
    output = []
    
    # Get the directory contents
    try:
        entries = list(os.scandir(directory))
    except PermissionError:
        return f"{prefix}[Permission Denied]\n"
    
    # Sort entries (directories first, then files)
    entries.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
    
    # Process each entry
    for i, entry in enumerate(entries):
        # Skip ignored patterns
        if any(pattern in entry.path for pattern in ignore_patterns):
            continue
        
        # Determine if this is the last item at this level
        is_last = i == len(entries) - 1
        
        # Choose the appropriate prefix characters
        connector = "└── " if is_last else "├── "
        
        # Add the current item to the output
        output.append(f"{prefix}{connector}{entry.name}")
        
        # If it's a directory, recursively process its contents
        if entry.is_dir():
            # Choose the appropriate prefix for nested items
            extension = "    " if is_last else "│   "
            output.append(generate_tree(entry.path, prefix + extension, ignore_patterns))
    
    return "\n".join(output)

def main():
    """
    Main function to run the directory tree generator.
    """
    # Get the current directory or accept a path as argument
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    
    # Print the tree
    print(f"\nDirectory Tree for: {os.path.abspath(path)}")
    print("=" * 50)
    print(generate_tree(path))

if __name__ == "__main__":
    main()