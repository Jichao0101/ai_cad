"""跨CLI进程验证检查失败、改参及确认状态；确认人仅为测试夹具。"""
import json,subprocess,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-confirmation-%Y%m%d-%H%M%S-%f')
    output.mkdir(parents=True)
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1]['requires_confirmation']=True
    config=output/'flow.json';config.write_text(json.dumps(definition),encoding='utf-8')
    count=0
    def call(command,request,success=True):
        nonlocal count
        count+=1
        path=output/(str(count)+'-'+command+'.json');path.write_text(json.dumps(request),encoding='utf-8')
        process=subprocess.run([sys.executable,'-X','utf8',str(root/'tools/steering_cli.py'),command,str(path)],
                               capture_output=True,text=True,encoding='utf-8')
        (output/(str(count)+'-stdout.txt')).write_text(process.stdout,encoding='utf-8')
        (output/(str(count)+'-stderr.txt')).write_text(process.stderr,encoding='utf-8')
        if not success:
            assert process.returncode!=0
            return process.stderr
        assert process.returncode==0,process.stderr
        return json.loads(process.stdout)
    state=call('start',{'flow':str(config),'runs_root':str(output),'parameters':{}})
    folder=Path(state['run_directory'])
    assert state['status']=='check_failed'
    assert 'pending_confirmation' not in state
    call('confirm',{'run_directory':str(folder),'expected_revision':state['revision'],
                   'fingerprint':'no valid report','confirmed_by':'AUTOMATED FIXTURE ONLY'},success=False)
    state=call('resume',{'run_directory':str(folder),'expected_revision':state['revision'],
                         'parameter_changes':{'thickness_mm':10}})
    assert state['status']=='waiting_confirmation'
    pending=state['pending_confirmation'];revision=state['revision']
    assert runtime.digest(folder/pending['report'])==pending['fingerprint']
    state=call('confirm',{'run_directory':str(folder),'expected_revision':revision,
                         'fingerprint':pending['fingerprint'],'confirmed_by':'AUTOMATED FIXTURE ONLY'})
    assert state['status']=='completed'
    assert len(state['attempts'])==2
    assert state['outputs']['baffle_part']['measurements']['volume_mm3']==24000
    before=(folder/'state.json').read_bytes()
    error=call('confirm',{'run_directory':str(folder),'expected_revision':revision,
                         'fingerprint':pending['fingerprint'],'confirmed_by':'AUTOMATED FIXTURE ONLY'},success=False)
    assert 'Stale revision' in error
    assert before==(folder/'state.json').read_bytes()
    report={'fixture_only':True,'passed':True,'statuses':['check_failed','waiting_confirmation','completed'],
            'stale_confirmation_rejected':True,'volume_mm3':24000,'attempt_count':2,
            'run_directory':str(folder),'confirmation_report':str(folder/pending['report'])}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
