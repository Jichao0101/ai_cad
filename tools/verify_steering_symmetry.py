"""实机验证四个原生点到对称面、设计轴和辐板的依赖链。"""
import copy,json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,symmetry_points


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-symmetry-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Add('Part');part=doc.Part
    support=part.HybridBodies.Add();support.Name='CAS_Points'
    points={'left_a':[-20.,-100.,40.],'right_a':[-20.,100.,40.],
            'left_b':[20.,-90.,45.],'right_b':[20.,90.,45.], 'wrong_b':[21.,90.,45.]}
    for name,coordinates in points.items():
        point=part.HybridShapeFactory.AddNewPointCoord(*coordinates)
        point.Name=name;support.AppendHybridShape(point)
    part.Update();source=output/'FourPoints.CATPart';doc.SaveAs(str(source));doc.Close()
    objects={name:[{'collection':'HybridBodies','name':'CAS_Points'},{'collection':'HybridShapes','name':name}] for name in points}
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['external_objects']={'cas':{'path':str(source),'sha256':runtime.digest(source),'unit':'mm',
        'coordinate_system':'design_global','objects':objects}}
    basis=definition['steps'][0]
    basis['parameters'].pop('symmetry_point');basis['parameters'].pop('symmetry_normal')
    basis['inputs']['symmetry']='symmetry_plane'
    symmetry={'id':'symmetry','operation':'symmetry_points','inputs':{'source':'cas'},'output':'symmetry_plane',
              'parameters':{'point_pairs':[['left_a','right_a'],['left_b','right_b']],'positive_normal':[0,1,0]}}
    definition['steps'].insert(0,symmetry)
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    retained={name:state['outputs'][name].copy() for name in ['cas','symmetry_plane','basis']}
    state=runtime.resume(folder,state['revision'],{'thickness_mm':10})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['baffle']
    assert all(state['outputs'][name]==record for name,record in retained.items())
    plane=runtime.read(folder/state['outputs']['symmetry_plane']['file'])
    assert plane['normal']==[0,1,0]
    assert plane['maximum_pair_deviation_mm']<1e-9
    bad=copy.deepcopy(definition);bad['steps'][0]['parameters']['point_pairs'][1][1]='wrong_b'
    _,bad_state=runtime.start(bad,{},output)
    assert bad_state['status']=='execution_error' and 'common symmetry plane' in bad_state['error']
    assert not bad_state['completed']
    assert runtime.digest(source)==definition['external_objects']['cas']['sha256']
    doc=app.Documents.Open(str(folder/state['outputs']['baffle_part']['file']))
    assert doc.Part.AxisSystems.Item('B10_DesignAxis').Name=='B10_DesignAxis'
    value=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
    assert abs(value-24000)<1e-5
    app.Visible=True;doc.Activate();app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'passed':True,'plane':plane,'reopened_volume_mm3':value,
            'retained':list(retained),'recovery':state['recovery'],'bad_pair_rejected':True,
            'source_unchanged':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
