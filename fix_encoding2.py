"""
Fixes garbled text (mojibake) that appears when UTF-8 characters (dashes, curly quotes,
the multiplication sign, etc.) get misread as a different encoding (cp1252) somewhere
along the way.

Run from the project root folder:
    python fix_encoding2.py
"""
from pathlib import Path

EXTENSIONS = [".py", ".yaml", ".yml", ".md", ".csv", ".json"]

# Telltale marker that a file contains this specific kind of corruption
TELLTALE = "\u00e2\u20ac"  # the two characters that always start this type of mojibake

def repair_text(text: str) -> str:
    """
    Standard fix for 'UTF-8 bytes that got decoded as cp1252 (Windows-1252)':
    re-encode back to cp1252 bytes, then decode those bytes properly as UTF-8.
    """
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text  # couldn't cleanly reverse it - leave the text untouched
    return repaired

def fix_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    if TELLTALE not in text:
        return False

    repaired = repair_text(text)
    if repaired != text:
        path.write_text(repaired, encoding="utf-8")
        return True
    return False

def main():
    root = Path(".").resolve()
    files = [
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix in EXTENSIONS
        and ".venv" not in p.parts
        and "__pycache__" not in p.parts
        and ".git" not in p.parts
    ]

    print(f"Scanning {len(files)} files under {root} ...\n")
    fixed_count = 0

    for path in files:
        if fix_file(path):
            print(f"  Fixed: {path.relative_to(root)}")
            fixed_count += 1

    print(f"\nDone. Fixed {fixed_count} file(s).")
    print("Now restart the app: streamlit run app\\streamlit_app.py --server.address localhost")

if __name__ == "__main__":
    main()
