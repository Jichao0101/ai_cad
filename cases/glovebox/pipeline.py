"""Historical glovebox sketch 701 -> up-to-plane pad 794.

Frozen placement uses the exported evaluated sketch frame. External sketch
constraints are NOT reconstructed. This is a new subset runner, not full replay.
"""
import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).parent / "handle_base"
PLAN = Path(__file__).parent / "pad_pipeline.json"

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def load_sources():
    records, fingerprints = {}, {}
    for number in (249, 671, 701, 794):
        path = next(SOURCE.glob(f"step_{number:04d}_*.json"))
        records[number] = json.loads(path.read_text(encoding="utf-8-sig"))
        fingerprints[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Verify the actual upstream identities rather than relying on step numbering.
    sketch, pad = records[701], records[794]
    valid = (
        records[671]["RECORD"]["id"] in sketch["DEPENDENCIES"]
        and sketch["RECORD"]["id"] in pad["DEPENDENCIES"]
        and records[249]["RECORD"]["id"] in pad["DEPENDENCIES"]
        and pad["DEFINITION"]["params"]["limit1"]["type"] == "UpToPlane"
        and pad["DEFINITION"]["params"]["profile_elements"][0]["id"] == sketch["RECORD"]["id"]
    )
    if not valid:
        raise ValueError("Historical source dependency contract changed")
    return records, fingerprints

def validate_request(request, plan):
    if set(request) - {"radius_candidates_mm", "minimum_volume_mm3", "check_source"}:
        raise ValueError("Unknown request fields")
    values = request.get("radius_candidates_mm", [])
    if not isinstance(values, list) or not 1 <= len(values) <= plan["max_attempts"]:
        raise ValueError("Supply 1..max_attempts radius candidates")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("Radius must be a finite positive number in mm")
    minimum = request.get("minimum_volume_mm3")
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum) or minimum <= 0:
        raise ValueError("A finite positive volume requirement is required")
    if not isinstance(request.get("check_source"), str) or not request["check_source"].strip():
        raise ValueError("Record requirement provenance; test rules are not DS")
    if plan["attempt_steps"] != [701, 794, "measure"] or plan["checkpoint_steps"] != [249, 671]:
        raise ValueError("Unsupported dependency order")

def create_checkpoint(app, records, path):
    doc = app.Documents.Add("Part")
    try:
        part = doc.Part
        supports = part.HybridBodies.Add()
        supports.Name = "HistoricalSupport"
        for number in (249, 671):
            frame = records[number]["DEFINITION"]["native_plane"]
            normal = frame["normal"]
            plane = part.HybridShapeFactory.AddNewPlaneEquation(*normal, sum(a*b for a,b in zip(normal, frame["origin_mm"])))
            supports.AppendHybridShape(plane)
            plane.Name = f"Source_{number}"
        body = part.Bodies.Add()
        body.Name = "A_block_set"
        part.Update()
        doc.SaveAs(str(path))
    finally:
        doc.Close()

def build_attempt(doc, records, radius):
    part = doc.Part
    supports = part.HybridBodies.Item("HistoricalSupport")
    body = part.Bodies.Item("A_block_set")
    if body.Shapes.Count or body.Sketches.Count:
        raise ValueError("Checkpoint contains attempt features")
    part.InWorkObject = body
    definition = records[701]["DEFINITION"]
    sketch = body.Sketches.Add(part.CreateReferenceFromObject(supports.HybridShapes.Item("Source_671")))
    sketch.Name = "Source_701"
    axis = definition["axis"]
    sketch.SetAbsoluteAxisData(tuple(axis["root"] + axis["h"] + axis["v"]))
    circle = definition["geometries"][definition["profile_geometry_indices"][0]]
    if circle["kind"] != "circle":
        raise ValueError("This runner requires the historical circular profile")
    factory = sketch.OpenEdition()
    factory.CreateClosedCircle(*circle["center"], radius)
    sketch.CloseEdition()
    part.Update()
    pad = part.ShapeFactory.AddNewPad(sketch, 20.0)
    pad.Name = "Source_794"
    pad.FirstLimit.LimitMode = 3
    pad.FirstLimit.LimitingElement = part.CreateReferenceFromObject(supports.HybridShapes.Item("Source_249"))
    part.Update()

def measure(doc):
    body = doc.Part.Bodies.Item("A_block_set")
    pad = body.Shapes.Item("Source_794")
    value = doc.GetWorkbench("SPAWorkbench").GetMeasurable(doc.Part.CreateReferenceFromObject(pad))
    return {"volume_mm3": value.Volume * 1e9, "area_mm2": value.Area * 1e6,
            "solid_features": body.Shapes.Count, "sketches": body.Sketches.Count,
            "limit_mode": pad.FirstLimit.LimitMode}

def expected_volume(records, radius):
    bottom = records[249]["DEFINITION"]["native_plane"]
    axis = records[701]["DEFINITION"]["axis"]
    normal = bottom["normal"]
    height = abs(sum(n*(a-b) for n,a,b in zip(normal, axis["root"], bottom["origin_mm"]))) / math.sqrt(sum(n*n for n in normal))
    return math.pi * radius * radius * height

