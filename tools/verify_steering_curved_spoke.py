"""样条辐条边界改参、镜像/组合、未变轮圈保留及干净构建对照。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-curved-spoke-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_skeleton_flow.json')
    definition['parameters']['bend_mm']={'default':3,'min':0,'max':8,'unit':'mm'}
    step=next(s for s in definition['steps'] if s['id']=='spoke')
    step['parameters']['guide_bends_mm']=[[{'parameter':'bend_mm'},0,0],[0,0,0]]
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    before=state['outputs']['half_spoke']['measurements']
    retained={key:dict(state['outputs'][key]) for key in ['basis','baffle_part','rim_part']}
    state=runtime.resume(folder,state['revision'],{'bend_mm':6})
    assert state['status']=='completed',state.get('error')
    after=state['outputs']['half_spoke']['measurements']
    assert after['guide_length_mm']>before['guide_length_mm']
    assert after['area_mm2']>before['area_mm2']
    assert all(state['outputs'][key]==value for key,value in retained.items())
    assert state['recovery']['execute']==['spoke','spoke_mirror','union']
    clean_folder,clean=runtime.start(definition,{'bend_mm':6},output)
    assert clean['status']=='completed',clean.get('error')
    for key in ['half_spoke','skeleton_part']:
        assert abs(clean['outputs'][key]['measurements']['volume_mm3']-state['outputs'][key]['measurements']['volume_mm3'])<1e-6
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['skeleton_part']['file']))
    part=doc.Part
    bend=part.FindObjectByName('B60_Bend_4_0')
    assert abs(bend.X.Value-6)<1e-7
    assert part.FindObjectByName('B60_Guide_4_0').GetNbControlPoint()==3
    volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
    assert abs(volume-state['outputs']['skeleton_part']['measurements']['volume_mm3'])<1e-6
    doc.Activate();app.Visible=True;app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'passed':True,'before':before,'after':after,'native_bend_mm':bend.X.Value,
            'reopened_volume_mm3':volume,'unaffected_branches_retained':True,'clean_build_matches':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
