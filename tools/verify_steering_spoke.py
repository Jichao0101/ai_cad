"""三定位截面辐条：体积、对称厚度、重建及组合后参数历史验证。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,cad_frame


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-spoke-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1].pop('check')
    definition['steps'].extend([
        {'id':'spoke','operation':'spoke','inputs':{'basis':'basis'},'output':'spoke_part',
         'parameters':{'thickness_mm':{'parameter':'thickness_mm'},'sections':[
             {'center_mm':[0,0,0],'x':[1,0,0],'y':[0,1,0],'width_mm':20},
             {'center_mm':[0,0,30],'x':[1,0,0],'y':[0,1,0],'width_mm':30},
             {'center_mm':[10,0,60],'x':[1,0,0],'y':[0,1,0],'width_mm':20}]}},
        {'id':'union','operation':'combine','inputs':{'baffle':'baffle_part','spoke':'spoke_part'},
         'output':'union_part','parameters':{}}])
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    before=state['outputs']['spoke_part']['measurements']
    assert abs(before['volume_mm3']-12600)<.001,before
    assert before['half_thickness_mm']==4.2
    state=runtime.resume(folder,state['revision'],{'thickness_mm':10})
    assert state['status']=='completed',state.get('error')
    after=state['outputs']['spoke_part']['measurements']
    assert abs(after['volume_mm3']-15000)<.001,after
    assert after['half_thickness_mm']==5
    clean_folder,clean=runtime.start(definition,{'thickness_mm':10},output)
    assert clean['status']=='completed',clean.get('error')
    for name in ['spoke_part','union_part']:
        assert abs(clean['outputs'][name]['measurements']['volume_mm3']-state['outputs'][name]['measurements']['volume_mm3'])<1e-6
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['union_part']['file']))
    reopened_volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
    assert abs(reopened_volume-state['outputs']['union_part']['measurements']['volume_mm3'])<1e-6
    body=doc.Part.FindObjectByName('Stage_spoke')
    frames=[cad_frame.read(body.Sketches.Item('B50_Section_'+str(i))) for i in range(1,4)]
    assert frames[2]==[10,0,60,1,0,0,0,1,0],frames
    assert body.Shapes.Item('B60_Connection_4').Name=='B60_Connection_4'
    assert body.Shapes.Item('B60_Connection_5').Name=='B60_Connection_5'
    lower=doc.Part.FindObjectByName('B50_Section_1_Corner_0').Y.Value
    upper=doc.Part.FindObjectByName('B50_Section_1_Corner_2').Y.Value
    assert abs(lower+5)<1e-7 and abs(upper-5)<1e-7,(lower,upper)
    app.Visible=True;doc.Activate();app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'before':before,'after':after,'saved_frames':frames,
            'reopened_union_volume_mm3':reopened_volume,'saved_thickness_bounds_mm':[lower,upper],
            'recovery':state['recovery'],'clean_build_matches':True,'passed':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
