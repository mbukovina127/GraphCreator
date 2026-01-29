import os

def analyze_project_structure(directory_path):
    items_info = []
    items_info.append({
        "name": os.path.basename(directory_path.rstrip(os.sep)),
        "path": directory_path,
        "type": "dir",
        "parent": None
    })
    
    # recursively traverse through the file system tree
    for root, dirs, files in os.walk(directory_path):
        # directories 
        for directory in dirs:
            items_info.append({
                "name": directory,
                "path": os.path.join(root, directory),
                "type": "dir",
                "parent": root
            })
        # process files
        for f in files:
            if f.endswith(".lua"):
                items_info.append({
                    "name": f,
                    "path": os.path.join(root, f),
                    "type": "file",
                    "parent": root
                })
    return items_info
