"""注入一次技术异常后，通过独立CLI进程同参续跑真实CAD步骤。"""
import json,subprocess,sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-retry-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json');definition['steps'][1].pop('check')
    with patch.object(runtime.baffle,'create',side_effect=RuntimeError('INJECTED technical failure before feature creation')):
        folder,state=runtime.start(definition,{'thickness_mm':10},output)
    assert state['status']=='execution_error' and state['failed_step']=='baffle'
    retained=dict(state['outputs']['basis'])
    request=output/'retry.json';request.write_text(json.dumps({'run_directory':str(folder),'expected_revision':state['revision']}),encoding='utf-8')
    process=subprocess.run([sys.executable,'-X','utf8',str(root/'tools/steering_cli.py'),'retry',str(request)],capture_output=True,text=True,encoding='utf-8')
    assert process.returncode==0,process.stderr
    state=json.loads(process.stdout)
    assert state['status']=='completed',state.get('error')
    assert state['outputs']['basis']==retained
    assert state['recovery']['execute']==['baffle']
    assert len(state['attempts'])==2 and state['attempts'][0]==state['attempts'][1]
    assert abs(state['outputs']['baffle_part']['measurements']['volume_mm3']-24000)<1e-6
    report={'fixture_only':True,'fault_injected':True,'passed':True,'same_run':state['run_id']==folder.name,
            'retained_asset_unchanged':True,'attempts':len(state['attempts']),
            'measurements':state['outputs']['baffle_part']['measurements'],'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
