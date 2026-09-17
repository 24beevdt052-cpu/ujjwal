"""
Fixes two Windows-specific issues in this project:
1. IndentationError in desk/reporting/interview_pack.py (day function)
2. OverflowError in tools/export_public.py (csv.field_size_limit with sys.maxsize)

Run from the project root folder:
    python fix_windows_compat.py
"""
import re
from pathlib import Path

root = Path(".").resolve()
changed = []

# ---- Fix 1: interview_pack.py day() function ----
target1 = root / "desk" / "reporting" / "interview_pack.py"
if target1.exists():
    text = target1.read_text(encoding="utf-8")
    pattern = re.compile(
        r"def day\(d, year: bool = False\) -> str:.*?(?=\ndef |\Z)",
        re.DOTALL,
    )
    replacement = (
        'def day(d, year: bool = False) -> str:\n'
        '    ts = pd.Timestamp(d)\n'
        '    return ts.strftime(f"{ts.day}-%b-%Y" if year else f"{ts.day}-%b")\n\n'
    )
    new_text, count = pattern.subn(replacement, text)
    if count > 0:
        target1.write_text(new_text, encoding="utf-8")
        changed.append(f"Fixed day() function in {target1.relative_to(root)}")
    else:
        changed.append(f"[SKIPPED] Could not find day() function pattern in {target1.relative_to(root)} (may already be fixed)")
else:
    changed.append(f"[NOT FOUND] {target1}")

# ---- Fix 2: export_public.py csv.field_size_limit ----
target2 = root / "tools" / "export_public.py"
if target2.exists():
    text = target2.read_text(encoding="utf-8")
    old_line_pattern = re.compile(r"^([ \t]*)csv\.field_size_limit\(sys\.maxsize\)\s*$", re.MULTILINE)
    def replace_line(m):
        indent = m.group(1)
        return (
            f"{indent}try:\n"
            f"{indent}    csv.field_size_limit(sys.maxsize)\n"
            f"{indent}except OverflowError:\n"
            f"{indent}    csv.field_size_limit(2**31 - 1)"
        )
    new_text, count = old_line_pattern.subn(replace_line, text)
    if count > 0:
        target2.write_text(new_text, encoding="utf-8")
        changed.append(f"Fixed csv.field_size_limit in {target2.relative_to(root)}")
    else:
        changed.append(f"[SKIPPED] Could not find csv.field_size_limit(sys.maxsize) line in {target2.relative_to(root)} (may already be fixed)")
else:
    changed.append(f"[NOT FOUND] {target2}")

print("\n".join(changed))
print("\nDone. Now run: streamlit run app\\streamlit_app.py --server.address localhost")
