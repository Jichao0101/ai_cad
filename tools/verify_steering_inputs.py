"""真实CATPart输入：缺文件等待、同运行补齐、对象校核及原件不变。"""
import copy,json,shutil,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-inputs-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1].pop('check')
    seed_folder,seed=runtime.start(definition,{},output)
    assert seed['status']=='completed',seed.get('error')
    original=seed_folder/seed['outputs']['baffle_part']['file']
    expected=runtime.digest(original)
    supplied=output/'SuppliedPlatformFixture.CATPart'
    manifest={'path':str(supplied),'sha256':expected,'unit':'mm','coordinate_system':'design_global',
              'objects':{'body':[{'collection':'Bodies','name':'B20_Baffle'}],
                         'pad':[{'collection':'Bodies','name':'B20_Baffle'},{'collection':'Shapes','name':'B20_Thickness'}]}}
    definition['external_objects']={'platform':manifest}
    definition['steps'].append({'id':'union','operation':'combine','inputs':{'platform':'platform','baffle':'baffle_part'},
                                'output':'union_part','parameters':{}})
    folder,state=runtime.start(definition,{'thickness_mm':10},output)
    assert state['status']=='needs_input' and not state['completed']
    try:runtime.resume(folder,state['revision'],{'thickness_mm':11})
    except ValueError as error:assert 'retry_inputs' in str(error)
    else:raise AssertionError('Missing input was bypassed')
    shutil.copyfile(original,supplied)
    state=runtime.retry_inputs(folder,state['revision'])
    assert state['status']=='completed',state.get('error') or state.get('input_issues')
    assert len(state['attempts'])==1
    assert abs(state['outputs']['union_part']['measurements']['volume_mm3']-24000)<1e-6
    assert runtime.digest(original)==expected==runtime.digest(supplied)
    assert state['outputs']['platform']['sha256']==expected
    assert (folder/state['outputs']['platform']['file']).resolve()!=supplied.resolve()
    bad=copy.deepcopy(definition)
    bad['external_objects']['platform']['objects']['body'][0]['name']='MissingBody'
    bad_folder,bad_state=runtime.start(bad,{},output)
    assert bad_state['status']=='needs_input' and not bad_state['completed']
    assert any(i.get('binding')=='body' and i['category']=='input_object' for i in bad_state['input_issues'])
    report={'fixture_only':True,'passed':True,'missing_input_resumed_same_run':True,
            'unknown_object_rejected':True,'original_sha256':expected,'source_unchanged':True,
            'attempt_count':len(state['attempts']),'volume_mm3':24000,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
