"""原生圆角的显式边选择、固定检查恢复、原生改参及保存重开。"""
import copy,json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-fillet-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['parameters']={'radius_mm':{'default':1,'min':.5,'max':3,'unit':'mm'}}
    definition['steps'][1]['parameters']={'outline':[[0,0],[20,0],[20,20],[0,20]],'thickness_mm':20}
    definition['steps'][1].pop('check')
    definition['steps'].append({'id':'round','operation':'edge_fillet','inputs':{'source':'baffle_part'},'output':'rounded_part',
        'parameters':{'radius_mm':{'parameter':'radius_mm'},'edge_endpoints_mm':[[0,0,0],[0,0,20]]},
        'checks':[{'id':'fixture-material-removal','measurement':'removed_volume_mm3','minimum':15,'maximum':25,
                   'unit':'mm3','source':'mechanism fixture only, not DS or CAE','version':'1'}]})
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['rounded_part']['measurements']
    assert abs(initial['removed_volume_mm3']-20*(1-math.pi/4))<1e-5
    retained={name:state['outputs'][name].copy() for name in ['basis','baffle_part']}
    state=runtime.resume(folder,state['revision'],{'radius_mm':2})
    assert state['status']=='completed',state.get('error')
    result=state['outputs']['rounded_part']['measurements']
    assert state['recovery']['execute']==['round']
    assert abs(result['removed_volume_mm3']-80*(1-math.pi/4))<1e-5
    assert all(state['outputs'][name]==record and runtime.digest(folder/record['file'])==record['sha256'] for name,record in retained.items())
    _,clean=runtime.start(definition,{'radius_mm':2},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['rounded_part']['measurements']['volume_mm3']-result['volume_mm3'])<1e-6
    app=win32com.client.GetActiveObject('CATIA.Application')
    path=folder/state['outputs']['rounded_part']['file'];doc=app.Documents.Open(str(path))
    try:
        feature=doc.Part.MainBody.Shapes.Item(result['feature_name']);assert feature.Radius.Value==2
        assert doc.Part.MainBody.Shapes.Item('B20_Thickness').FirstLimit.Dimension.Value==20
        spa=doc.GetWorkbench('SPAWorkbench')
        reopened=spa.GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
        assert abs(reopened-result['volume_mm3'])<1e-6
        feature.Radius.Value=2.5;doc.Part.Update()
        edited=spa.GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
        assert abs(edited-(8000-125*(1-math.pi/4)))<1e-5
        doc.SaveAs(str(output/'EditedRadius.CATPart'))
    finally:doc.Close()
    assert runtime.digest(path)==state['outputs']['rounded_part']['sha256']
    bad=copy.deepcopy(definition);bad['steps'][-1]['parameters']['edge_endpoints_mm']=[[0,0,0],[0,0,21]]
    _,bad_state=runtime.start(bad,{},output)
    assert bad_state['status']=='execution_error' and 'one matching straight edge' in bad_state['error']
    assert 'rounded_part' not in bad_state['outputs']
    report={'fixture_only':True,'passed':True,'initial':initial,'updated':result,
        'reopened_volume_mm3':reopened,'native_edited_volume_mm3':edited,'clean_build_matches':True,
        'retained_assets_unchanged':True,'missing_edge_rejected':True,'recovery':state['recovery'],'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
