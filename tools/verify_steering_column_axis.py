"""从圆柱侧面提取轴线并驱动B10/B20，拒绝错误或多义管柱范围。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle,column_axis,sections


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-column-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    baffle.create(doc,None,[10,0,20,1,0,0,0,1,0],40,12)
    source=output/'ColumnFixture.CATPart';doc.SaveAs(str(source));doc.Close()
    scope=[{'collection':'Bodies','name':'B20_Baffle'}]
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1].pop('check')
    definition['external_objects']={'column_part':{'path':str(source),'sha256':runtime.digest(source),'unit':'mm',
        'coordinate_system':'design_global','objects':{'column_scope':scope}}}
    basis=definition['steps'][0]
    basis['parameters'].pop('column_point');basis['parameters'].pop('column_direction')
    basis['inputs']={'column':'column_axis'}
    definition['steps'].insert(0,{'id':'column','operation':'column_axis','inputs':{'source':'column_part'},'output':'column_axis',
        'parameters':{'scope_binding':'column_scope','positive_direction':[0,0,1]}})
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    measured=runtime.read(folder/state['outputs']['column_axis']['file'])
    assert measured['direction']==[0,0,1] and measured['radius_mm']==12,measured
    assert abs(measured['point_mm'][0]-10)<1e-7 and abs(measured['point_mm'][1])<1e-7
    axis_record=dict(state['outputs']['column_axis'])
    state=runtime.resume(folder,state['revision'],{'thickness_mm':10})
    assert state['status']=='completed' and state['outputs']['column_axis']==axis_record
    reversed_axis=column_axis.extract(app,source,scope,[0,0,-1])
    assert reversed_axis['direction']==[0,0,-1]
    try:column_axis.extract(app,source,scope,[1,0,0])
    except ValueError as error:assert 'sense' in str(error)
    else:raise AssertionError('Ambiguous axis orientation accepted')
    doc=app.Documents.Add('Part')
    baffle.create(doc,[[0,0],[10,0],[10,10],[0,10]],[0,0,0,1,0,0,0,1,0],10)
    wrong=output/'NotCylinder.CATPart';doc.SaveAs(str(wrong));doc.Close()
    try:column_axis.extract(app,wrong,scope,[0,0,1])
    except ValueError as error:assert 'found 0' in str(error)
    else:raise AssertionError('Non-cylindrical scope accepted')
    doc=app.Documents.Open(str(source))
    sketch=sections.circle(doc,doc.Part.MainBody,'OtherCylinder',[40,0,20,1,0,0,0,1,0],3)
    doc.Part.ShapeFactory.AddNewPad(sketch,10);doc.Part.Update()
    multiple=output/'MultipleCylinders.CATPart';doc.SaveAs(str(multiple));doc.Close()
    try:column_axis.extract(app,multiple,scope,[0,0,1])
    except ValueError as error:assert 'found 2' in str(error),str(error)
    else:raise AssertionError('Ambiguous cylinders accepted')
    report={'fixture_only':True,'passed':True,'axis':measured,'axis_asset_retained':True,
            'invalid_scope_rejected':True,'multiple_cylinders_rejected':True,'ambiguous_direction_rejected':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
