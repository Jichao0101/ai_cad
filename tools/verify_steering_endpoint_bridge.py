"""上游原生圆截面扫掠端部读回、绑定桥接及分支改参恢复。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-endpoint-bridge-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    try:
        part=doc.Part;support=part.HybridBodies.Add();support.Name='Guides';factory=part.HybridShapeFactory
        for name,limits in [('First',[0,20]),('Second',[40,60])]:
            points=[]
            for z in limits:
                point=factory.AddNewPointCoord(10.,20.,float(z));support.AppendHybridShape(point);points.append(point)
            line=factory.AddNewLinePtPt(*[part.CreateReferenceFromObject(p) for p in points])
            line.Name=name;support.AppendHybridShape(line)
        part.Update();source=output/'Guides.CATPart';doc.SaveAs(str(source))
    finally:doc.Close()
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['id']='native-endpoint-bridge-fixture';definition['steps']=definition['steps'][:1]
    definition['parameters']={'first_radius_mm':{'default':2,'min':1,'max':3,'unit':'mm'}}
    definition['external_objects']={'source':{'path':str(source),'sha256':runtime.digest(source),'unit':'mm',
        'coordinate_system':'design_global','objects':{name:[{'collection':'HybridBodies','name':'Guides'},
        {'collection':'HybridShapes','name':name}] for name in ['First','Second']}}}
    for role,binding,radius in [('first','First',{'parameter':'first_radius_mm'}),('second','Second',2)]:
        definition['steps'].append({'id':role,'operation':'native_guide','inputs':{'source':'source'},'output':role+'_part',
            'parameters':{'guide_binding':binding,'section_radius_mm':radius}})
    definition['steps'].append({'id':'bridge','operation':'rim_bridge',
        'inputs':{'basis':'basis','first':'first_part','second':'second_part'},'output':'bridge_part',
        'parameters':{'endpoints':{'first':'end','second':'start'}},
        'checks':[{'id':'fixture-volume','measurement':'volume_mm3','minimum':300,'maximum':350,
            'unit':'mm3','source':'mechanism fixture, not DS','version':'1'}]})
    definition['steps'].extend([
        {'id':'union','operation':'combine','inputs':{'first':'first_part','bridge':'bridge_part','second':'second_part','basis':'basis'},
         'output':'joined_part','parameters':{}},
        {'id':'domains','operation':'solid_domains','inputs':{'source':'joined_part'},'output':'step_evidence','parameters':{},
         'checks':[{'id':'one-exported-solid','measurement':'step_solid_count','minimum':1,'maximum':1,
                    'unit':'count','source':'mechanism fixture, STEP topology only, not DS','version':'1'}]}])
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    before=state['outputs']['bridge_part']['measurements']['volume_mm3']
    ends={role:state['outputs'][role+'_part']['measurements']['end_sections'] for role in ['first','second']}
    assert ends['first']['sections']['end']['center_mm']==[10,20,20]
    assert ends['second']['sections']['start']['center_mm']==[10,20,40]
    retained={name:state['outputs'][name].copy() for name in ['source','basis','second_part']}
    state=runtime.resume(folder,state['revision'],{'first_radius_mm':2.5})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['first','bridge','union','domains']
    assert all(state['outputs'][name]==record and runtime.digest(folder/record['file'])==record['sha256'] for name,record in retained.items())
    after=state['outputs']['bridge_part']['measurements']['volume_mm3']
    _,clean=runtime.start(definition,{'first_radius_mm':2.5},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['bridge_part']['measurements']['volume_mm3']-after)<1e-6
    assert state['outputs']['step_evidence']['measurements']['step_solid_count']==1
    assert clean['outputs']['step_evidence']['measurements']==state['outputs']['step_evidence']['measurements']
    doc=app.Documents.Open(str(folder/state['outputs']['bridge_part']['file']))
    try:
        assert doc.Part.MainBody.Shapes.Item('B45_Bridge').Name=='B45_Bridge'
        volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
        assert abs(volume-after)<1e-6
    finally:doc.Close()
    assert runtime.digest(source)==definition['external_objects']['source']['sha256']
    report={'fixture_only':True,'passed':True,'ds_status':'not_evaluated','initial_volume_mm3':before,
        'updated_volume_mm3':after,'reopened_volume_mm3':volume,'end_sections':ends,'recovery':state['recovery'],
        'joined_topology':state['outputs']['step_evidence']['measurements'],
        'clean_build_matches':True,'retained_assets_unchanged':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
