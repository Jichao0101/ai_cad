"""验证原生曲线上的矩形截面方向、派生半厚及失败后恢复。"""
import copy,json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import pythoncom,win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-rectangle-guide-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    part=doc.Part;factory=part.HybridShapeFactory;support=part.HybridBodies.Add();support.Name='Guides'
    points=[]
    for coordinates in [(10.,20.,30.),(40.,60.,30.),(22.,40.,34.)]:
        point=factory.AddNewPointCoord(*coordinates);support.AppendHybridShape(point);points.append(point)
    line=factory.AddNewLinePtPt(part.CreateReferenceFromObject(points[0]),part.CreateReferenceFromObject(points[1]))
    line.Name='Line';support.AppendHybridShape(line)
    spline=factory.AddNewSpline()
    for i in [0,2,1]:spline.AddPoint(part.CreateReferenceFromObject(points[i]))
    spline.Name='Spline';support.AppendHybridShape(spline);part.Update()
    source=output/'Guides.CATPart';doc.SaveAs(str(source));doc.Close()
    objects={name:[{'collection':'HybridBodies','name':'Guides'},{'collection':'HybridShapes','name':name}] for name in ['Line','Spline']}
    definition={'parameters':{'thickness_mm':{'default':8.4,'min':8,'max':12}},'max_attempts':3,'fixture_only':True,
        'external_objects':{'cas':{'path':str(source),'sha256':runtime.digest(source),'unit':'mm','coordinate_system':'design_global','objects':objects}},
        'steps':[{'id':'rim','operation':'native_guide','inputs':{'source':'cas'},'output':'rim_part',
                  'parameters':{'guide_binding':'Line','rectangle':{'width_mm':12,'thickness_mm':{'parameter':'thickness_mm'},'thickness_direction':[0,0,1]}},
                  'check':{'measurement':'volume_mm3','minimum':5500,'source':'fixture only, not DS'}}]}
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['rim_part']['measurements'];retained=state['outputs']['cas'].copy()
    assert abs(initial['volume_mm3']-5040)<1e-5
    assert initial['half_thickness_mm']==4.2
    state=runtime.resume(folder,state['revision'],{'thickness_mm':10})
    assert state['status']=='completed',state.get('error')
    result=state['outputs']['rim_part']['measurements']
    assert abs(result['volume_mm3']-6000)<1e-5 and result['half_thickness_mm']==5
    assert result['section_frame'][6:]==[0,0,1]
    assert state['outputs']['cas']==retained
    _,clean=runtime.start(definition,{'thickness_mm':10},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['rim_part']['measurements']['volume_mm3']-result['volume_mm3'])<1e-6
    doc=app.Documents.Open(str(folder/state['outputs']['rim_part']['file']))
    part=doc.Part;spa=doc.GetWorkbench('SPAWorkbench');z=[]
    for i in range(4):
        point=part.FindObjectByName('B30_Section_Corner_'+str(i))
        measured=spa.GetMeasurable(part.CreateReferenceFromObject(point))
        values=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPoint'),0,1,0,values)
        z.append(values.value[2])
    assert min(z)==25 and max(z)==35
    reopened=spa.GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
    assert abs(reopened-6000)<1e-5
    doc.Close()
    bad=copy.deepcopy(definition);bad['steps'][0]['parameters']['rectangle']['thickness_direction']=[.6,.8,0]
    _,bad_state=runtime.start(bad,{},output)
    assert bad_state['status']=='execution_error' and 'parallel' in bad_state['error']
    curved=copy.deepcopy(definition);curved['steps'][0]['parameters']['guide_binding']='Spline';curved['steps'][0].pop('check')
    _,curved_state=runtime.start(curved,{},output)
    assert curved_state['status']=='completed',curved_state.get('error')
    assert runtime.digest(source)==definition['external_objects']['cas']['sha256']
    report={'fixture_only':True,'passed':True,'initial':initial,'updated':result,'corner_z_mm':z,
            'spline':curved_state['outputs']['rim_part']['measurements'],'parallel_direction_rejected':True,
            'reopened_volume_mm3':reopened,'source_unchanged':True,'clean_build_matches':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
