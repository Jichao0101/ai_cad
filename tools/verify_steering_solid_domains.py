"""主Body STEP实体域检查：分离失败、改参贴面、空腔和辅助Body隔离。"""
import copy,json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,solid_domains,baffle


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-solid-domains-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['parameters']={'start_x':{'default':20,'min':5,'max':20,'unit':'mm'}}
    definition['steps'][1]['parameters']={'outline':[[0,0],[10,0],[10,10],[0,10]],'thickness_mm':10}
    definition['steps'][1].pop('check')
    definition['steps'].extend([
        {'id':'second','operation':'baffle','inputs':{'basis':'basis'},'output':'second_part',
         'parameters':{'outline':[[{'parameter':'start_x'},0],[30,0],[30,10],[{'parameter':'start_x'},10]],'thickness_mm':10}},
        {'id':'union','operation':'combine','inputs':{'first':'baffle_part','second':'second_part'},'output':'union_part','parameters':{}},
        {'id':'domains','operation':'solid_domains','inputs':{'source':'union_part'},'output':'step_evidence','parameters':{},
         'checks':[{'id':'single-step-solid','measurement':'step_solid_count','minimum':1,'maximum':1,
                    'unit':'count','source':'mechanism fixture, STEP export only, not DS','version':'1'}]}])
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['step_evidence']['measurements'];assert initial['step_solid_count']==2
    retained={name:state['outputs'][name].copy() for name in ['basis','baffle_part']}
    state=runtime.resume(folder,state['revision'],{'start_x':10})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['second','union','domains']
    after=state['outputs']['step_evidence']['measurements'];assert after['step_solid_count']==1
    assert all(state['outputs'][name]==record and runtime.digest(folder/record['file'])==record['sha256'] for name,record in retained.items())
    _,clean=runtime.start(definition,{'start_x':10},output)
    assert clean['status']=='completed',clean.get('error')
    assert clean['outputs']['step_evidence']['measurements']==after
    app=win32com.client.GetActiveObject('CATIA.Application')
    source=folder/state['outputs']['union_part']['file'];doc=app.Documents.Open(str(source))
    try:
        original=doc.Part.MainBody;aux=doc.Part.Bodies.Add();doc.Part.MainBody=aux
        baffle.create(doc,[[100,0],[110,0],[110,10],[100,10]],[0,0,0,1,0,0,0,1,0],10)
        doc.Part.MainBody=original;decoy=output/'AuxiliaryBody.CATPart';doc.SaveAs(str(decoy))
    finally:doc.Close()
    isolated=solid_domains.measure(app,decoy,output/'isolated.stp')
    assert isolated['step_solid_count']==1 and abs(isolated['copied_volume_mm3']-3000)<1e-5
    assert runtime.digest(source)==state['outputs']['union_part']['sha256']
    cavity=copy.deepcopy(definition);cavity['steps']=cavity['steps'][:2]
    shifted=copy.deepcopy(cavity['steps'][0]);shifted.update(id='inner_basis',output='inner_basis')
    shifted['parameters']['bottom_point']=[0,0,2]
    cavity['steps'].extend([shifted,{'id':'inner','operation':'baffle','inputs':{'basis':'inner_basis'},'output':'inner_part',
        'parameters':{'outline':[[2,2],[8,2],[8,8],[2,8]],'thickness_mm':6}},
        {'id':'cavity','operation':'subtract','inputs':{'stock':'baffle_part','tool':'inner_part'},'output':'cavity_part','parameters':{}},
        {'id':'domains','operation':'solid_domains','inputs':{'source':'cavity_part'},'output':'step_evidence','parameters':{}}])
    _,cavity_state=runtime.start(cavity,{},output)
    assert cavity_state['status']=='completed',cavity_state.get('error')
    cavity_result=cavity_state['outputs']['step_evidence']['measurements']
    assert cavity_result['step_solid_count']==1 and cavity_result['step_closed_shell_count']==2
    assert abs(cavity_result['source_volume_mm3']-784)<1e-5
    report={'fixture_only':True,'passed':True,'initial':initial,'updated':after,'cavity':cavity_result,
        'auxiliary_body_isolated':True,'source_unchanged':True,'clean_build_matches':True,
        'recovery':state['recovery'],'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
