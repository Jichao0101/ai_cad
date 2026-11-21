"""验证组合骨架的非零基准移交、真实Publication及分支改参恢复。"""
import json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import pythoncom,win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-skeleton-publications-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_skeleton_flow.json')
    basis=definition['steps'][0]['parameters']
    basis.update(column_point=[10,20,0],symmetry_point=[0,20,0],outer_3=[10,120,40],
                 outer_9=[10,-80,40],bottom_point=[0,0,30])
    definition['steps'][-1]['inputs']['basis']='basis'
    definition['steps'].append({'id':'publications','operation':'publish_references','inputs':{'source':'skeleton_part'},
        'output':'published_skeleton','parameters':{'prepare_display':True,'publications':{
            'SkeletonSolid':[{'collection':'Bodies','name':'B90_Skeleton'}],
            'DesignAxis':[{'collection':'AxisSystems','name':'B10_DesignAxis'}]}}})
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    retained={name:state['outputs'][name].copy() for name in ['basis','baffle_part','spoke_part']}
    state=runtime.resume(folder,state['revision'],{'section_radius_mm':5.5})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['rim','rim_mirror','union','publications']
    assert all(state['outputs'][name]==record for name,record in retained.items())
    _,clean=runtime.start(definition,{'section_radius_mm':5.5},output)
    assert clean['status']=='completed',clean.get('error')
    expected=state['outputs']['skeleton_part']['measurements']['volume_mm3']
    assert abs(expected-clean['outputs']['skeleton_part']['measurements']['volume_mm3'])<1e-6
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['published_skeleton']['file']))
    try:
        pubs=doc.Product.Publications
        volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(pubs.Item('SkeletonSolid').Valuation).Volume*1e9
        assert abs(volume-expected)<1e-6
        selection=doc.Selection;selection.Clear();selection.Add(pubs.Item('DesignAxis').Valuation)
        axis=selection.Item2(1).Value;selection.Clear()
        for collection in [doc.Part.AxisSystems,doc.Part.HybridBodies]:
            for i in range(1,collection.Count+1):
                selection.Add(collection.Item(i));assert selection.VisProperties.GetShow()==(0,1);selection.Clear()
        selection.Add(doc.Part.MainBody);assert selection.VisProperties.GetShow()==(0,0);selection.Clear()
        assert sum(doc.Part.AxisSystems.Item(i).Name=='B10_DesignAxis' for i in range(1,doc.Part.AxisSystems.Count+1))==1
        axes={}
        for method,expected_vector in [('GetOrigin',[10,20,30]),('GetXAxis',[1,0,0]),('GetYAxis',[0,1,0]),('GetZAxis',[0,0,1])]:
            values=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
            axis._oleobj_.Invoke(axis._oleobj_.GetIDsOfNames(method),0,1,0,values)
            axes[method]=list(values.value)
            assert math.dist(values.value,expected_vector)<1e-8
    finally:doc.Close()
    report={'fixture_only':True,'passed':True,'published_volume_mm3':volume,'published_axis':axes,
            'display_persisted':True,'clean_build_matches':True,'retained_assets_unchanged':True,'recovery':state['recovery'],
            'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
