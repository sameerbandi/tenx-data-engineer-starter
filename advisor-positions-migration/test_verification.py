import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
import jsonschema

root = Path(".")
python_exe = sys.executable

print(f"Using python: {python_exe}")

# 1. Run pipeline first time
start_1 = time.perf_counter()
res_1 = subprocess.run([python_exe, "run.py"], capture_output=True, text=True, check=True)
dur_1 = time.perf_counter() - start_1
print(f"Run 1 completed in {dur_1:.2f}s")

report_path = Path("out/recon_report.json")
with open(report_path, "rb") as f:
    hash_1 = hashlib.sha256(f.read()).hexdigest()

# 2. Run pipeline second time
start_2 = time.perf_counter()
res_2 = subprocess.run([python_exe, "run.py"], capture_output=True, text=True, check=True)
dur_2 = time.perf_counter() - start_2
print(f"Run 2 completed in {dur_2:.2f}s")

with open(report_path, "rb") as f:
    hash_2 = hashlib.sha256(f.read()).hexdigest()

print(f"Hash 1: {hash_1}")
print(f"Hash 2: {hash_2}")
assert hash_1 == hash_2, "Outputs between consecutive runs are not identical!"
print(">>> IDEMPOTENCY TEST: PASSED")

# 3. Schema validation
schema_path = Path("schema/recon_report.schema.json")
with open(schema_path, "r", encoding="utf-8") as sf:
    schema = json.load(sf)
with open(report_path, "r", encoding="utf-8") as rf:
    report_data = json.load(rf)

jsonschema.validate(instance=report_data, schema=schema)
print(">>> JSON SCHEMA VALIDATION: PASSED")

# 4. Zero PII leak test
for p in Path("out").rglob("*"):
    if p.is_file():
        content = p.read_text(encoding="utf-8", errors="ignore")
        assert "client_ref" not in content, f"PII leak detected in {p}: 'client_ref' found"
        assert "CR-" not in content, f"PII leak detected in {p}: 'CR-' pattern found"
print(">>> ZERO PII LEAK TEST: PASSED")

# 5. Word count checks
recon_words = len(Path("RECON.md").read_text(encoding="utf-8").split())
print(f"RECON.md word count: {recon_words} (max 300)")
assert recon_words <= 300, f"RECON.md exceeds 300 words: {recon_words}"

design_words = len(Path("DESIGN.md").read_text(encoding="utf-8").split())
print(f"DESIGN.md word count: {design_words} (~600)")
assert design_words <= 650, f"DESIGN.md exceeds page limit: {design_words}"

notes_content = Path("NOTES.md").read_text(encoding="utf-8")
sec1 = notes_content.split("## ")[1].replace("What I don't trust", "").strip().split()
sec2 = notes_content.split("## ")[2].replace("AI use", "").strip().split()
print(f"NOTES.md Sec 1 word count: {len(sec1)} (max 150)")
print(f"NOTES.md Sec 2 word count: {len(sec2)} (max 100)")
assert len(sec1) <= 150, f"NOTES.md Sec 1 exceeds 150 words: {len(sec1)}"
assert len(sec2) <= 100, f"NOTES.md Sec 2 exceeds 100 words: {len(sec2)}"
print(">>> WORD COUNT CHECKS: PASSED")

# 6. Performance check
assert dur_1 < 120, f"Run 1 took {dur_1}s (limit: 120s)"
assert dur_2 < 120, f"Run 2 took {dur_2}s (limit: 120s)"
print(">>> PERFORMANCE CHECK (< 2 min): PASSED")

print("\nALL VERIFICATIONS PASSED!")
