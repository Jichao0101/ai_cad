"""Development acceptance harness only. Never included in the delivery package."""
import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/"delivery/glovebox"
COMMANDS={"get_workflow":"workflow","start_build":"start","inspect_build":"inspect","resume_build":"resume"}

def object_schema(properties):
    return {"type":"object","properties":properties,"required":list(properties),"additionalProperties":False}

def tools():
    string={"type":"string"};revision={"type":"integer"}
    common={"run_id":string,"expected_revision":revision}
    parameter_map={"type":"object","properties":{"radius_mm":{"type":"number"}},"additionalProperties":False}
    schemas={"get_workflow":{},"start_build":{"parameters":parameter_map},
        "inspect_build":{"run_id":string},"resume_build":{**common,"parameter_changes":parameter_map}}
    descriptions={"get_workflow":"Read the predefined pipeline and parameter defaults.",
        "start_build":"Run the entire pipeline automatically with fixed caller policy until pass or decision needed.",
        "inspect_build":"Read committed status without modifying CAD.",
        "resume_build":"Submit parameter changes only; executor computes rollback and reruns affected steps."}
    return [{"type":"function","function":{"name":name,"description":descriptions[name],"parameters":object_schema(schema)}} for name,schema in schemas.items()]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError("Redirects disabled")

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--policy",type=Path,required=True)
    parser.add_argument("--allow-cloud",action="store_true")
    args=parser.parse_args()
    policy=json.loads(args.policy.read_text(encoding="utf-8-sig"))
    env_path=ROOT/".env.local"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                k,v=line.split("=",1);os.environ.setdefault(k.strip(),v.strip().strip(chr(34)).strip(chr(39)))
    endpoint=os.environ.get("QWEN_BASE_URL","").rstrip("/");model=os.environ.get("QWEN_MODEL","")
    url=urlparse(endpoint)
    if not model or not url.hostname or url.username or url.password or url.query or url.fragment:parser.error("Invalid model endpoint")
    local=url.hostname in ("localhost","127.0.0.1","::1")
    if url.scheme not in ("http","https") or (not local and (not args.allow_cloud or url.scheme!="https")):parser.error("Public model requires HTTPS and --allow-cloud")
    skill=(PACKAGE/"skill/glovebox-design/SKILL.md").read_text(encoding="utf-8")
    folder=ROOT/"runs"/datetime.now().strftime("qwen-automatic-%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True)
    messages=[{"role":"system","content":skill+"\nFixed caller policy: "+json.dumps(policy,ensure_ascii=False)}, {"role":"user","content":args.prompt}]
    transcript={"model":model,"skill_sha256":hashlib.sha256(skill.encode()).hexdigest(),"policy":policy,"commands":[],"messages":messages}
    opener=urllib.request.build_opener(NoRedirect)
    owned_run=None;latest=None;call_count=0
    try:
        for turn in range(24):
            data={"model":model,"messages":messages,"tools":tools(),"tool_choice":"auto"}
            req=urllib.request.Request(endpoint+"/chat/completions",data=json.dumps(data).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ.get("QWEN_API_KEY","")})
            with opener.open(req,timeout=90) as response:
                message=json.load(response)["choices"][0]["message"]
            messages.append({k:message[k] for k in ("role","content","tool_calls") if k in message})
            calls=message.get("tool_calls") or []
            if not calls:
                transcript["final_state"]=latest
                print(json.dumps({"status":latest.get("status") if latest else "not_executed","run_id":owned_run,"acceptance_dir":str(folder),"assistant":message.get("content")},ensure_ascii=False),flush=True)
                return 0 if latest and latest.get("status")=="passed" else 2
            for call in calls:
                call_count+=1
                if call_count>24:raise ValueError("Tool call budget exhausted")
                name=call["function"]["name"]
                if name not in COMMANDS:raise ValueError("Unknown tool")
                request=json.loads(call["function"]["arguments"])
                command=COMMANDS[name]
                if command=="workflow" and request:raise ValueError("Tool takes no model-specified fields")
                if command=="start":
                    if owned_run:raise ValueError("Only one run per acceptance session")
                    if set(request)!={"parameters"}:raise ValueError("Start requires parameters only")
                    request={"policy":policy,"parameters":request["parameters"]}
                if command not in ("workflow","start") and (not owned_run or request.get("run_id")!=owned_run):raise ValueError("Tool may only access this session's run")
                path=folder/f"request-{call_count:03d}.json";path.write_text(json.dumps(request,ensure_ascii=False),encoding="utf-8")
                process=subprocess.run([sys.executable,"-X","utf8",str(PACKAGE/"cad_cli.py"),command,"--request",str(path),"--workspace",str(folder/"builds")],capture_output=True,text=True,encoding="utf-8",timeout=120)
                result=json.loads(process.stdout)
                transcript["commands"].append({"tool":name,"command":command,"request":request,"result":result,"exit_code":process.returncode})
                if command=="start" and result.get("run_id"):owned_run=result["run_id"]
                if result.get("run_id"):latest=result
                # No source geometry or CAD file contents are sent to the model.
                returned=copy.deepcopy(result)
                if "snapshot" in returned.get("details",{}):returned["details"]["snapshot"]="local CAD artifact saved"
                messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(returned,ensure_ascii=False)})
                (folder/"transcript.json").write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding="utf-8")
        raise RuntimeError("Model turn budget exhausted")
    finally:
        (folder/"transcript.json").write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":raise SystemExit(main())
