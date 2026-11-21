"""验证真实Publication保存重开、改参重建和错误目标拒绝。"""
import copy,json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,publications


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-publications-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json');definition['steps'][1].pop('check')
    bindings={'SkeletonSolid':[{'collection':'Bodies','name':'B20_Baffle'}],
              'DesignAxis':[{'collection':'AxisSystems','name':'B10_DesignAxis'}]}
    definition['steps'].append({'id':'publications','operation':'publish_references','inputs':{'source':'baffle_part'},
                                'output':'published_part','parameters':{'publications':bindings,'prepare_display':True}})
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    app=win32com.client.GetActiveObject('CATIA.Application')
    def inspect(state,expected):
        doc=app.Documents.Open(str(folder/state['outputs']['published_part']['file']))
        try:
            pubs=doc.Product.Publications
            assert pubs.Count==2
            volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(pubs.Item('SkeletonSolid').Valuation).Volume*1e9
            assert abs(volume-expected)<1e-5
            selection=doc.Selection;selection.Clear();selection.Add(pubs.Item('DesignAxis').Valuation)
            assert selection.Item2(1).Value.Name=='B10_DesignAxis';selection.Clear()
            for collection in [doc.Part.AxisSystems,doc.Part.HybridBodies,doc.Part.MainBody.Sketches]:
                for i in range(1,collection.Count+1):
                    selection.Add(collection.Item(i))
                    assert selection.VisProperties.GetShow()==(0,1)
                    selection.Clear()
            selection.Add(doc.Part.MainBody)
            assert selection.VisProperties.GetShow()==(0,0);selection.Clear()
            try:publications.create(doc,bindings)
            except ValueError as error:assert 'already exists' in str(error)
            else:raise AssertionError('Existing publication was overwritten')
            assert pubs.Count==2
            return volume
        finally:doc.Close()
    before=inspect(state,20160);basis=state['outputs']['basis'].copy();source=state['outputs']['baffle_part'].copy()
    state=runtime.resume(folder,state['revision'],{'thickness_mm':10})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['baffle','publications']
    assert state['outputs']['basis']==basis
    assert runtime.digest(folder/source['file'])==source['sha256']
    after=inspect(state,24000)
    bad=copy.deepcopy(definition);bad['steps'][-1]['parameters']['publications']['SkeletonSolid'][0]['name']='MissingBody'
    _,bad_state=runtime.start(bad,{},output)
    assert bad_state['status']=='execution_error' and 'unique object' in bad_state['error']
    assert 'published_part' not in bad_state['outputs']
    report={'fixture_only':True,'passed':True,'before_volume_mm3':before,'after_volume_mm3':after,
            'publications':state['outputs']['published_part']['measurements'],'recovery':state['recovery'],
            'original_asset_unchanged':True,'display_persisted':True,'duplicate_rejected':True,'missing_object_rejected':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
