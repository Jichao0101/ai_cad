"""实机验证比例总以原曲线为基准，并由改参恢复重建裁剪及扫掠。"""
import copy,json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-guide-trim-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    part=doc.Part;factory=part.HybridShapeFactory;body=part.HybridBodies.Add();body.Name='Guides'
    pts=[]
    for coords in [(10.,20.,30.),(40.,60.,30.),(22.,40.,34.)]:
        point=factory.AddNewPointCoord(*coords);body.AppendHybridShape(point);pts.append(point)
    line=factory.AddNewLinePtPt(part.CreateReferenceFromObject(pts[0]),part.CreateReferenceFromObject(pts[1]))
    line.Name='Line';body.AppendHybridShape(line)
    spline=factory.AddNewSpline()
    for i in [0,2,1]:spline.AddPoint(part.CreateReferenceFromObject(pts[i]))
    spline.Name='Spline';body.AppendHybridShape(spline);part.Update()
    source=output/'Guides.CATPart';doc.SaveAs(str(source));doc.Close()
    objects={name:[{'collection':'HybridBodies','name':'Guides'},{'collection':'HybridShapes','name':name}] for name in ['Line','Spline']}
    definition={'parameters':{'end_fraction':{'default':.6,'min':.4,'max':1}},'max_attempts':3,'fixture_only':True,
        'external_objects':{'cas':{'path':str(source),'sha256':runtime.digest(source),'unit':'mm','coordinate_system':'design_global','objects':objects}},
        'steps':[{'id':'rim','operation':'native_guide','inputs':{'source':'cas'},'output':'rim_part',
                  'parameters':{'guide_binding':'Line','section_radius_mm':2,'start_fraction':.2,'end_fraction':{'parameter':'end_fraction'}},
                  'check':{'measurement':'guide_length_mm','minimum':25,'source':'fixture only, not DS'}}]}
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['rim_part']['measurements']
    assert abs(initial['guide_length_mm']-20)<1e-6
    retained=state['outputs']['cas'].copy()
    state=runtime.resume(folder,state['revision'],{'end_fraction':.8})
    assert state['status']=='completed',state.get('error')
    result=state['outputs']['rim_part']['measurements']
    assert abs(result['guide_length_mm']-30)<1e-6
    assert math.dist(result['section_frame'][:3],[16,28,30])<1e-6
    assert abs(result['volume_mm3']-math.pi*4*30)<1e-5
    assert state['outputs']['cas']==retained
    _,clean=runtime.start(definition,{'end_fraction':.8},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['rim_part']['measurements']['volume_mm3']-result['volume_mm3'])<1e-6
    curved=copy.deepcopy(definition);curved['steps'][0]['parameters']['guide_binding']='Spline';curved['steps'][0].pop('check')
    curved_folder,curved_state=runtime.start(curved,{'end_fraction':.8},output)
    assert curved_state['status']=='completed',curved_state.get('error')
    curved_result=curved_state['outputs']['rim_part']['measurements']
    assert abs(curved_result['guide_length_mm']-.6*curved_result['source_guide_length_mm'])<1e-4
    doc=app.Documents.Open(str(folder/state['outputs']['rim_part']['file']))
    part=doc.Part
    assert part.FindObjectByName('B40_TrimAfterStart').Name=='B40_TrimAfterStart'
    assert part.FindObjectByName('B40_TrimAfterEnd').Name=='B40_TrimAfterEnd'
    reopened=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
    assert abs(reopened-result['volume_mm3'])<1e-6
    doc.Close()
    assert runtime.digest(source)==definition['external_objects']['cas']['sha256']
    report={'fixture_only':True,'passed':True,'initial':initial,'updated':result,'spline':curved_result,
            'reopened_volume_mm3':reopened,'clean_build_matches':True,'source_unchanged':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
