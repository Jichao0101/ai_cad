"""统一开发验收入口：跨进程构建、检查失败恢复、复验及移交，最终模型保持打开。"""
import json,subprocess,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-integrated-%Y%m%d-%H%M%S-%f');output.mkdir()
    definition=root/'tests/fixtures/steering_integrated_flow.json'
    # 所有建模/恢复/移交均经过交付CLI；JSON请求保留，方便检查和复跑。
    def command(name,label,request):
        path=output/(label+'.json');path.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
        process=subprocess.run([sys.executable,'-X','utf8',str(root/'tools/steering_cli.py'),name,str(path)],capture_output=True,text=True,encoding='utf-8')
        if process.returncode:raise RuntimeError(process.stderr)
        state=json.loads(process.stdout)
        (output/(label+'-result.json')).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        print(label+': '+state.get('status',state.get('release_status','described')),flush=True)
        return state
    command('describe','describe',{'flow':str(definition)})
    first=command('start','start',{'flow':str(definition),'runs_root':str(output/'builds'),'parameters':{'section_radius_mm':5.0}})
    assert first['status']=='check_failed' and first['check']['step']=='union',first.get('error')
    assert 'published_skeleton' not in first['outputs']
    retained={key:first['outputs'][key] for key in ['basis','baffle_part','half_spoke','spoke_part']}
    state=command('resume','resume',{'run_directory':first['run_directory'],'expected_revision':first['revision'],'parameter_changes':{'section_radius_mm':5.5}})
    assert state['status']=='completed',state.get('error')
    assert state['run_id']==first['run_id'] and state['attempts']==[first['parameters'],state['parameters']]
    assert state['recovery']['execute']==['rim','rim_mirror','union','domains','publications']
    folder=Path(state['run_directory'])
    assert all(state['outputs'][key]==record and runtime.digest(folder/record['file'])==record['sha256'] for key,record in retained.items())
    assert state['flow']==first['flow'] and state['flow_signature']==first['flow_signature']
    assert state['outputs']['step_evidence']['measurements']['step_solid_count']==1
    volume=state['outputs']['skeleton_part']['measurements']['volume_mm3']
    clean=command('start','clean',{'flow':str(definition),'runs_root':str(output/'clean'),'parameters':state['parameters']})
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['skeleton_part']['measurements']['volume_mm3']-volume)<1e-6
    before=runtime.digest(folder/'state.json')
    delivery=command('handover','handover',{'run_directory':str(folder),'expected_revision':state['revision'],'asset_id':'published_skeleton','destination':str(output/'handover')})
    assert runtime.digest(folder/'state.json')==before
    manifest=runtime.read(delivery['manifest']);target=Path(delivery['directory'])
    assert all(runtime.digest(target/name)==digest for name,digest in manifest['files'].items())
    assert any(name.endswith('.stp') for name in manifest['files'])
    assert len(manifest['check_reports'])==2 and manifest['ds_status']=='not_evaluated'
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Open(str(target/delivery['model_file']))
    try:
        part=doc.Part;pubs=doc.Product.Publications
        measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(pubs.Item('SkeletonSolid').Valuation).Volume*1e9
        assert abs(measured-volume)<1e-6
        assert pubs.Item('DesignAxis').Valuation.DisplayName
        selection=doc.Selection
        for i in range(1,part.Bodies.Count+1):
            body=part.Bodies.Item(i);selection.Clear();selection.Add(body)
            assert selection.VisProperties.GetShow()==(0,0 if body.Name==part.MainBody.Name else 1)
        selection.Clear();doc.Activate();app.Visible=True
        viewer=app.ActiveWindow.ActiveViewer;view=viewer.Viewpoint3D
        view.PutSightDirection((0.0,0.0,-1.0));view.PutUpDirection((0.0,1.0,0.0))
        viewer.Viewpoint3D=view;viewer.Reframe();viewer.Update()
    except Exception:
        doc.Close();raise
    report={'passed':True,'fixture_only':True,'run_id':state['run_id'],'run_directory':str(folder),
        'initial_volume_mm3':first['outputs']['skeleton_part']['measurements']['volume_mm3'],
        'updated_volume_mm3':volume,'reopened_volume_mm3':measured,'recovery':state['recovery'],
        'retained_assets_unchanged':True,'clean_build_matches':True,'rules_unchanged':True,
        'step_solid_count':1,'handover':delivery,'model_kept_open':True,'ds_status':'not_evaluated'}
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
