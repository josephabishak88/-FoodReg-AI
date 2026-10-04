import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

scripts = [
    "populate_regulatory_data.py",
    "add_missing_regulatory.py",
    "add_singapore_regulatory.py",
    "add_eu_regulatory.py",
    "add_canada_regulatory.py",
    "add_fsan_regulatory.py",
    "add_japan_regulatory.py",
    "add_gb_regulatory.py",
    "add_northern_ireland_regulatory.py",
    "add_codex_gsfa.py",
    "add_south_korea_regulatory.py",
    "add_china_regulatory.py",
    "add_malaysia_regulatory.py",
    "add_saudi_arabia_regulatory.py",
    "add_mexico_regulatory.py",
    "add_brazil_regulatory.py",
    "add_argentina_regulatory.py",
    "add_chile_regulatory.py",
    "add_colombia_regulatory.py",
    "add_peru_regulatory.py",
    "add_south_africa_regulatory.py",
    "add_nigeria_regulatory.py",
    "add_thailand_regulatory.py",
    "add_philippines_regulatory.py",
    "add_israel_regulatory.py",
    "add_indonesia_regulatory.py",
    "add_turkey_regulatory.py",
    "add_vietnam_regulatory.py",
    "add_switzerland_regulatory.py",
    "add_united_arab_emirates_regulatory.py",
]

ok = 0
missing = []
failed = []

for name in scripts:
    path = BASE / name

    if not path.exists():
        missing.append(name)
        print(f"\n⚠️ MISSING: {name}")
        continue

    print(f"\n{'='*70}\n▶ Running {name}\n{'='*70}")

    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(BASE),
        text=True,
    )

    if result.returncode == 0:
        ok += 1
    else:
        failed.append(name)
        print(f"❌ FAILED: {name}")

print("\n" + "="*70)
print("FINAL SUMMARY")
print("="*70)
print(f"Successful: {ok}")
print(f"Missing:    {len(missing)}")
print(f"Failed:     {len(failed)}")

if missing:
    print("\nMissing files:")
    for name in missing:
        print(" -", name)

if failed:
    print("\nFailed files:")
    for name in failed:
        print(" -", name)

if not missing and not failed:
    print("\n✅ All regulatory scripts completed successfully.")
else:
    print("\n⚠️ Fix the missing/failed files above, then run this file again.")
