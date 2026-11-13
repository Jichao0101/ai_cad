"""Restore one generated, closed test Part to its original empty baseline."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import win32com.client as com


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    root = parser.parse_args().run_dir.resolve(strict=True)
    runs = (Path(__file__).resolve().parents[1] / "runs").resolve()
    if root.parent != runs or not root.name.startswith("v5-line-"):
        parser.error("Expected a generated v5-line directory directly under runs")
    path = root / "Line.CATPart"
    baseline = root / "empty-baseline.CATPart"
    report = json.loads((root / "result.json").read_text(encoding="utf-8"))
    if (Path(report["file"]) != path or not report["passed"]
            or path.resolve(strict=True) != path or baseline.resolve(strict=True) != baseline):
        parser.error("Test artifact identity check failed")
    empty_hash = report["baseline_sha256"]
    current = digest(path)
    if digest(baseline) != empty_hash or current not in (report["built_sha256"], empty_hash):
        parser.error("Part or baseline changed since creation")
    app = com.GetActiveObject("CATIA.Application")
    for i in range(1, app.Documents.Count + 1):
        if Path(app.Documents.Item(i).FullName) == path:
            opened = app.Documents.Item(i)
            if not opened.Saved:
                parser.error("Test Part has unsaved edits; review them before resetting")
            opened.Close()
            break
    if current != empty_hash:
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            shutil.copyfile(baseline, tmp_path)
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)
    doc = app.Documents.Open(str(path))
    try:
        structure = {"bodies": doc.Part.Bodies.Count, "hybrid_bodies": doc.Part.HybridBodies.Count}
    finally:
        doc.Close()
    if structure != report["empty_structure"] or digest(path) != empty_hash:
        raise RuntimeError("Restored Part does not match baseline")
    result = {"file": str(path), "structure": structure, "baseline_sha256": empty_hash, "passed": True}
    (root / "reset-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
