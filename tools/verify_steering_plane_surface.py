"""读取倾斜且有边界的底罩平面，验证投影及越界拒绝。"""
import copy,json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle,plane_surface


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-plane-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    q=math.sqrt(.5)
    baffle.create(doc,[[-20,-20],[20,-20],[20,20],[-20,20]],[0,0,10,1,0,0,0,q,-q],8.4)
    part=doc.Part;support=part.HybridBodies.Add();support.Name='CAS'
    fill=part.HybridShapeFactory.AddNewFill()
    fill.AddBound(part.CreateReferenceFromObject(part.MainBody.Sketches.Item('B20_Outline')))
    fill.Name='BottomFace';support.AppendHybridShape(fill)
    symmetry=part.HybridShapeFactory.AddNewPlaneEquation(0.0,1.0,0.0,0.0)
    symmetry.Name='Symmetry';support.AppendHybridShape(symmetry);part.Update()
    source=output/'PlanarInput.CATPart';doc.SaveAs(str(source));doc.Close()
    def object_path(name):return [{'collection':'HybridBodies','name':'CAS'},{'collection':'HybridShapes','name':name}]
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1].pop('check')
    definition['external_objects']={'cas':{'path':str(source),'sha256':runtime.digest(source),'unit':'mm',
        'coordinate_system':'design_global','objects':{'bottom':object_path('BottomFace'),'symmetry':object_path('Symmetry')}}}
    basis=definition['steps'][0]
    for role in ['bottom','symmetry']:
        basis['parameters'].pop(role+'_point');basis['parameters'].pop(role+'_normal')
        basis['inputs'][role]=role+'_plane'
    definition['steps'][:0]=[{'id':role,'operation':'plane_surface','inputs':{'source':'cas'},'output':role+'_plane',
        'parameters':{'surface_binding':role,'positive_normal':normal}} for role,normal in [('bottom',[0,0,1]),('symmetry',[0,1,0])]]
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    result=runtime.read(folder/state['outputs']['basis']['file'])
    assert all(abs(a-b)<1e-7 for a,b in zip(result['origin_mm'],[0,0,10])),result
    assert result['bottom_projection_distance_mm']<1e-7
    bad=copy.deepcopy(definition)
    datum_step=next(s for s in bad['steps'] if s['id']=='datum')
    datum_step['parameters']['outer_3'][0]=50;datum_step['parameters']['outer_9'][0]=50
    bad_folder,bad_state=runtime.start(bad,{},output)
    assert bad_state['status']=='execution_error' and 'outside' in bad_state['error'],bad_state.get('error')
    assert 'baffle' not in bad_state['completed']
    assert runtime.digest(source)==definition['external_objects']['cas']['sha256']
    doc=app.Documents.Add('Part');baffle.create(doc,None,[0,0,0,1,0,0,0,1,0],20,10)
    selection=doc.Selection;selection.Clear();selection.Add(doc.Part.MainBody);selection.Search('Topology.CGMFace,sel')
    spa=doc.GetWorkbench('SPAWorkbench')
    curved_ref=next(selection.Item2(i).Reference for i in range(1,selection.Count2+1)
                    if spa.GetMeasurable(selection.Item2(i).Reference).GeometryName==4)
    extracted=doc.Part.HybridShapeFactory.AddNewExtract(curved_ref)
    selection.Clear();support=doc.Part.HybridBodies.Add();support.Name='CAS'
    extracted.Name='Curved';support.AppendHybridShape(extracted);doc.Part.Update()
    curved_file=output/'CurvedInput.CATPart';doc.SaveAs(str(curved_file));doc.Close()
    try:plane_surface.extract(app,curved_file,object_path('Curved'),[0,0,1])
    except ValueError as error:assert 'planar' in str(error)
    else:raise AssertionError('Curved surface was silently treated as a plane')
    report={'fixture_only':True,'passed':True,'basis':result,'out_of_bounds_rejected':True,
            'curved_surface_rejected':True,'input_unchanged':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
