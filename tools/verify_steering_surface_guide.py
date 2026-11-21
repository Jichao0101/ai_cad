"""曲面求交→引导线扫掠→间隙检查的单参局部恢复；输入为合成曲面。"""
import copy,json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle,sections


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-surface-guide-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    try:
        part=doc.Part;factory=part.HybridShapeFactory;support=part.HybridBodies.Add();support.Name='CAS'
        spline=factory.AddNewSpline()
        for coordinates in [(0.,0.,0.),(25.,10.,0.),(50.,0.,0.)]:
            point=factory.AddNewPointCoord(*coordinates);support.AppendHybridShape(point)
            spline.AddPoint(part.CreateReferenceFromObject(point))
        spline.Name='OuterCurve';support.AppendHybridShape(spline);part.Update()
        surface=factory.AddNewExtrude(part.CreateReferenceFromObject(spline),10.,10.,factory.AddNewDirectionByCoord(0.,0.,1.))
        surface.Name='OuterSurface';support.AppendHybridShape(surface);part.Update()
        circle=sections.circle(doc,part.MainBody,'ClosedProfile',[0,0,0,1,0,0,0,1,0],15)
        closed=factory.AddNewExtrude(part.CreateReferenceFromObject(circle),10.,10.,factory.AddNewDirectionByCoord(0.,0.,1.))
        closed.Name='ClosedSurface';support.AppendHybridShape(closed);part.Update()
        cas=output/'CAS_Surface.CATPart';doc.SaveAs(str(cas))
    finally:doc.Close()
    doc=app.Documents.Add('Part')
    try:
        baffle.create(doc,[[-10,-10],[60,-10],[60,30],[-10,30]],[0,0,-6,1,0,0,0,1,0],2)
        environment=output/'Environment.CATPart';doc.SaveAs(str(environment))
    finally:doc.Close()
    surface_path=[{'collection':'HybridBodies','name':'CAS'},{'collection':'HybridShapes','name':'OuterSurface'}]
    guide_path=[{'collection':'HybridBodies','name':'B40_SurfaceGuide'},{'collection':'HybridShapes','name':'GuideIntersection'}]
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json');definition['steps']=definition['steps'][:1]
    definition['parameters']={'plane_offset_mm':{'default':0,'min':0,'max':20,'unit':'mm'}}
    definition['external_objects']={name:{'path':str(path),'sha256':runtime.digest(path),'unit':'mm',
        'coordinate_system':'design_global','objects':bindings} for name,path,bindings in [
            ('cas',cas,{'surface':surface_path,'closed_surface':[{'collection':'HybridBodies','name':'CAS'},{'collection':'HybridShapes','name':'ClosedSurface'}]}),('environment',environment,{'body':[{'collection':'Bodies','name':'B20_Baffle'}]})]}
    definition['steps'].extend([
        {'id':'section','operation':'surface_guide','inputs':{'source':'cas','basis':'basis'},'output':'section_part',
         'parameters':{'surface_binding':'surface','plane_offset_mm':{'parameter':'plane_offset_mm'},'start_hint_mm':[0,0,0]}},
        {'id':'rim','operation':'native_guide','inputs':{'source':'section_part'},'output':'rim_part',
         'parameters':{'guide_path':guide_path,'section_radius_mm':1,'start_fraction':.2,'end_fraction':.8}},
        {'id':'clearance','operation':'clearance','inputs':{'first':'rim_part','second':'environment'},'output':'gap_report','parameters':{},
         'checks':[{'id':'fixture-gap','measurement':'minimum_distance_mm','minimum':5,'unit':'mm',
                    'source':'mechanism fixture, not CAS design rule or DS','version':'1'}]}])
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    before=state['outputs']['gap_report']['measurements']['minimum_distance_mm'];assert abs(before-3)<1e-4
    retained={name:state['outputs'][name].copy() for name in ['cas','environment','basis']}
    state=runtime.resume(folder,state['revision'],{'plane_offset_mm':5})
    assert state['status']=='completed',state.get('error')
    after=state['outputs']['gap_report']['measurements']['minimum_distance_mm'];assert abs(after-8)<1e-4
    assert state['recovery']['execute']==['section','rim','clearance']
    assert all(state['outputs'][name]==record and runtime.digest(folder/record['file'])==record['sha256'] for name,record in retained.items())
    section=state['outputs']['section_part']['measurements']
    assert section['guide_path']==guide_path and all(abs(p[2]-5)<1e-6 for p in section['guide_points_mm'])
    assert section['direction_from_hint'] and section['guide_reversed']
    assert abs(section['guide_points_mm'][0][0])<1e-6 and abs(section['guide_points_mm'][2][0]-50)<1e-6
    ends=state['outputs']['rim_part']['measurements']['end_sections']['sections']
    assert 0<ends['start']['center_mm'][0]<ends['end']['center_mm'][0]<50
    _,clean=runtime.start(definition,{'plane_offset_mm':5},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['gap_report']['measurements']['minimum_distance_mm']-after)<1e-6
    doc=app.Documents.Open(str(folder/state['outputs']['rim_part']['file']))
    try:
        assert doc.Part.HybridBodies.Item('B40_SurfaceGuide').HybridShapes.Item('GuideIntersection').Name=='GuideIntersection'
        assert doc.Part.MainBody.Shapes.Item('B40_NativeSweep').Name=='B40_NativeSweep'
        volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
        assert abs(volume-state['outputs']['rim_part']['measurements']['volume_mm3'])<1e-6
    finally:doc.Close()
    _,bad=runtime.start(definition,{'plane_offset_mm':20},output)
    assert bad['status']=='execution_error' and bad['failed_step']=='section'
    assert 'rim_part' not in bad['outputs']
    closed_definition=copy.deepcopy(definition);closed_definition['steps'][1]['parameters']['surface_binding']='closed_surface'
    _,closed_state=runtime.start(closed_definition,{},output)
    assert closed_state['status']=='execution_error' and 'Closed intersection' in closed_state['error']
    assert 'rim_part' not in closed_state['outputs']
    ambiguous=copy.deepcopy(definition);ambiguous['steps'][1]['parameters']['start_hint_mm']=[25,0,0]
    _,ambiguous_state=runtime.start(ambiguous,{},output)
    assert ambiguous_state['status']=='execution_error' and 'equidistant' in ambiguous_state['error']
    assert 'rim_part' not in ambiguous_state['outputs']
    assert all(runtime.digest(spec['path'])==spec['sha256'] for spec in definition['external_objects'].values())
    report={'fixture_only':True,'passed':True,'initial_gap_mm':before,'updated_gap_mm':after,
        'section':section,'trimmed_end_sections':ends,'ambiguous_direction_rejected':True,'reopened_volume_mm3':volume,'clean_build_matches':True,'source_unchanged':True,
        'nonintersecting_plane_rejected':True,'closed_intersection_rejected':True,'recovery':state['recovery'],'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
