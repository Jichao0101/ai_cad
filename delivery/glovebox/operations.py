"""Deterministic CAD operations; no model calls or workflow orchestration."""
import hashlib
import json
import math
from pathlib import Path

HOME = Path(__file__).resolve().parent
CATALOG = {
    "create_reference_plane": {"inputs": {}, "parameters": {"source_step": [249, 671]}, "output_type": "plane"},
    "create_circle_sketch": {"inputs": {"support": "plane:671"}, "parameters": {"radius_mm": "number within fixed policy"}, "output_type": "sketch"},
    "create_pad_up_to_plane": {"inputs": {"profile": "sketch", "limit": "plane:249"}, "parameters": {}, "output_type": "solid"},
}

def sources():
    manifest = json.loads((HOME / "assets/manifest.json").read_text(encoding="utf-8"))
    records = {}
    for number, entry in manifest.items():
        path = HOME / "assets" / entry["file"]
        if path.parent != HOME / "assets" or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Source asset fingerprint mismatch")
        records[int(number)] = json.loads(path.read_text(encoding="utf-8-sig"))
    if records[671]["RECORD"]["id"] not in records[701]["DEPENDENCIES"] or any(records[n]["RECORD"]["id"] not in records[794]["DEPENDENCIES"] for n in (249,701)):
        raise ValueError("Historical dependency mismatch")
    return records

def connect():
    import win32com.client
    return win32com.client.Dispatch("CATIA.Application")

def create_empty(app, path):
    doc = app.Documents.Add("Part")
    try:
        doc.Part.HybridBodies.Add().Name = "Supports"
        doc.Part.Bodies.Add().Name = "BuildBody"
        doc.Part.Update()
        doc.SaveAs(str(path))
    finally:
        doc.Close()

def object_for(doc, record):
    if record["type"] == "plane":
        return doc.Part.HybridBodies.Item("Supports").HybridShapes.Item(record["name"])
    body = doc.Part.Bodies.Item("BuildBody")
    return (body.Sketches if record["type"] == "sketch" else body.Shapes).Item(record["name"])

def assert_saved(app, path):
    for i in range(1, app.Documents.Count + 1):
        doc = app.Documents.Item(i)
        try:
            matches = Path(doc.FullName).resolve() == path.resolve()
        except Exception:
            continue
        if matches and not doc.Saved:
            raise ValueError("Run snapshot has unsaved manual edits; review before continuing")

def execute(doc, step, objects, records):
    part = doc.Part
    operation = step["operation"]
    name = "obj_" + step["output"]
    if operation == "create_reference_plane":
        number = step["parameters"]["source_step"]
        frame = records[number]["DEFINITION"]["native_plane"]
        normal = frame["normal"]
        obj = part.HybridShapeFactory.AddNewPlaneEquation(*normal, sum(a*b for a,b in zip(normal,frame["origin_mm"])))
        part.HybridBodies.Item("Supports").AppendHybridShape(obj)
        result = {"type":"plane", "source_step":number}
    elif operation == "create_circle_sketch":
        body = part.Bodies.Item("BuildBody")
        part.InWorkObject = body
        support = object_for(doc,objects[step["inputs"]["support"]])
        obj = body.Sketches.Add(part.CreateReferenceFromObject(support))
        definition = records[701]["DEFINITION"]
        axis = definition["axis"]
        obj.SetAbsoluteAxisData(tuple(axis["root"]+axis["h"]+axis["v"]))
        circle = definition["geometries"][definition["profile_geometry_indices"][0]]
        factory = obj.OpenEdition()
        factory.CreateClosedCircle(*circle["center"],step["parameters"]["radius_mm"])
        obj.CloseEdition()
        result = {"type":"sketch", "source_step":701,"radius_mm":step["parameters"]["radius_mm"]}
    else:
        body = part.Bodies.Item("BuildBody")
        part.InWorkObject = body
        sketch = object_for(doc,objects[step["inputs"]["profile"]])
        plane = object_for(doc,objects[step["inputs"]["limit"]])
        obj = part.ShapeFactory.AddNewPad(sketch,20.0)
        obj.FirstLimit.LimitMode = 3
        obj.FirstLimit.LimitingElement = part.CreateReferenceFromObject(plane)
        result = {"type":"solid","source_step":794,"profile":step["inputs"]["profile"],"limit":step["inputs"]["limit"]}
    obj.Name = name
    part.Update()
    return {**result,"name":name,"producer_step":step["id"]}

def measure(doc, objects, target, records):
    solid = objects[target]
    obj = object_for(doc,solid)
    value = doc.GetWorkbench("SPAWorkbench").GetMeasurable(doc.Part.CreateReferenceFromObject(obj))
    radius = objects[solid["profile"]]["radius_mm"]
    bottom = records[249]["DEFINITION"]["native_plane"]
    origin = records[701]["DEFINITION"]["axis"]["root"]
    normal = bottom["normal"]
    height = abs(sum(n*(a-b) for n,a,b in zip(normal,origin,bottom["origin_mm"]))) / math.sqrt(sum(n*n for n in normal))
    expected = math.pi * radius * radius * height
    volume = value.Volume*1e9
    if not math.isfinite(volume) or abs(volume-expected)>0.001 or obj.FirstLimit.LimitMode != 3:
        raise ValueError("Geometry consistency check failed")
    body = doc.Part.Bodies.Item("BuildBody")
    if body.Shapes.Count != sum(v["type"]=="solid" for v in objects.values()) or body.Sketches.Count != sum(v["type"]=="sketch" for v in objects.values()):
        raise ValueError("Unexpected feature residue")
    return {"volume_mm3":volume,"area_mm2":value.Area*1e6,"radius_mm":radius,"expected_volume_mm3":expected,"solid_features":body.Shapes.Count,"sketches":body.Sketches.Count,"limit_mode":obj.FirstLimit.LimitMode}
