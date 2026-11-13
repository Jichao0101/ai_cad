"""Verify the exported step sequence and the Windows COM dependency offline."""
import json
import runpy
from pathlib import Path

import pythoncom
from win32com.client import VARIANT


def main():
    pythoncom.CoInitialize()
    try:
        VARIANT(pythoncom.VT_I4, 1)
    finally:
        pythoncom.CoUninitialize()
    root = Path(__file__).resolve().parent / "handle_base"
    steps = runpy.run_path(str(root / "sequence.py"))["STEPS"]
    expected = {name + ".json" for name, _ in steps}
    actual = {p.name for p in root.glob("step_*.json")}
    if expected != actual or len(expected) != len(steps):
        raise ValueError("Step file inventory differs from sequence")
    for number, (name, identifier) in enumerate(steps, 1):
        path = root / (name + ".json")
        step = json.loads(path.read_text(encoding="utf-8"))
        if (step["STEP_NUMBER"], step["RECORD"]["id"]) != (number, identifier):
            raise ValueError(f"Step number or feature ID mismatch: {path}")
        if number in (794, 795):
            print(number, step["RECORD"]["type"])
    print(f"COM initialization OK; {len(steps)} steps validated")


if __name__ == "__main__":
    main()
