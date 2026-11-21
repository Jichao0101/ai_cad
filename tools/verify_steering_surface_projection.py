"""曲面原点投影：半圆柱唯一解、整圆柱多解、区间内无解。"""
import json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,cad_frame,surface_projection


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-projection-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application')
    sources=[]
    for closed in [False,True]:
        doc=app.Documents.Add('Part');part=doc.Part
        sketch=part.MainBody.Sketches.Add(part.CreateReferenceFromObject(part.OriginElements.PlaneYZ))
        cad_frame.set_verified(sketch,[0,0,0,0,1,0,0,0,1])
        factory=sketch.OpenEdition()
        if closed:factory.CreateClosedCircle(0,0,20)
        else:
            arc=factory.CreateCircle(0,0,20,0,math.pi)
            arc.StartPoint=factory.CreatePoint(20,0);arc.EndPoint=factory.CreatePoint(-20,0)
        sketch.CloseEdition();part.Update()
        support=part.HybridBodies.Add();support.Name='CAS'
        surface=part.HybridShapeFactory.AddNewExtrude(part.CreateReferenceFromObject(sketch),20,20,part.HybridShapeFactory.AddNewDirectionByCoord(1,0,0))
        surface.Name='Bottom';support.AppendHybridShape(surface);part.Update()
        path=output/('FullCylinder.CATPart' if closed else 'HalfCylinder.CATPart')
        doc.SaveAs(str(path));doc.Close();sources.append(path)
    binding=[{'collection':'HybridBodies','name':'CAS'},{'collection':'HybridShapes','name':'Bottom'}]
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1].pop('check')
    definition['external_objects']={'cas':{'path':str(sources[0]),'sha256':runtime.digest(sources[0]),'unit':'mm',
        'coordinate_system':'design_global','objects':{'bottom':binding}}}
    basis=definition['steps'][0];basis['inputs']={'bottom_surface':'cas'}
    basis['parameters'].pop('bottom_point');basis['parameters'].pop('bottom_normal')
    basis['parameters'].update(bottom_surface_binding='bottom',projection_extent_mm=100)
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    result=runtime.read(folder/state['outputs']['basis']['file'])
    assert all(abs(a-b)<1e-7 for a,b in zip(result['origin_mm'],[0,0,20])),result
    try:surface_projection.project(app,sources[1],binding,[0,0,40],[0,0,1],100)
    except ValueError as error:assert 'found 2' in str(error),str(error)
    else:raise AssertionError('Multiple intersections accepted')
    try:surface_projection.project(app,sources[0],binding,[0,0,40],[0,0,1],1)
    except ValueError as error:assert 'found 0' in str(error) or 'intersection failed' in str(error),str(error)
    else:raise AssertionError('Empty projection interval accepted')
    assert runtime.digest(sources[0])==definition['external_objects']['cas']['sha256']
    report={'fixture_only':True,'passed':True,'basis':result,'multiple_intersections_rejected':True,
            'no_intersection_rejected':True,'source_unchanged':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
