"""
Fixes Mac/Linux-only strftime format codes (%#d, %#m, %#H, %#M, %#S, %#j)
so they work on Windows, by converting them to the Windows equivalent (%#d, %#m, etc).

Run this from inside your project's root folder (the one containing 'desk', 'app', etc):
    python fix_windows_dates.py

It scans every .py file in the project, fixes any occurrences, and prints what it changed.
Safe to run multiple times - it won't double-fix anything already correct.
"""
import re
from pathlib import Path

# Matches %#d, %#m, %#H, %#M, %#S, %#j, %#y etc. (a dash right after % followed by a letter)
PATTERN = re.compile(r'%-([a-zA-Z])')
REPLACEMENT = r'%#\1'

def fix_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    new_text, count = PATTERN.subn(REPLACEMENT, text)
    if count > 0:
        path.write_text(new_text, encoding="utf-8")
    return count

def main():
    root = Path(".").resolve()
    py_files = [
        p for p in root.rglob("*.py")
        if ".venv" not in p.parts and "__pycache__" not in p.parts and ".git" not in p.parts
    ]

    total_files_changed = 0
    total_occurrences = 0

    print(f"Scanning {len(py_files)} Python files under {root} ...\n")

    for path in py_files:
        try:
            count = fix_file(path)
        except Exception as e:
            print(f"  [SKIPPED - error reading/writing] {path}: {e}")
            continue
        if count > 0:
            rel = path.relative_to(root)
            print(f"  Fixed {count} occurrence(s) in: {rel}")
            total_files_changed += 1
            total_occurrences += count

    print(f"\nDone. Fixed {total_occurrences} occurrence(s) across {total_files_changed} file(s).")
    if total_occurrences == 0:
        print("No %#d style patterns found - the issue may be something else. Send the new error if the app still fails.")

if __name__ == "__main__":
    main()
