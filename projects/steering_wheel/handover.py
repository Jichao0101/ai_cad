"""导出可复核的开发阶段移交包；不授予工程发布状态。"""
import hashlib,json,shutil
from pathlib import Path
from . import runtime


def export(folder,expected_revision,asset_id,destination):
    folder=Path(folder).resolve();destination=Path(destination).resolve()
    if destination==folder or destination.is_relative_to(folder) or folder.is_relative_to(destination):
        raise ValueError('Handover destination must be separate from the run directory')
    with runtime.lock(folder):
        state=runtime.read(folder/'state.json')
        if state['revision']!=expected_revision:raise ValueError('Stale revision')
        if state['status']!='completed':raise ValueError('Handover requires a completed configured flow')
        if state.get('flow_signature')!=hashlib.sha256(json.dumps(state['flow'],sort_keys=True).encode()).hexdigest():
            raise ValueError('Flow version changed or checkpoint lacks a flow signature')
        if asset_id not in state['outputs']:raise ValueError('Unknown handover asset')
        selected=state['outputs'][asset_id]
        if Path(selected['file']).suffix.lower()!='.catpart':raise ValueError('Handover asset must be a CATPart')
        for record in state['outputs'].values():
            if runtime.digest(folder/record['file'])!=record['sha256']:raise ValueError('Stage asset changed outside executor')
        expected_files={selected['file']:selected['sha256']}
        for step in state['flow']['steps']:
            if step['operation']=='solid_domains':
                record=state['outputs'][step['output']]
                expected_files[record['file']]=record['sha256']
        for step_id,record in state.get('check_reports',{}).items():
            if runtime.digest(folder/record['file'])!=record['sha256']:raise ValueError('Check report changed')
            report=runtime.read(folder/record['file'])
            step=next(s for s in state['flow']['steps'] if s['id']==step_id)
            if not report['passed'] or report['output']!=state['outputs'][step['output']]:
                raise ValueError('Check report does not match current completed output')
            expected_files[record['file']]=record['sha256']
        for step_id,approval in state.get('confirmations',{}).items():
            name='confirmation-'+step_id+'-'+approval['fingerprint']+'.json'
            if runtime.digest(folder/name)!=approval['fingerprint']:raise ValueError('Confirmation report changed')
            expected_files[name]=approval['fingerprint']
        destination.mkdir(parents=True,exist_ok=False)
        files={}
        for name,expected_hash in expected_files.items():
            shutil.copyfile(folder/name,destination/name)
            copied_hash=runtime.digest(destination/name)
            if copied_hash!=expected_hash:raise ValueError('Asset changed during export')
            files[name]=copied_hash
        basis_files=[]
        for step in state['flow']['steps']:
            if step['operation']=='datum' and step['output'] in state['outputs']:
                record=state['outputs'][step['output']]
                shutil.copyfile(folder/record['file'],destination/record['file'])
                if runtime.digest(destination/record['file'])!=record['sha256']:raise ValueError('Basis changed during export')
                files[record['file']]=record['sha256'];basis_files.append(record['file'])
        manifest={'release_status':'development_only','fixture_only':state['flow'].get('fixture_only',False),
                  'run_id':state['run_id'],'revision':state['revision'],'workflow_status':state['status'],
                  'flow_signature':state['flow_signature'],'execution_signature':state.get('execution_signature'),
                  'asset_id':asset_id,'model_file':selected['file'],'basis_files':basis_files,
                  'parameters':state['parameters'],'parameter_specs':state['flow']['parameters'],
                  'ds_status':state['ds_status'],'confirmations':state.get('confirmations',{}),
                  'check_reports':state.get('check_reports',{}),'asset_measurements':selected['measurements'],
                  'input_versions':{name:record['sha256'] for name,record in state['outputs'].items()},
                  'unverified_scope':['Actual CAS engineering acceptance','Complete applicable DS','CAE material addition','Frozen-region verification'],
                  'files':files}
        (destination/'handover.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        text=(f"# 方向盘开发阶段移交\n\n运行：{state['run_id']}，revision：{state['revision']}。\n\n"
              f"模型：{selected['file']}。参数、基准、报告和文件哈希见 handover.json。\n\n"
              f"配置流程状态：{state['status']}；DS状态：{state['ds_status']}；机制夹具：{manifest['fixture_only']}。\n\n"
              "本包仅用于开发复核。真实CAS验收、完整DS、CAE加料和冻结区验证尚未在本移交接口中获得验收证明，不能作为正式工程发布。\n")
        (destination/'README.md').write_text(text,encoding='utf-8')
        return {'directory':str(destination),'manifest':str(destination/'handover.json'),
                'release_status':'development_only','model_file':selected['file'],'files':len(files)}
