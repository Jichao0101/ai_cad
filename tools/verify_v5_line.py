import hashlib
import shutil
import json
from datetime import datetime
from pathlib import Path
import win32com.client as com

def main():
    root = Path(__file__).resolve().parents[1] / "runs" / datetime.now().strftime("v5-line-%Y%m%d-%H%M%S-%f")
    root.mkdir(parents=True)
    app = com.GetActiveObject("CATIA.Application")
    print("Connected:", app.FullName, flush=True)
    doc = app.Documents.Add("Part")
    part = doc.Part
    path = root / "Line.CATPart"
    baseline = root / "empty-baseline.CATPart"
    empty_structure = {"bodies": part.Bodies.Count, "hybrid_bodies": part.HybridBodies.Count}
    doc.SaveAs(str(path))
    doc.Close()
    shutil.copyfile(path, baseline)
    doc = app.Documents.Open(str(path))
    part = doc.Part
    body = part.HybridBodies.Add()
    body.Name = "PythonVerification"
    factory = part.HybridShapeFactory
    point = factory.AddNewPointCoord(0, 0, 0)
    body.AppendHybridShape(point)
    part.Update()
    direction = factory.AddNewDirectionByCoord(1, 0, 0)
    line = factory.AddNewLinePtDir(part.CreateReferenceFromObject(point), direction, 0, 10, False)
    body.AppendHybridShape(line)
    line.Name = "VerificationLine"
    part.Update()
    def read(doc, line):
        ref = doc.Part.CreateReferenceFromObject(line)
        measure = doc.GetWorkbench("SPAWorkbench").GetMeasurable(ref)
        return {"end_offset_mm": line.EndOffset.Value, "measured_length_mm": measure.Length}
    results = {"initial": read(doc, line)}
    line.EndOffset.Value = 20
    part.Update()
    results["updated"] = read(doc, line)
    doc.Save()
    doc.Close()
    reopened = app.Documents.Open(str(path))
    saved_line = reopened.Part.HybridBodies.Item("PythonVerification").HybridShapes.Item("VerificationLine")
    results["reopened"] = read(reopened, saved_line)
    reopened.Activate()
    app.Visible = True
    app.ActiveWindow.ActiveViewer.Reframe()
    reopened.Selection.Clear()
    reopened.Selection.Add(saved_line)
    app.ActiveWindow.ActiveViewer.Update()
    passed = all(abs(v - expected) < 0.000001 for stage, expected in [("initial", 10), ("updated", 20), ("reopened", 20)] for v in results[stage].values())
    report = {"client": app.FullName, "file": str(path), "results": results, "passed": passed}
    report["empty_structure"] = empty_structure
    report["baseline_sha256"] = hashlib.sha256(baseline.read_bytes()).hexdigest()
    report["built_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    if not passed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
