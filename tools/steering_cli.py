"""方向盘阶段命令行入口，JSON输入输出，不请求模型API。"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['describe','handover','start','inspect','resume','confirm','retry_inputs','retry'])
    parser.add_argument('request',type=Path)
    args=parser.parse_args();request=runtime.read(args.request)
    if args.command=='handover':
        from projects.steering_wheel import handover
        result=handover.export(request['run_directory'],request['expected_revision'],request['asset_id'],request['destination'])
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return
    if args.command=='describe':
        print(json.dumps(runtime.flow.describe(runtime.read(request['flow'])),ensure_ascii=False),flush=True)
        return
    if args.command=='start':
        folder,state=runtime.start(runtime.read(request['flow']),request.get('parameters',{}),request['runs_root'])
    else:
        folder=Path(request['run_directory'])
        if args.command=='inspect':state=runtime.read(folder/'state.json')
        elif args.command=='retry_inputs':state=runtime.retry_inputs(folder,request['expected_revision'])
        elif args.command=='retry':state=runtime.retry(folder,request['expected_revision'])
        elif args.command=='confirm':state=runtime.confirm(folder,request['expected_revision'],request['fingerprint'],request['confirmed_by'])
        else:state=runtime.resume(folder,request['expected_revision'],request['parameter_changes'])
    print(json.dumps({'run_directory':str(folder),**state},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
