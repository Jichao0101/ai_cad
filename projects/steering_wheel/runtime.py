"""阶段资产执行器：参数变更按依赖失效，未变分支保留原文件。"""
import hashlib,json,math,os,re,uuid,shutil
from contextlib import contextmanager
from pathlib import Path
from . import datum,baffle,flow,rim_segment,rim_bridge,spline_segment,combine,spoke,mirror,clearance,column_axis,plane_surface,surface_projection,circular_profile,symmetry_points,native_guide,publications,placement,checks,inputs as input_assets
from . import solid_domains
from . import edge_fillet
from . import surface_guide


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execution_signature():
    """记录执行模块版本，供所有续跑入口校验。"""
    files={path.name:digest(path) for path in sorted(Path(__file__).parent.glob('*.py'))}
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def verify_versions(state):
    """所有续跑入口共用版本边界；代码或规则迁移不能隐式复用旧检查点。"""
    if state.get('execution_signature')!=execution_signature():
        raise ValueError('Execution code version changed or checkpoint lacks a code signature')
    if state.get('flow_signature')!=hashlib.sha256(json.dumps(state['flow'],sort_keys=True).encode()).hexdigest():
        raise ValueError('Flow version changed or checkpoint lacks a flow signature')


def publish(folder,state):
    state['revision']+=1
    temporary=folder/'state.tmp'
    temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temporary,folder/'state.json')


@contextmanager
def lock(folder):
    import msvcrt
    with (folder/'run.lock').open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        try:yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def values_for(specs,changes,previous=None):
    result=dict(previous or {})
    if set(changes)-set(specs):raise ValueError('Unknown parameter')
    for name,spec in specs.items():
        value=changes.get(name,result.get(name,spec.get('default')))
        if value is None:raise ValueError('Missing parameter: '+name)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not spec['min']<=value<=spec['max']:
            raise ValueError('Parameter outside declared range: '+name)
        result[name]=float(value)
    return result


def check_step(folder,state,step,measured):
    results=checks.evaluate(step,measured)
    if not results:return True
    failed=[result for result in results if not result['passed']]
    state['check']={'step':step['id'],**(failed or results)[0],'results':results}
    payload={'run_id':state['run_id'],'step':step['id'],'output':state['outputs'][step['output']],
             'results':results,'passed':not failed,'ds_status':state['ds_status']}
    data=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    fingerprint=hashlib.sha256(data).hexdigest()
    name='checks-'+step['id']+'-'+fingerprint+'.json'
    (folder/name).write_bytes(data)
    record={'file':name,'sha256':fingerprint,'passed':not failed}
    reports=state.setdefault('check_reports',{})
    if reports.get(step['id'])!=record:
        state['events'].append({'event':'checks_evaluated','step':step['id'],'attempt':len(state['attempts']),**record})
    reports[step['id']]=record
    if failed:
        state['status']='check_failed';publish(folder,state);return False
    return True


def confirmation_report(state,step):
    """仅绑定本阶段参数与输入/输出版本，无关分支改参不使确认失效。"""
    payload={'run_id':state['run_id'],'step':step,
             'parameters':flow.resolve(step['parameters'],state['parameters']),
             'parameter_specs':{name:state['flow']['parameters'][name] for name in sorted(flow.parameter_names(step['parameters']))},
             'inputs':{role:state['outputs'][name] for role,name in step['inputs'].items()},
             'output':state['outputs'][step['output']],
             'checks':checks.evaluate(step,state['outputs'][step['output']]['measurements']),
             'ds_status':state['ds_status']}
    return json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')


def stage_gate(folder,state,step):
    if not check_step(folder,state,step,state['outputs'][step['output']]['measurements']):return False
    if not step.get('requires_confirmation',False):return True
    report=confirmation_report(state,step)
    fingerprint=hashlib.sha256(report).hexdigest()
    if state.get('confirmations',{}).get(step['id'],{}).get('fingerprint')==fingerprint:return True
    name='confirmation-'+step['id']+'-'+fingerprint+'.json'
    (folder/name).write_bytes(report)
    state['pending_confirmation']={'step':step['id'],'fingerprint':fingerprint,'report':name}
    state['status']='waiting_confirmation'
    publish(folder,state)
    return False


