"""局部坐标库件经显式定位后组合，检查失败改参并验证轴系依赖保留。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-placement-flow-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');assets={}
    for name,origin,outline,coordinate in [
        ('platform',[0,0,0],[[0,0],[10,0],[10,20],[0,20]],'part_local'),
        ('other',[90,200,300],[[0,0],[20,0],[20,10],[0,10]],'design_global')]:
        doc=app.Documents.Add('Part');baffle.create(doc,outline,origin+[1,0,0,0,1,0],30)
        source=output/(name+'.CATPart');doc.SaveAs(str(source));doc.Close()
        assets[name]={'path':str(source),'sha256':runtime.digest(source),'unit':'mm','coordinate_system':coordinate,
                      'objects':{'body':[{'collection':'Bodies','name':'B20_Baffle'}]}}
    definition={'parameters':{'target_x_mm':{'default':100,'min':95,'max':110}},'external_objects':assets,'max_attempts':3,'fixture_only':True,
        'steps':[{'id':'place','operation':'place','inputs':{'source':'platform'},'output':'placed',
                  'parameters':{'source_frame':{'origin_mm':[0,0,0],'x':[1,0,0],'y':[0,1,0],'z':[0,0,1]},
                                'target_frame':{'origin_mm':[{'parameter':'target_x_mm'},200,300],'x':[0,1,0],'y':[-1,0,0],'z':[0,0,1]}}},
                 {'id':'union','operation':'combine','inputs':{'placed':'placed','other':'other'},'output':'combined','parameters':{},
                  'check':{'measurement':'volume_mm3','maximum':8000,'source':'fixture only, not DS'}}]}
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['combined']['measurements']['volume_mm3'];assert abs(initial-9000)<1e-5
    inputs={name:state['outputs'][name].copy() for name in assets}
    state=runtime.resume(folder,state['revision'],{'target_x_mm':105})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['place','union']
    assert all(state['outputs'][name]==record for name,record in inputs.items())
    updated=state['outputs']['combined']['measurements']['volume_mm3'];assert abs(updated-7500)<1e-5
    _,clean=runtime.start(definition,{'target_x_mm':105},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['combined']['measurements']['volume_mm3']-updated)<1e-6
    doc=app.Documents.Open(str(folder/state['outputs']['combined']['file']))
    try:
        part=doc.Part
        axis=part.AxisSystems.Item('Stage_placed_B00_Placement_2_TargetAxis')
        axis.PutOrigin((110.,200.,300.));part.Update()
        edited=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
        assert abs(edited-6000)<1e-5
        assert part.FindObjectByName('Stage_placed').Shapes.Item('B00_Placement_2').Name=='B00_Placement_2'
        doc.SaveAs(str(output/'EditablePlacedCombination.CATPart'))
    finally:doc.Close()
    assert all(runtime.digest(Path(spec['path']))==spec['sha256'] for spec in assets.values())
    report={'fixture_only':True,'passed':True,'initial_volume_mm3':initial,'updated_volume_mm3':updated,
            'edited_combination_volume_mm3':edited,'source_unchanged':True,'clean_build_matches':True,
            'recovery':state['recovery'],'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
