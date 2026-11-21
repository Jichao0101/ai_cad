"""混合原生特征组合夹具；不代表实际CAS骨架验收。"""
import json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-skeleton-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_skeleton_flow.json')
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    original=dict(state['outputs']['spoke_part']);baffle=dict(state['outputs']['baffle_part'])
    assert abs(state['outputs']['rim_part']['measurements']['volume_mm3']-2*math.pi**2*100*25)<.001
    state=runtime.resume(folder,state['revision'],{'section_radius_mm':5.5})
    assert state['status']=='completed',state.get('error')
    assert state['outputs']['spoke_part']==original and state['outputs']['baffle_part']==baffle
    assert state['recovery']['execute']==['rim','rim_mirror','union']
    clean_folder,clean=runtime.start(definition,{'section_radius_mm':5.5},output)
    assert clean['status']=='completed',clean.get('error')
    built=state['outputs']['skeleton_part']['measurements']['volume_mm3']
    assert abs(built-clean['outputs']['skeleton_part']['measurements']['volume_mm3'])<1e-6
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['skeleton_part']['file']))
    part=doc.Part
    volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
    assert abs(volume-built)<1e-6
    for role,name in [('rim','B40_Sweep'),('rim','B60_StageMirror'),('spoke','B60_Connection_4'),('spoke','B60_Connection_5'),('spoke','B60_StageMirror')]:
        assert part.FindObjectByName('Stage_'+role).Shapes.Item(name).Name==name
    selection=doc.Selection;selection.Clear()
    for i in range(1,part.HybridBodies.Count+1):selection.Add(part.HybridBodies.Item(i))
    for role in ['baffle','rim','spoke']:
        sketches=part.FindObjectByName('Stage_'+role).Sketches
        for i in range(1,sketches.Count+1):selection.Add(sketches.Item(i))
    if selection.Count:selection.VisProperties.SetShow(1)
    selection.Clear();selection.Add(part.MainBody);selection.VisProperties.SetShow(0);selection.Clear()
    app.Visible=True;doc.Activate()
    viewer=app.ActiveWindow.ActiveViewer
    viewpoint=viewer.Viewpoint3D
    viewpoint.PutSightDirection((0.0,0.0,-1.0));viewpoint.PutUpDirection((0.0,1.0,0.0))
    viewer.Viewpoint3D=viewpoint;viewer.Reframe();viewer.Update()
    doc.SaveAs(str(output/'VisibleSkeletonFixture.CATPart'))
    report={'fixture_only':True,'passed':True,'reopened_volume_mm3':volume,'recovery':state['recovery'],
            'unaffected_assets_unchanged':True,'clean_build_matches':True,'ds_status':'not_evaluated',
            'file':str(output/'VisibleSkeletonFixture.CATPart'),'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