def drive(folder,state):
    import win32com.client
    app=None;current_step=None
    try:
        for step in flow.ordered_steps(state['flow']):
            current_step=step['id']
            if step['id'] in state['completed']:
                if not stage_gate(folder,state,step):return state
                continue
            parameters=flow.resolve(step['parameters'],state['parameters'])
            inputs={role:state['outputs'][name] for role,name in step['inputs'].items()}
            path=folder/(step['id']+'-'+uuid.uuid4().hex)
            if step['operation']=='datum':
                if 'column' in inputs:
                    if 'column_point' in parameters or 'column_direction' in parameters:raise ValueError('Choose CAD column input or explicit column coordinates, not both')
                    column=read(folder/inputs['column']['file'])
                    parameters={**parameters,'column_point':column['point_mm'],'column_direction':column['direction']}
                planes={}
                for role in ['bottom','symmetry']:
                    if role in inputs:
                        if role+'_point' in parameters or role+'_normal' in parameters:raise ValueError('Choose CAD '+role+' plane or explicit coordinates, not both')
                        planes[role]=read(folder/inputs[role]['file'])
                        parameters={**parameters,role+'_point':planes[role]['point_mm'],role+'_normal':planes[role]['normal']}
                if 'bottom_surface' in inputs:
                    if 'bottom' in inputs or 'bottom_point' in parameters or 'bottom_normal' in parameters:
                        raise ValueError('Choose native bottom surface or planar bottom input, not both')
                    if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                    source=inputs['bottom_surface'];binding=source['input_manifest']['objects'][parameters['bottom_surface_binding']]
                    seed,_,direction=datum.projection_seed(parameters)
                    projection=surface_projection.project(app,folder/source['file'],binding,seed,direction,parameters['projection_extent_mm'])
                    result=datum.solve(parameters,projection['origin_mm'])
                    result['surface_projection']={**projection,'source_sha256':source['sha256']}
                else:result=datum.solve(parameters)
                if 'bottom' in planes:
                    if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                    plane=planes['bottom']
                    distance=plane_surface.point_distance(app,folder/plane['source_file'],plane['scope'],result['origin_mm'])
                    if not math.isfinite(distance) or distance>1e-6:raise ValueError('Projected origin lies outside the bound bottom surface')
                    result['bottom_projection_distance_mm']=distance
                path=path.with_suffix('.json')
                path.write_text(json.dumps(result,indent=2),encoding='utf-8')
                measured={}
            elif step['operation']=='circular_profile':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                source=inputs['source'];object_path=source['input_manifest']['objects'][parameters['surface_binding']]
                result=circular_profile.extract(app,folder/source['file'],object_path,read(folder/inputs['basis']['file']),parameters['radial_inset_mm'],parameters.get('plane_offset_mm',0))
                result['source_sha256']=source['sha256']
                path=path.with_suffix('.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                measured={k:result[k] for k in ['radius_mm','source_radius_mm','radial_inset_mm']}
            elif step['operation']=='symmetry_points':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                source=inputs['source'];bindings=source['input_manifest']['objects']
                pairs=[[bindings[name] for name in pair] for pair in parameters['point_pairs']]
                result=symmetry_points.extract(app,folder/source['file'],pairs,parameters['positive_normal'])
                result['source_sha256']=source['sha256']
                path=path.with_suffix('.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                measured={'maximum_pair_deviation_mm':result['maximum_pair_deviation_mm']}
            elif step['operation']=='plane_surface':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                source=inputs['source'];object_path=source['input_manifest']['objects'][parameters['surface_binding']]
                result=plane_surface.extract(app,folder/source['file'],object_path,parameters['positive_normal'])
                result.update(source_file=source['file'],source_sha256=source['sha256'])
                path=path.with_suffix('.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                measured={}
            elif step['operation']=='column_axis':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                source=inputs['source']
                object_path=source['input_manifest']['objects'][parameters['scope_binding']]
                result=column_axis.extract(app,folder/source['file'],object_path,parameters['positive_direction'])
                result['source_sha256']=source['sha256']
                path=path.with_suffix('.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                measured={'radius_mm':result['radius_mm']}
            elif step['operation'] in {'baffle','rim_segment','rim_bridge','spline_segment','spoke'}:
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                basis=read(folder/inputs['basis']['file'])
                if step['operation']=='rim_bridge' and 'endpoints' in parameters:
                    if set(parameters)!={'endpoints'}:
                        raise ValueError('Choose upstream endpoint bindings or explicit bridge sections, not both')
                    parameters=rim_bridge.from_endpoints(basis,{key:value for key,value in inputs.items() if key!='basis'},parameters['endpoints'])
                doc=app.Documents.Add('Part')
                path=path.with_suffix('.CATPart')
                try:
                    datum.create(doc,basis)
                    if step['operation']=='baffle':
                        if 'profile' in inputs:
                            if 'outline' in parameters or 'radius_mm' in parameters:raise ValueError('Choose measured profile input or explicit outline/radius, not both')
                            profile=read(folder/inputs['profile']['file'])
                            baffle.create(doc,None,profile['sketch_frame'],parameters['thickness_mm'],profile['radius_mm'])
                        else:baffle.create(doc,parameters.get('outline'),basis['sketch_frame'],parameters['thickness_mm'],parameters.get('radius_mm'))
                        measured=baffle.measure(doc)
                    elif step['operation']=='rim_segment':
                        measured=rim_segment.create(doc,basis,parameters)
                    elif step['operation']=='spline_segment':
                        measured=spline_segment.create(doc,basis,parameters)
                    elif step['operation']=='rim_bridge':
                        measured=rim_bridge.create(doc,basis,parameters)
                    else:
                        measured=spoke.create(doc,basis,parameters)
                    doc.SaveAs(str(path))
                finally:doc.Close()
            elif step['operation']=='solid_domains':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                path=path.with_suffix('.stp')
                measured=solid_domains.measure(app,folder/inputs['source']['file'],path)
            elif step['operation']=='clearance':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                object_paths=[inputs[role]['input_manifest']['objects'][parameters[role+'_binding']]
                              if role+'_binding' in parameters else None for role in ['first','second']]
                measured=clearance.measure(app,folder/inputs['first']['file'],folder/inputs['second']['file'],object_paths)
                path=path.with_suffix('.json')
                path.write_text(json.dumps({'measurements':measured,'inputs':inputs},ensure_ascii=False,indent=2),encoding='utf-8')
            elif step['operation']=='edge_fillet':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                path=path.with_suffix('.CATPart');shutil.copyfile(folder/inputs['source']['file'],path)
                doc=app.Documents.Open(str(path))
                try:
                    measured=edge_fillet.create(doc,parameters)
                    doc.Save()
                finally:doc.Close()
            elif step['operation']=='place':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                if 'basis' in inputs and 'target_frame' in parameters:raise ValueError('Choose basis or explicit target frame, not both')
                target=read(folder/inputs['basis']['file']) if 'basis' in inputs else parameters['target_frame']
                path=path.with_suffix('.CATPart');shutil.copyfile(folder/inputs['source']['file'],path)
                doc=app.Documents.Open(str(path))
                try:
                    measured=placement.create(doc,parameters['source_frame'],target,parameters.get('clocking_deg'))
                    doc.Save()
                finally:doc.Close()
            elif step['operation']=='publish_references':
                if not isinstance(parameters.get('prepare_display',False),bool):
                    raise ValueError('prepare_display must be a boolean')
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                path=path.with_suffix('.CATPart');shutil.copyfile(folder/inputs['source']['file'],path)
                doc=app.Documents.Open(str(path))
                try:
                    measured=publications.create(doc,parameters['publications'])
                    if parameters.get('prepare_display',False):
                        measured['display']=publications.prepare_display(doc)
                    doc.Save()
                finally:doc.Close()
            elif step['operation']=='surface_guide':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                source=inputs['source'];binding=source['input_manifest']['objects'][parameters['surface_binding']]
                path=path.with_suffix('.CATPart');shutil.copyfile(folder/source['file'],path)
                doc=app.Documents.Open(str(path))
                try:
                    measured=surface_guide.create(doc,binding,read(folder/inputs['basis']['file']),parameters['plane_offset_mm'],parameters.get('start_hint_mm'))
                    doc.Save()
                finally:doc.Close()
            elif step['operation']=='native_guide':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                if ('guide_binding' in parameters)==('guide_path' in parameters):
                    raise ValueError('Choose exactly one guide binding or generated object path')
                source=inputs['source']
                binding=parameters['guide_path'] if 'guide_path' in parameters else source['input_manifest']['objects'][parameters['guide_binding']]
                path=path.with_suffix('.CATPart');shutil.copyfile(folder/source['file'],path)
                doc=app.Documents.Open(str(path))
                try:
                    measured=native_guide.create(doc,binding,parameters.get('section_radius_mm'),parameters.get('start_fraction',0),parameters.get('end_fraction',1),parameters.get('rectangle'))
                    doc.Save()
                finally:doc.Close()
            elif step['operation']=='mirror':
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                path=path.with_suffix('.CATPart')
                shutil.copyfile(folder/inputs['source']['file'],path)
                doc=app.Documents.Open(str(path))
                try:
                    measured=mirror.create(doc,read(folder/inputs['basis']['file']))
                    doc.Save()
                finally:doc.Close()
            elif step['operation'] in {'combine','subtract'}:
                if app is None:app=win32com.client.GetActiveObject('CATIA.Application')
                doc=app.Documents.Add('Part')
                path=path.with_suffix('.CATPart')
                try:
                    roles=['stock','tool'] if step['operation']=='subtract' else list(inputs)
                    if step['operation']=='combine' and 'basis' in inputs:
                        datum.create(doc,read(folder/inputs['basis']['file']))
                        roles.remove('basis')
                    if step['operation']=='subtract' and set(inputs)!={'stock','tool'}:
                        raise ValueError('Subtract requires exactly stock and tool inputs')
                    measured=combine.create(app,doc,[(role,folder/inputs[role]['file']) for role in roles],
                                            mode='subtract' if step['operation']=='subtract' else 'union')
                    doc.SaveAs(str(path))
                finally:doc.Close()
            else:raise ValueError('Operation not implemented: '+step['operation'])
            state['outputs'][step['output']]={'file':path.name,'sha256':digest(path),'measurements':measured}
            state['completed'].append(step['id'])
            state['events'].append({'step':step['id'],'attempt':len(state['attempts']),'file':path.name})
            publish(folder,state)
            if not stage_gate(folder,state,step):return state
        state['status']='completed'
        publish(folder,state)
        return state
    except Exception as error:
        state['status']='execution_error';state['error']=str(error);state['failed_step']=current_step
        state['events'].append({'event':'execution_error','step':current_step,'attempt':len(state['attempts']),'error':str(error)})
        publish(folder,state)
        return state


def start(definition,parameters,root):
    ordered=flow.ordered_steps(definition)
    for step in ordered:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',step['id']):raise ValueError('Invalid step ID')
        if step['operation'] not in {'datum','baffle','rim_segment','rim_bridge','spline_segment','combine','subtract','spoke','mirror','clearance','solid_domains','edge_fillet','column_axis','plane_surface','circular_profile','symmetry_points','native_guide','surface_guide','publish_references','place'}:raise ValueError('Operation not implemented: '+step['operation'])
        if type(step.get('requires_confirmation',False)) is not bool:raise ValueError('requires_confirmation must be boolean')
        checks.rules_for(step)
    if type(definition['max_attempts']) is not int or definition['max_attempts']<1:raise ValueError('Invalid attempt budget')
    if not isinstance(definition.get('external_objects',{}),dict):raise ValueError('External objects must map logical IDs to manifests')
    values=values_for(definition['parameters'],parameters)
    folder=Path(root).resolve()/('steering-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    state={'run_id':folder.name,'revision':0,'status':'running','flow':definition,
        'parameters':values,'completed':[],'outputs':{},'attempts':[values.copy()],
        'events':[],'confirmations':{},'ds_status':'not_evaluated','execution_signature':execution_signature(),
        'flow_signature':hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest()}
    with lock(folder):
        publish(folder,state)
        if not load_inputs(folder,state):return folder,state
        return folder,drive(folder,state)


def load_inputs(folder,state):
    try:
        records,issues=input_assets.load(folder,state['flow'].get('external_objects',{}))
    except Exception as error:
        state['status']='execution_error';state['error']=str(error);publish(folder,state);return False
    if issues:
        state['status']='needs_input';state['input_issues']=issues
        publish(folder,state);return False
    state['outputs'].update(records)
    state.pop('input_issues',None);state.pop('error',None)
    state['status']='running';publish(folder,state)
    return True


def retry_inputs(folder,expected_revision):
    """补齐固定清单中的缺项后重试；沿用同一运行与尝试预算。"""
    folder=Path(folder).resolve()
    with lock(folder):
        state=read(folder/'state.json')
        if state['revision']!=expected_revision:raise ValueError('Stale revision')
        if state['status']!='needs_input' or state['completed']:raise ValueError('Run is not waiting for initial inputs')
        verify_versions(state)
        if not load_inputs(folder,state):return state
        return drive(folder,state)


def retry(folder,expected_revision):
    """环境故障修复后，同参重试未完成步骤；计入原运行预算。"""
    folder=Path(folder).resolve()
    with lock(folder):
        state=read(folder/'state.json')
        if state['revision']!=expected_revision:raise ValueError('Stale revision')
        if state['status']!='execution_error':raise ValueError('Technical retry requires execution_error')
        verify_versions(state)
        if len(state['attempts'])>=state['flow']['max_attempts']:raise ValueError('Attempt budget exhausted')
        for record in state['outputs'].values():
            if digest(folder/record['file'])!=record['sha256']:raise ValueError('Stage asset changed outside executor')
        plan=flow.rebuild_plan(state['flow'],set(),state['completed'])
        state['events'].append({'event':'technical_retry','failed_step':state.get('failed_step'),
                                'previous_error':state.get('error'),'attempt':len(state['attempts'])+1})
        state['attempts'].append(state['parameters'].copy())
        state.update(status='running',recovery=plan)
        state.pop('error',None);state.pop('failed_step',None)
        publish(folder,state)
        if not set(state['flow'].get('external_objects',{}))<=set(state['outputs']):
            if not load_inputs(folder,state):return state
        return drive(folder,state)


def resume(folder,expected_revision,changes):
    folder=Path(folder).resolve()
    with lock(folder):
        state=read(folder/'state.json')
        if state['revision']!=expected_revision:raise ValueError('Stale revision')
        if state['status']=='needs_input':raise ValueError('Resolve initial inputs with retry_inputs before changing design parameters')
        verify_versions(state)
        if len(changes)!=1:raise ValueError('Change one design parameter per call')
        if len(state['attempts'])>=state['flow']['max_attempts']:raise ValueError('Attempt budget exhausted')
        values=values_for(state['flow']['parameters'],changes,state['parameters'])
        if values in state['attempts']:raise ValueError('Parameter candidate already attempted')
        for record in state['outputs'].values():
            if digest(folder/record['file'])!=record['sha256']:raise ValueError('Stage asset changed outside executor')
        plan=flow.rebuild_plan(state['flow'],set(changes),state['completed'])
        for step_id in plan['invalidated']:
            state.get('check_reports',{}).pop(step_id,None)
            previous=state.get('confirmations',{}).pop(step_id,None)
            if previous:state['events'].append({'event':'confirmation_invalidated','step':step_id,**previous})
        state.pop('pending_confirmation',None)
        state['completed']=list(plan['retained'])
        for name in plan['affected_outputs']:state['outputs'].pop(name,None)
        state.update(parameters=values,status='running',recovery=plan)
        state.pop('check',None);state.pop('error',None)
        state.pop('failed_step',None)
        state['attempts'].append(values.copy())
        publish(folder,state)
        return drive(folder,state)


def confirm(folder,expected_revision,fingerprint,confirmed_by):
    """宿主提交人工确认；确认人身份认证由宿主承担，不由字符串提供。"""
    folder=Path(folder).resolve()
    with lock(folder):
        state=read(folder/'state.json')
        if state['revision']!=expected_revision:raise ValueError('Stale revision')
        if state['status']!='waiting_confirmation':raise ValueError('Run is not waiting for confirmation')
        verify_versions(state)
        if not isinstance(confirmed_by,str) or not confirmed_by.strip():raise ValueError('Confirmation attribution required')
        pending=state['pending_confirmation']
        if fingerprint!=pending['fingerprint']:raise ValueError('Stale confirmation fingerprint')
        for record in state['outputs'].values():
            if digest(folder/record['file'])!=record['sha256']:raise ValueError('Stage asset changed outside executor')
        step=next(s for s in state['flow']['steps'] if s['id']==pending['step'])
        if hashlib.sha256(confirmation_report(state,step)).hexdigest()!=fingerprint or digest(folder/pending['report'])!=fingerprint:
            raise ValueError('Confirmation report or inputs changed')
        approval={'fingerprint':fingerprint,'confirmed_by':confirmed_by.strip()}
        state.setdefault('confirmations',{})[step['id']]=approval
        state['events'].append({'event':'confirmed','step':step['id'],**approval})
        state.pop('pending_confirmation');state['status']='running'
        publish(folder,state)
        return drive(folder,state)
