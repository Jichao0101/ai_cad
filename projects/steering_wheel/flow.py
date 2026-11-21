"""方向盘流程依赖与参数绑定；不调用模型或CAD，不推断快照恢复已完成。"""
from copy import deepcopy


def parameter_names(value):
    if isinstance(value,dict):
        if set(value)=={'parameter'}:
            if not isinstance(value['parameter'],str):
                raise ValueError('Parameter binding must name a parameter')
            return {value['parameter']}
        return set().union(*(parameter_names(v) for v in value.values()))
    if isinstance(value,list):
        return set().union(*(parameter_names(v) for v in value))
    return set()


def resolve(value, parameters):
    if isinstance(value,dict):
        if set(value)=={'parameter'}:
            name=value['parameter']
            if name not in parameters:
                raise ValueError('Missing parameter: '+name)
            return deepcopy(parameters[name])
        return {key:resolve(item,parameters) for key,item in value.items()}
    if isinstance(value,list):
        return [resolve(item,parameters) for item in value]
    return value


def ordered_steps(flow):
    """外部对象和生产者显式声明；依赖循环或引用缺项在CAD执行前拒绝。"""
    steps=flow['steps']
    ids=set();producers={};external=set(flow.get('external_objects',[]))
    declared=set(flow['parameters'])
    for step in steps:
        if not isinstance(step['id'],str) or not step['id'] or step['id'] in ids:
            raise ValueError('Duplicate or empty step ID')
        ids.add(step['id'])
        output=step['output']
        if not isinstance(output,str) or not output or output in producers or output in external:
            raise ValueError('Duplicate or invalid output')
        producers[output]=step['id']
        unknown=parameter_names(step['parameters'])-declared
        if unknown:
            raise ValueError('Undeclared parameters: '+', '.join(sorted(unknown)))
        if not isinstance(step['inputs'],dict) or any(not isinstance(v,str) for v in step['inputs'].values()):
            raise ValueError('Inputs must map roles to object IDs')
        for role,object_id in step['inputs'].items():
            manifest=flow.get('external_objects',{})
            spec=manifest.get(object_id,{}) if isinstance(manifest,dict) else {}
            if spec.get('coordinate_system')=='part_local' and (step['operation']!='place' or role!='source'):
                raise ValueError('Local-coordinate asset must first enter place as source: '+object_id)
    missing={v for step in steps for v in step['inputs'].values()}-set(producers)-external
    if missing:
        raise ValueError('Missing objects: '+', '.join(sorted(missing)))
    pending=list(steps);available=set(external);ordered=[]
    while pending:
        ready=[s for s in pending if set(s['inputs'].values())<=available]
        if not ready:
            raise ValueError('Cyclic step dependencies')
        for step in ready:
            ordered.append(step);available.add(step['output']);pending.remove(step)
    return ordered


def rebuild_plan(flow, changed_parameters, completed):
    """仅计算实际失效分支；CAD执行器必须另行证明保留对象没有被快照回退删除。"""
    ordered=ordered_steps(flow)
    changed=set(changed_parameters);done=set(completed)
    if changed-set(flow['parameters']):
        raise ValueError('Unknown changed parameter')
    if done-{s['id'] for s in ordered}:
        raise ValueError('Unknown completed step')
    producers={s['output']:s['id'] for s in ordered}
    for step in ordered:
        if step['id'] in done and any(producers[v] not in done for v in step['inputs'].values() if v in producers):
            raise ValueError('Completed step has incomplete dependencies')
    affected=set();outputs=set()
    for step in ordered:
        if parameter_names(step['parameters']) & changed or set(step['inputs'].values()) & outputs:
            affected.add(step['id']);outputs.add(step['output'])
    return {
        'invalidated':[s['id'] for s in ordered if s['id'] in affected & done],
        'retained':[s['id'] for s in ordered if s['id'] in done-affected],
        'execute':[s['id'] for s in ordered if s['id'] in affected or s['id'] not in done],
        'affected_outputs':[s['output'] for s in ordered if s['id'] in affected],
    }


def _binding_paths(value,path=''):
    """只列绑定所在字段的JSON Pointer，不展开固定几何或外部清单。"""
    if isinstance(value,dict):
        if set(value)=={'parameter'}:
            yield value['parameter'],path
        else:
            for key,item in value.items():
                escaped=str(key).replace('~','~0').replace('/','~1')
                yield from _binding_paths(item,path+'/'+escaped)
    elif isinstance(value,list):
        for index,item in enumerate(value):yield from _binding_paths(item,path+'/'+str(index))


def describe(definition):
    """给宿主的只读流程契约；影响范围复用执行器的同一个依赖算法。"""
    ordered=ordered_steps(definition);completed=[step['id'] for step in ordered]
    steps=[]
    for step in ordered:
        summary={key:deepcopy(step[key]) for key in ('id','operation','inputs','output','check','checks','requires_confirmation') if key in step}
        bindings={}
        for name,path in _binding_paths(step['parameters']):bindings.setdefault(name,[]).append(path)
        summary['parameter_bindings']=bindings
        steps.append(summary)
    effects={}
    for name in definition['parameters']:
        plan=rebuild_plan(definition,{name},completed)
        effects[name]={'direct_steps':[s['id'] for s in steps if name in s['parameter_bindings']],
                       'affected_steps':plan['invalidated'],'unaffected_steps':plan['retained']}
    return {'fixture_only':definition.get('fixture_only',False),'parameters':deepcopy(definition['parameters']),
            'max_attempts':definition['max_attempts'],'steps':steps,'parameter_effects':effects}
