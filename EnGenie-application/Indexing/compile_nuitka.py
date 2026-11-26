import os
import sys
import subprocess

def get_python_files(dir_path):
    py_files = []
    for root, _, files in os.walk(dir_path):
        if "__pycache__" in root or ".venv" in root or "/." in root or "\\." in root:
            continue
        for file in files:
            # Compile all .py files except package index __init__.py and this compiler script itself
            if file.endswith(".py") and file != "__init__.py" and file != "compile_nuitka.py":
                py_files.append(os.path.join(root, file))
    return py_files

def compile_files():
    here = os.path.dirname(os.path.abspath(__file__))
    py_files = get_python_files(here)
    
    print(f"[NUITKA] Found {len(py_files)} Python source files to compile inside Indexing.")
    
    for py_file in py_files:
        print(f"[NUITKA] Compiling: {py_file}")
        dir_name = os.path.dirname(py_file) or "."
        
        # Nuitka module compilation command
        cmd = [
            sys.executable, "-m", "nuitka",
            "--module",
            "--remove-output",
            f"--output-dir={dir_name}",
            py_file
        ]
        
        try:
            # Run Nuitka compilation
            subprocess.run(cmd, check=True)
            print(f"[NUITKA] Successfully compiled {py_file}")
            
            # Remove original plain-text .py file
            if os.path.exists(py_file):
                os.remove(py_file)
                print(f"[NUITKA] Removed original source: {py_file}")
                
            # Remove generated .pyi stub file for maximum code protection
            pyi_file = py_file + "i"
            if os.path.exists(pyi_file):
                os.remove(pyi_file)
                print(f"[NUITKA] Removed stub file: {pyi_file}")
                
        except subprocess.CalledProcessError as e:
            print(f"[NUITKA] [ERROR] Failed to compile {py_file}: {e}")
            sys.exit(1)
            
    print("[NUITKA] Compilation process complete! All pipeline source modules converted to binary.")

if __name__ == "__main__":
    compile_files()
