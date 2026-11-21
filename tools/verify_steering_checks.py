"""实际CAD多项检查失败、同参候选恢复及历史报告留存。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-checks-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    step=definition['steps'][1];step.pop('check')
    step['checks']=[
        {'id':'volume','measurement':'volume_mm3','minimum':22000,'maximum':25000,
         'unit':'mm3','source':'mechanism fixture, not DS','version':'fixture-v1'},
        {'id':'thickness','measurement':'thickness_mm','minimum':9.5,'maximum':10.5,
         'unit':'mm','source':'mechanism fixture, not DS','version':'fixture-v1'}]
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    failed=state['check_reports']['baffle'].copy()
    failed_report=runtime.read(folder/failed['file'])
    assert [r['passed'] for r in failed_report['results']]==[False,False]
    basis=state['outputs']['basis'].copy()
    state=runtime.resume(folder,state['revision'],{'thickness_mm':10})
    assert state['status']=='completed',state.get('error')
    assert state['outputs']['basis']==basis
    passed=state['check_reports']['baffle']
    passed_report=runtime.read(folder/passed['file'])
    assert [r['passed'] for r in passed_report['results']]==[True,True]
    assert runtime.digest(folder/failed['file'])==failed['sha256']
    assert runtime.digest(folder/passed['file'])==passed['sha256']
    assert state['ds_status']=='not_evaluated'
    report={'fixture_only':True,'passed':True,'run_directory':str(folder),
            'failed':failed_report,'updated':passed_report,'recovery':state['recovery']}
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'report':str(output/'result.json'),'results':passed_report['results']}),flush=True)


if __name__=='__main__':main()
