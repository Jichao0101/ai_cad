"""底罩求交圆→径向内缩→原生辐板，含半圆与过量内缩拒绝。"""
import json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,circular_profile,cad_frame


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-circular-profile-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');sources=[]
    for closed in [True,False]:
        doc=app.Documents.Add('Part');part=doc.Part
        sketch=part.MainBody.Sketches.Add(part.CreateReferenceFromObject(part.OriginElements.PlaneXY))
        cad_frame.set_verified(sketch,[10,0,0,1,0,0,0,1,0])
        factory=sketch.OpenEdition()
        if closed:factory.CreateClosedCircle(0,0,40)
        else:
            arc=factory.CreateCircle(0,0,40,0,math.pi)
            arc.StartPoint=factory.CreatePoint(40,0);arc.EndPoint=factory.CreatePoint(-40,0)
        sketch.CloseEdition();part.Update()
        support=part.HybridBodies.Add();support.Name='CAS'
        surface=part.HybridShapeFactory.AddNewExtrude(part.CreateReferenceFromObject(sketch),30,30,part.HybridShapeFactory.AddNewDirectionByCoord(0,0,1))
        surface.Name='Bottom';support.AppendHybridShape(surface);part.Update()
        path=output/('Closed.CATPart' if closed else 'Open.CATPart');doc.SaveAs(str(path));doc.Close();sources.append(path)
    binding=[{'collection':'HybridBodies','name':'CAS'},{'collection':'HybridShapes','name':'Bottom'}]
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['external_objects']={'cas':{'path':str(sources[0]),'sha256':runtime.digest(sources[0]),'unit':'mm',
        'coordinate_system':'design_global','objects':{'bottom':binding}}}
    definition['parameters']['inset_mm']={'default':3,'min':0,'max':10,'unit':'mm'}
    plate=definition['steps'][1];plate.pop('check');plate['parameters'].pop('outline');plate['inputs']['profile']='circle_profile'
    definition['steps'].insert(1,{'id':'profile','operation':'circular_profile','inputs':{'source':'cas','basis':'basis'},
        'output':'circle_profile','parameters':{'surface_binding':'bottom','radial_inset_mm':{'parameter':'inset_mm'},'plane_offset_mm':2}})
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    before=state['outputs']['baffle_part']['measurements']
    assert before['radius_mm']==37 and abs(before['volume_mm3']-math.pi*37**2*8.4)<1e-5
    basis_record=dict(state['outputs']['basis']);source_record=dict(state['outputs']['cas'])
    state=runtime.resume(folder,state['revision'],{'inset_mm':5})
    assert state['status']=='completed',state.get('error')
    after=state['outputs']['baffle_part']['measurements']
    assert after['radius_mm']==35 and abs(after['volume_mm3']-math.pi*35**2*8.4)<1e-5
    assert state['outputs']['basis']==basis_record and state['outputs']['cas']==source_record
    assert state['recovery']['execute']==['profile','baffle']
    basis=runtime.read(folder/basis_record['file'])
    for source,inset,expected in [(sources[1],3,'complete circular'),(sources[0],40,'entire circular')]:
        try:circular_profile.extract(app,source,binding,basis,inset)
        except ValueError as error:assert expected in str(error),str(error)
        else:raise AssertionError('Invalid profile accepted')
    doc=app.Documents.Open(str(folder/state['outputs']['baffle_part']['file']))
    frame=cad_frame.read(doc.Part.MainBody.Sketches.Item('B20_Outline'))
    assert all(abs(a-b)<1e-7 for a,b in zip(frame[:3],[10,0,2])),frame
    app.Visible=True;doc.Activate();app.ActiveWindow.ActiveViewer.Reframe()
    assert runtime.digest(sources[0])==source_record['sha256']
    report={'fixture_only':True,'passed':True,'before':before,'after':after,'saved_frame':frame,
            'open_profile_rejected':True,'excessive_inset_rejected':True,'source_and_basis_retained':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
