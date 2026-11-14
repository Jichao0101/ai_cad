"""JSON command interface; no Agent/model dependency."""
import argparse
import json
import os
import sys
from pathlib import Path
import executor
import automatic

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["workflow","start","inspect","resume"])
    parser.add_argument("--request",type=Path)
    parser.add_argument("--workspace",type=Path,default=Path(__file__).resolve().parent/"runs")
    args=parser.parse_args()
    try:
        request=executor.read_json(args.request) if args.request else {}
        result=automatic.dispatch(args.command,request,args.workspace)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return 3 if result.get("status")=="execution_error" else (2 if result.get("status") in ("check_failed","needs_input") else 0)
    except Exception as error:
        print(json.dumps({"status":"rejected" if isinstance(error,ValueError) else "execution_error", "error":str(error),"process_id":os.getpid()},ensure_ascii=False),flush=True)
        return 3

if __name__=="__main__":
    raise SystemExit(main())
