"""真实几何间隙失败→改参恢复，并保存最近点与输入身份。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle,clearance


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-clearance-%Y%m%d-%H%M%S-%f')
    output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Add('Part')
    obstacle=output/'Obstacle.CATPart'
    baffle.create(doc,[[-5,-5],[5,-5],[5,5],[-5,5]],[0,0,15,1,0,0,0,1,0],10)
    doc.SaveAs(str(obstacle));doc.Close()
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1].pop('check')
    definition['external_objects']={'obstacle':{'path':str(obstacle),'sha256':runtime.digest(obstacle),
        'unit':'mm','coordinate_system':'design_global','objects':{'body':[{'collection':'Bodies','name':'B20_Baffle'}]}}}
    definition['steps'].append({'id':'clearance','operation':'clearance','inputs':{'first':'baffle_part','second':'obstacle'},
        'output':'clearance_report','parameters':{},'check':{'measurement':'minimum_distance_mm','minimum':5,
        'source':'fixture clearance threshold 5mm; not a business DS rule'}})
    folder,state=runtime.start(definition,{'thickness_mm':12},output)
    assert state['status']=='check_failed',state.get('error')
    before=state['outputs']['clearance_report']['measurements']
    assert abs(before['minimum_distance_mm']-3)<1e-7
    obstacle_record=dict(state['outputs']['obstacle'])
    state=runtime.resume(folder,state['revision'],{'thickness_mm':10})
    assert state['status']=='completed',state.get('error')
    after=state['outputs']['clearance_report']['measurements']
    assert abs(after['minimum_distance_mm']-5)<1e-7
    assert state['outputs']['obstacle']==obstacle_record
    assert state['recovery']['execute']==['baffle','clearance']
    clean_folder,clean=runtime.start(definition,{'thickness_mm':10},output)
    assert clean['status']=='completed',clean.get('error')
    assert clean['outputs']['clearance_report']['measurements']==after
    # 完全包含也必须为零，不能把两层边界之间的距离误报为安全间隙。
    doc=app.Documents.Add('Part');contained=output/'Contained.CATPart'
    baffle.create(doc,[[-2,-2],[2,-2],[2,2],[-2,2]],[0,0,2,1,0,0,0,1,0],2)
    doc.SaveAs(str(contained));doc.Close()
    inside=clearance.measure(app,folder/state['outputs']['baffle_part']['file'],contained)
    assert inside['minimum_distance_mm']==0
    doc=app.Documents.Add('Part');surface_file=output/'Surface.CATPart'
    support=doc.Part.HybridBodies.Add();support.Name='CAS'
    plane=doc.Part.HybridShapeFactory.AddNewPlaneEquation(0.0,0.0,1.0,15.0)
    plane.Name='CheckSurface';support.AppendHybridShape(plane);doc.Part.Update()
    doc.SaveAs(str(surface_file));doc.Close()
    surface_path=[{'collection':'HybridBodies','name':'CAS'},{'collection':'HybridShapes','name':'CheckSurface'}]
    definition['external_objects']['obstacle']={'path':str(surface_file),'sha256':runtime.digest(surface_file),
        'unit':'mm','coordinate_system':'design_global','objects':{'surface':surface_path}}
    definition['steps'][-1]['parameters']={'second_binding':'surface'}
    surface_folder,surface_state=runtime.start(definition,{'thickness_mm':10},output)
    assert surface_state['status']=='completed',surface_state.get('error')
    surface_distance=surface_state['outputs']['clearance_report']['measurements']['minimum_distance_mm']
    assert abs(surface_distance-5)<1e-7
    assert runtime.digest(obstacle)==obstacle_record['sha256']
    report={'fixture_only':True,'passed':True,'before':before,'after':after,'contained_distance_mm':0,
            'surface_distance_mm':surface_distance,'obstacle_unchanged':True,'clean_build_matches':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
