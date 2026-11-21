"""单参数平台对时：以真实间隙检查驱动0→90度恢复，保留原生定位。"""
import json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle


def main():
    import pythoncom,win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-clocking-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');assets={}
    for name,outline,thickness,coordinates in [
        ('platform',[[0,0],[10,0],[10,20],[0,20]],30,'part_local'),
        ('environment',[[30,0],[40,0],[40,10],[30,10]],10,'design_global')]:
        doc=app.Documents.Add('Part')
        try:
            baffle.create(doc,outline,[0,0,0,1,0,0,0,1,0],thickness)
            source=output/(name+'.CATPart');doc.SaveAs(str(source))
        finally:doc.Close()
        assets[name]={'path':str(source),'sha256':runtime.digest(source),'unit':'mm','coordinate_system':coordinates,
                      'objects':{'body':[{'collection':'Bodies','name':'B20_Baffle'}]}}
    frame={'origin_mm':[0,0,0],'x':[1,0,0],'y':[0,1,0],'z':[0,0,1]}
    definition={'fixture_only':True,'parameters':{'clocking_deg':{'default':0,'min':0,'max':90,'unit':'deg'}},
        'max_attempts':3,'external_objects':assets,'steps':[
            {'id':'place','operation':'place','inputs':{'source':'platform'},'output':'placed',
             'parameters':{'source_frame':frame,'target_frame':frame,'clocking_deg':{'parameter':'clocking_deg'}}},
            {'id':'clearance','operation':'clearance','inputs':{'first':'placed','second':'environment'},'output':'clearance_report',
             'parameters':{},'checks':[{'id':'fixture-gap','measurement':'minimum_distance_mm','minimum':25,
                  'unit':'mm','source':'mechanism fixture, not platform rule or DS','version':'1'}]}]}
    definition['steps'].append({'id':'union','operation':'combine','inputs':{'placed':'placed','environment':'environment'},
                                'output':'combined','parameters':{}})
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['clearance_report']['measurements']['minimum_distance_mm'];assert abs(initial-20)<1e-6
    retained={name:state['outputs'][name].copy() for name in assets}
    state=runtime.resume(folder,state['revision'],{'clocking_deg':90})
    assert state['status']=='completed',state.get('error')
    after=state['outputs']['clearance_report']['measurements']['minimum_distance_mm'];assert abs(after-30)<1e-6
    placed=state['outputs']['placed']['measurements']
    assert math.dist(placed['cog_mm'],[-10,5,15])<1e-6 and abs(placed['volume_mm3']-6000)<1e-6
    assert state['recovery']['execute']==['place','clearance','union']
    assert all(state['outputs'][name]==record and runtime.digest(folder/record['file'])==record['sha256'] for name,record in retained.items())
    _,clean=runtime.start(definition,{'clocking_deg':90},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['clearance_report']['measurements']['minimum_distance_mm']-after)<1e-6
    doc=app.Documents.Open(str(folder/state['outputs']['placed']['file']))
    try:
        axis=doc.Part.AxisSystems.Item(placed['target_axis_name']);axes={}
        for method,expected in [('GetXAxis',[0,1,0]),('GetYAxis',[-1,0,0]),('GetZAxis',[0,0,1])]:
            value=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
            axis._oleobj_.Invoke(axis._oleobj_.GetIDsOfNames(method),0,1,0,value)
            axes[method]=list(value.value);assert math.dist(value.value,expected)<1e-6
        assert doc.Part.MainBody.Shapes.Item(placed['feature_name']).Name==placed['feature_name']
        volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody)).Volume*1e9
        assert abs(volume-6000)<1e-6
        angle=doc.Part.Parameters.Item(placed['clocking_parameter']);angle.ValuateFromString('45deg');doc.Part.Update()
        measurable=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody))
        cog=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
        measurable._oleobj_.Invoke(measurable._oleobj_.GetIDsOfNames('GetCOG'),0,1,0,cog)
        expected=[-5/math.sqrt(2),15/math.sqrt(2),15]
        assert math.dist(cog.value,expected)<1e-6
        edited_cog=list(cog.value);edited_path=output/'EditedClocking.CATPart';doc.SaveAs(str(edited_path))
    finally:doc.Close()
    doc=app.Documents.Open(str(edited_path))
    try:
        measurable=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(doc.Part.MainBody))
        measurable._oleobj_.Invoke(measurable._oleobj_.GetIDsOfNames('GetCOG'),0,1,0,cog)
        assert math.dist(cog.value,expected)<1e-6
    finally:doc.Close()
    assert runtime.digest(folder/state['outputs']['placed']['file'])==state['outputs']['placed']['sha256']
    doc=app.Documents.Open(str(folder/state['outputs']['combined']['file']))
    try:
        parameters=doc.Part.Parameters;leaf='Stage_placed_'+placed['clocking_parameter'].rsplit('\\',1)[-1]
        candidates=[parameters.Item(i) for i in range(1,parameters.Count+1) if parameters.Item(i).Name.rsplit('\\',1)[-1]==leaf]
        assert len(candidates)==1,'Combined model must retain exactly one native clocking parameter'
        candidates[0].ValuateFromString('45deg');doc.Part.Update()
        body=doc.Part.FindObjectByName('Stage_placed')
        measurable=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(body))
        measurable._oleobj_.Invoke(measurable._oleobj_.GetIDsOfNames('GetCOG'),0,1,0,cog)
        combined_cog=list(cog.value);assert math.dist(combined_cog,expected)<1e-6
        doc.SaveAs(str(output/'EditableClockedCombination.CATPart'))
    finally:doc.Close()
    assert runtime.digest(folder/state['outputs']['combined']['file'])==state['outputs']['combined']['sha256']
    assert all(runtime.digest(spec['path'])==spec['sha256'] for spec in assets.values())
    report={'fixture_only':True,'passed':True,'initial_gap_mm':initial,'updated_gap_mm':after,'placed':placed,
            'reopened_axes':axes,'reopened_volume_mm3':volume,'native_45deg_cog_mm':edited_cog,'combined_native_45deg_cog_mm':combined_cog,'source_unchanged':True,'clean_build_matches':True,
            'recovery':state['recovery'],'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
