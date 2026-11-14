"""Persistent, revision-checked CAD execution. Each command may be a new process."""
import copy
import hashlib
import json
import math
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
import operations as cad

ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path, value):
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temp,path)

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def identity():
    return {p.name:digest(p) for p in sorted(cad.HOME.glob("*.py"))} | {"assets/manifest.json":digest(cad.HOME/"assets/manifest.json"),"pipeline.json":digest(cad.HOME/"pipeline.json")}

def fields(value, required):
    if not isinstance(value,dict) or set(value)!=set(required):
        raise ValueError("Expected fields: " + ", ".join(required))

def number(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and value>0

def policy_valid(policy):
    fields(policy,["radius_min_mm","radius_max_mm","minimum_volume_mm3","check_source"])
    if not all(number(policy[k]) for k in ("radius_min_mm","radius_max_mm","minimum_volume_mm3")) or policy["radius_min_mm"]>policy["radius_max_mm"]:
        raise ValueError("Invalid fixed policy bounds")
    if not isinstance(policy["check_source"],str) or not policy["check_source"].strip():
        raise ValueError("Check provenance is required")

@contextmanager
def lock(folder):
    import msvcrt
    with (folder/"run.lock").open("a+b") as stream:
        stream.seek(0,2)
        if stream.tell()==0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:
            raise ValueError("Run is busy; do not retry a mutation until its outcome is known") from error
        try:
            yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def view(state):
    return {"run_id":state["run_id"],"revision":state["revision"],"status":state["status"],
            "completed_steps":[s["id"] for s in state["steps"]],"available_outputs":state["objects"],
            "recoverable_before_steps":[s["id"] for s in state["steps"]],
            "remaining_builds":4-state["builds"],"policy":state["policy"],"check":state.get("check"),
            "process_id":os.getpid()}

def snapshot(folder, path, state):
    token=uuid.uuid4().hex
    state["checkpoints"][token]={"model":str(path.relative_to(folder)),"sha256":digest(path),
        "steps":copy.deepcopy(state["steps"]),"objects":copy.deepcopy(state["objects"])}
    state["checkpoint"]=token

def model_path(folder,state,token=None):
    item=state["checkpoints"][token or state["checkpoint"]]
    path=(folder/item["model"]).resolve(strict=True)
    if path.parent!=(folder/"snapshots").resolve() or digest(path)!=item["sha256"]:
        raise ValueError("Checkpoint file changed or escaped run directory")
    return path

def publish(folder,state,action,details):
    state["revision"]+=1
    event={"action":action,"details":details,**view(state)}
    write_json(folder/"events"/f"revision-{state['revision']:04d}.json",event)
    write_json(folder/"state.json",state)
    return event

def start(workspace,request):
    fields(request,["policy"]);policy_valid(request["policy"])
    cad.sources()
    run_id="run-"+uuid.uuid4().hex
    folder=workspace/run_id
    (folder/"snapshots").mkdir(parents=True);(folder/"events").mkdir()
    state={"run_id":run_id,"revision":0,"status":"ready","policy":request["policy"],"identity":identity(),
        "steps":[],"objects":{},"checkpoints":{},"builds":0,"check":None}
    app=cad.connect();path=folder/"snapshots"/"initial.CATPart"
    cad.create_empty(app,path)
    snapshot(folder,path,state)
    write_json(folder/"state.json",state)
    write_json(folder/"events"/"revision-0000.json",{"action":"start",**view(state)})
    return view(state)

def validate_steps(steps,state):
    if not isinstance(steps,list) or not 1<=len(steps)<=8:
        raise ValueError("Supply 1..8 operations per stage")
    objects=copy.deepcopy(state["objects"]);ids={s["id"] for s in state["steps"]}
    builds=state["builds"]
    for step in steps:
        fields(step,["id","operation","inputs","parameters","output"])
        if any(not isinstance(step[k],str) or not ID.fullmatch(step[k]) for k in ("id","output")):
            raise ValueError("Step/output identifiers must be simple ASCII names")
        if step["id"] in ids or step["output"] in objects:
            raise ValueError("Step/output already exists; restore before editing")
        op=step["operation"]
        if op not in cad.CATALOG:
            raise ValueError("Unknown operation")
        fields(step["inputs"],cad.CATALOG[op]["inputs"])
        fields(step["parameters"],cad.CATALOG[op]["parameters"])
        for role,kind in cad.CATALOG[op]["inputs"].items():
            ref=step["inputs"][role]
            if not isinstance(ref,str) or ref not in objects:
                raise ValueError("Missing dependency: " + str(ref))
            obj=objects[ref];parts=kind.split(":")
            if obj["type"]!=parts[0] or (len(parts)>1 and obj["source_step"]!=int(parts[1])):
                raise ValueError("Wrong dependency type or historical support: " + ref)
        if op=="create_reference_plane":
            source=step["parameters"]["source_step"]
            if isinstance(source,bool) or source not in (249,671):
                raise ValueError("Unsupported source plane")
            meta={"type":"plane","source_step":source}
        elif op=="create_circle_sketch":
            radius=step["parameters"]["radius_mm"]
            if not number(radius) or not state["policy"]["radius_min_mm"]<=radius<=state["policy"]["radius_max_mm"]:
                raise ValueError("Radius outside fixed bounds")
            meta={"type":"sketch","source_step":701}
        else:
            builds+=1
            if builds>4 or any(o["type"]=="solid" for o in objects.values()):
                raise ValueError("Solid already exists or total build budget exhausted")
            meta={"type":"solid","source_step":794}
        objects[step["output"]]=meta;ids.add(step["id"])

def execute(folder,state,steps):
    if state["status"]!="ready":
        raise ValueError("Restore before changing an inspected build")
    validate_steps(steps,state)
    records=cad.sources();app=cad.connect()
    baseline=model_path(folder,state);cad.assert_saved(app,baseline)
    work=folder/"snapshots"/("stage-"+uuid.uuid4().hex+".CATPart")
    shutil.copyfile(baseline,work)
    pending=copy.deepcopy(state)
    doc=app.Documents.Open(str(work))
    alerts=app.DisplayFileAlerts;app.DisplayFileAlerts=False
    try:
        for step in steps:
            before=pending["checkpoint"]
            obj=cad.execute(doc,step,pending["objects"],records)
            pending["objects"][step["output"]]=obj
            pending["steps"].append({**step,"before_checkpoint":before,
                "depends_on":[pending["objects"][v]["producer_step"] for v in step["inputs"].values()]})
            if obj["type"]=="solid":pending["builds"]+=1
            path=folder/"snapshots"/("step-"+uuid.uuid4().hex+".CATPart")
            doc.SaveAs(str(path))
            snapshot(folder,path,pending)
    except Exception as error:
        write_json(folder/"events"/("failed-"+uuid.uuid4().hex+".json"),{
            "action":"execute","revision":state["revision"],"steps":steps,"rolled_back":True,"error":str(error)})
        raise
    finally:
        try:doc.Close()
        finally:app.DisplayFileAlerts=alerts
    pending["check"]=None
    return publish(folder,pending,"execute",{"executed_steps":[s["id"] for s in steps]})

def inspect(folder,state,target,checks):
    if checks!=["minimum_volume"] or target not in state["objects"] or state["objects"][target]["type"]!="solid":
        raise ValueError("Inspect requires a solid and minimum_volume check")
    app=cad.connect();path=model_path(folder,state);cad.assert_saved(app,path)
    doc=app.Documents.Open(str(path))
    try:
        measurement=cad.measure(doc,state["objects"],target,cad.sources())
        passed=measurement["volume_mm3"]>=state["policy"]["minimum_volume_mm3"]
        profile=state["objects"][target]["profile"]
        state["check"]={"check_id":"minimum_volume","target":target,"passed":passed,"measurement":measurement,
            "required_mm3":state["policy"]["minimum_volume_mm3"],"reason":"passed" if passed else "volume_below_requirement",
            "upstream_parameter_steps":[state["objects"][profile]["producer_step"]],"ds_status":"not_evaluated"}
        state["status"]="passed" if passed else "check_failed"
        if passed:
            app.Visible=True;doc.Activate();doc.Selection.Clear()
            doc.Selection.Add(cad.object_for(doc,state["objects"][target]));app.ActiveWindow.ActiveViewer.Reframe()
    finally:
        if state["status"]!="passed":doc.Close()
    return publish(folder,state,"inspect",{"snapshot":str(path)})

def restore(folder,state,before_step):
    match=next((s for s in state["steps"] if s["id"]==before_step),None)
    if match is None:raise ValueError("No checkpoint before this executed step")
    app=cad.connect();cad.assert_saved(app,model_path(folder,state))
    token=match["before_checkpoint"];path=model_path(folder,state,token)
    # Reopen the selected checkpoint to ensure it remains usable in this CATIA session.
    doc=app.Documents.Open(str(path));doc.Close()
    checkpoint=state["checkpoints"][token]
    kept={s["id"] for s in checkpoint["steps"]}
    removed=[s["id"] for s in state["steps"] if s["id"] not in kept]
    state["steps"]=copy.deepcopy(checkpoint["steps"])
    state["objects"]=copy.deepcopy(checkpoint["objects"])
    state["checkpoint"]=token;state["check"]=None;state["status"]="ready"
    return publish(folder,state,"restore",{"before_step":before_step,"invalidated_steps":removed,"checkpoint_sha256":checkpoint["sha256"]})

