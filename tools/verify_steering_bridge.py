"""B45显式端部桥接的检查失败、局部恢复及原生保存重开验证。"""
import copy,json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-bridge-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['id']='b45-explicit-endpoint-fixture'
    definition['parameters']={'bridge_thickness_mm':{'default':5,'min':4,'max':8,'unit':'mm'}}
    definition['steps'][1]['parameters']['thickness_mm']=8.4
    definition['steps'][1].pop('check')
    specs=[{'center_mm':[0,0,z],'x':[1,0,0],'y':[0,1,0],'width_mm':20,
            'thickness_mm':{'parameter':'bridge_thickness_mm'}} for z in [0,40]]
    definition['steps'].append({'id':'bridge','operation':'rim_bridge','inputs':{'basis':'basis'},
        'output':'bridge_part','parameters':{'section_kind':'rectangle','sections':specs},
        'checks':[{'id':'fixture-volume','measurement':'volume_mm3','minimum':4500,'maximum':5000,
                   'unit':'mm3','source':'mechanism fixture only, not DS','version':'1'}]})
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    before=state['outputs']['bridge_part']['measurements']['volume_mm3']
    assert abs(before-4000)<1e-5
    retained={name:state['outputs'][name].copy() for name in ['basis','baffle_part']}
    state=runtime.resume(folder,state['revision'],{'bridge_thickness_mm':6})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['bridge']
    assert all(state['outputs'][name]==record and runtime.digest(folder/record['file'])==record['sha256'] for name,record in retained.items())
    after=state['outputs']['bridge_part']['measurements']['volume_mm3'];assert abs(after-4800)<1e-5
    _,clean=runtime.start(definition,{'bridge_thickness_mm':6},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['bridge_part']['measurements']['volume_mm3']-after)<1e-6
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['bridge_part']['file']))
    try:
        body=doc.Part.MainBody
        assert body.Shapes.Item('B45_Bridge').Name=='B45_Bridge'
        assert body.Sketches.Count==2
        reopened=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(body)).Volume*1e9
        assert abs(reopened-after)<1e-6
    finally:doc.Close()
    circular=copy.deepcopy(definition);circular['steps'][-1].pop('checks')
    circular['steps'][-1]['parameters']={'section_kind':'circle','sections':[
        {'center_mm':[0,0,z],'x':[1,0,0],'y':[0,1,0],'radius_mm':5} for z in [0,40]]}
    circular_folder,circular_state=runtime.start(circular,{},output)
    assert circular_state['status']=='completed',circular_state.get('error')
    circle_volume=circular_state['outputs']['bridge_part']['measurements']['volume_mm3']
    expected=math.pi*25*40
    report={'fixture_only':True,'passed':True,'ds_status':'not_evaluated','initial_volume_mm3':before,
        'updated_volume_mm3':after,'reopened_volume_mm3':reopened,'clean_build_matches':True,
        'retained_assets_unchanged':True,'native_loft_retained':True,'recovery':state['recovery'],
        'circle_volume_mm3':circle_volume,'circle_analytic_error_mm3':circle_volume-expected,
        'circle_strict_analytic_passed':abs(circle_volume-expected)<.001,
        'run_directory':str(folder),'circle_run_directory':str(circular_folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
