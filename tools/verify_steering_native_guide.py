"""验证外部原生引导线的法向截面、扫掠和参数恢复。"""
import copy,json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-native-guide-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    baffle.create(doc,None,[-100,0,0,1,0,0,0,1,0],10,5)
    part=doc.Part;factory=part.HybridShapeFactory;support=part.HybridBodies.Add();support.Name='CAS_Guides'
    points=[]
    for i,coords in enumerate([(10.,20.,30.),(40.,60.,30.),(22.,40.,34.)]):
        point=factory.AddNewPointCoord(*coords);point.Name='Point_'+str(i);support.AppendHybridShape(point);points.append(point)
    line=factory.AddNewLinePtPt(part.CreateReferenceFromObject(points[0]),part.CreateReferenceFromObject(points[1]))
    line.Name='Line';support.AppendHybridShape(line)
    spline=factory.AddNewSpline()
    for index in [0,2,1]:spline.AddPoint(part.CreateReferenceFromObject(points[index]))
    spline.Name='Spline';support.AppendHybridShape(spline);part.Update()
    source=output/'NativeGuides.CATPart';doc.SaveAs(str(source));doc.Close()
    objects={name:[{'collection':'HybridBodies','name':'CAS_Guides'},{'collection':'HybridShapes','name':name}] for name in ['Line','Spline']}
    definition={'parameters':{'radius_mm':{'default':2,'min':1,'max':3,'unit':'mm'}},'max_attempts':3,'fixture_only':True,
        'external_objects':{'cas':{'path':str(source),'sha256':runtime.digest(source),'unit':'mm','coordinate_system':'design_global','objects':objects}},
        'steps':[{'id':'rim','operation':'native_guide','inputs':{'source':'cas'},'output':'rim_part',
                  'parameters':{'guide_binding':'Line','section_radius_mm':{'parameter':'radius_mm'}},
                  'check':{'measurement':'volume_mm3','minimum':800,'source':'fixture only, not DS'}}]}
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['rim_part']['measurements'];source_record=state['outputs']['cas'].copy()
    assert abs(initial['volume_mm3']-math.pi*4*50)<1e-5
    state=runtime.resume(folder,state['revision'],{'radius_mm':2.5})
    assert state['status']=='completed',state.get('error')
    assert state['outputs']['cas']==source_record
    measured=state['outputs']['rim_part']['measurements']
    assert abs(measured['volume_mm3']-math.pi*6.25*50)<1e-5
    assert measured['section_frame'][:3]==[10,20,30]
    _,clean=runtime.start(definition,{'radius_mm':2.5},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['rim_part']['measurements']['volume_mm3']-measured['volume_mm3'])<1e-6
    curved=copy.deepcopy(definition);curved['steps'][0]['parameters']['guide_binding']='Spline';curved['steps'][0].pop('check')
    curved_folder,curved_state=runtime.start(curved,{},output)
    assert curved_state['status']=='completed',curved_state.get('error')
    assert runtime.digest(source)==definition['external_objects']['cas']['sha256']
    doc=app.Documents.Open(str(folder/state['outputs']['rim_part']['file']))
    assert doc.Part.MainBody.Name=='B40_NativeRim'
    assert doc.Part.MainBody.Shapes.Item('B40_NativeSweep').Name=='B40_NativeSweep'
    volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
    assert abs(volume-measured['volume_mm3'])<1e-6
    doc.Close()
    report={'fixture_only':True,'passed':True,'initial':initial,'updated':measured,
            'spline':curved_state['outputs']['rim_part']['measurements'],'source_unchanged':True,
            'clean_build_matches':True,'reopened_volume_mm3':volume,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