def run(request, plan_path=PLAN, resume_run=None):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    validate_request(request, plan)
    records, fingerprints = load_sources()
    import win32com.client as com
    app = com.Dispatch("CATIA.Application")
    implementation_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if resume_run is None:
        folder = ROOT / "runs" / datetime.now().strftime("glovebox-pad-%Y%m%d-%H%M%S-%f")
        folder.mkdir(parents=True)
        report = {"run_dir": str(folder), "request": request, "plan": plan, "source_sha256": fingerprints,
                  "implementation_sha256": implementation_hash,
                  "client": app.FullName, "attempts": [], "status": "running", "ds_status": "not_evaluated",
                  "scope": "new subset runner; evaluated sketch placement frozen; external constraints not replayed"}
        write_json(folder / "request.json", request)
        write_json(folder / "plan.json", plan)
    else:
        folder = Path(resume_run).resolve(strict=True)
        if folder.parent != (ROOT / "runs").resolve() or not folder.name.startswith("glovebox-pad-"):
            raise ValueError("Resume target must be a direct glovebox run directory")
        report = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        if report["status"] != "no_solution":
            raise ValueError("Only an exhausted candidate batch can be resumed")
        if report["plan"] != plan or report["source_sha256"] != fingerprints or report.get("implementation_sha256") != implementation_hash:
            raise ValueError("Source, implementation or plan changed since checkpoint")
        if any(report["request"][k] != request[k] for k in ("minimum_volume_mm3", "check_source")):
            raise ValueError("Check conditions cannot change during recovery")
        if len(report["attempts"]) + len(request["radius_candidates_mm"]) > plan["max_attempts"]:
            raise ValueError("Total retry budget exhausted")
        report.setdefault("resumed_requests", []).append(request)
        report["status"] = "running"
    checkpoint = folder / "checkpoint.CATPart"
    try:
        if resume_run is None:
            create_checkpoint(app, records, checkpoint)
            checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            state = {"checkpoint_sha256": checkpoint_hash, "completed_steps": plan["checkpoint_steps"],
                     "source_sha256": fingerprints, "plan": plan, "attempt_features": []}
            write_json(folder / "checkpoint.json", state)
        else:
            state = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
            if state["source_sha256"] != fingerprints or state["plan"] != plan or state["completed_steps"] != plan["checkpoint_steps"]:
                raise ValueError("Checkpoint metadata changed")
            checkpoint_hash = state["checkpoint_sha256"]
        first_index = len(report["attempts"]) + 1
        for index, radius in enumerate(request["radius_candidates_mm"], first_index):
            if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != checkpoint_hash:
                raise ValueError("Checkpoint changed")
            path = folder / f"attempt-{index}.CATPart"
            shutil.copyfile(checkpoint, path)
            doc = app.Documents.Open(str(path))
            try:
                build_attempt(doc, records, radius)
                before = measure(doc)
                doc.Save()
            finally:
                doc.Close()
            doc = app.Documents.Open(str(path))
            try:
                after = measure(doc)
                expected = expected_volume(records, radius)
                geometry_ok = (abs(after["volume_mm3"] - expected) <= plan["volume_tolerance_mm3"]
                    and abs(before["volume_mm3"] - after["volume_mm3"]) <= plan["volume_tolerance_mm3"]
                    and after["solid_features"] == 1 and after["sketches"] == 1 and after["limit_mode"] == 3)
                if not geometry_ok:
                    raise ValueError("Geometry or persistence check failed; parameter retry is not allowed")
                passed = after["volume_mm3"] >= request["minimum_volume_mm3"]
                report["attempts"].append({"index": index, "radius_mm": radius, "file": str(path),
                    "restored_checkpoint_sha256": checkpoint_hash, "executed_steps": plan["attempt_steps"],
                    "before_reopen": before, "after_reopen": after, "expected_volume_mm3": expected,
                    "passed": passed, "reason": "volume_requirement_passed" if passed else "volume_below_requirement"})
                write_json(folder / f"attempt-{index}.json", report["attempts"][-1])
                write_json(folder / "result.json", report)
                if passed:
                    report["status"] = "passed"
                    report["final_file"] = str(path)
                    doc.Activate()
                    app.Visible = True
                    doc.Selection.Clear()
                    doc.Selection.Add(doc.Part.Bodies.Item("A_block_set").Shapes.Item("Source_794"))
                    app.ActiveWindow.ActiveViewer.Reframe()
                    break
            finally:
                if report["status"] != "passed":
                    doc.Close()
        if report["status"] == "running":
            report["status"] = "no_solution"
    except Exception as error:
        report["status"] = "execution_error"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        write_json(folder / "result.json", report)
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    result = run(json.loads(args.request.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=True), flush=True)
    raise SystemExit(0 if result["status"] == "passed" else 2)
