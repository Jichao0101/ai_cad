"""Run a registered pipeline continuously; ask the host only for parameter decisions."""
import copy
import os
import re
from pathlib import Path
import executor as engine
import operations as cad


def definition():
    flow=engine.read_json(cad.HOME/'pipeline.json')
    # The format is intentionally limited to the delivered case, not arbitrary code.
    engine.fields(flow,['id','version','parameters','steps','check','recovery'])
    if flow['recovery']!={'mode':'parameter_decision','max_builds':4}:
        raise ValueError('Unsupported recovery policy')
    ids=set();outputs=set();bound=set()
    for step in flow['steps']:
        engine.fields(step,['id','operation','inputs','parameters','output'])
        if step['id'] in ids or step['output'] in outputs or any(v not in outputs for v in step['inputs'].values()):
            raise ValueError('Pipeline dependencies must precede their consumers')
        ids.add(step['id']);outputs.add(step['output'])
        for value in step['parameters'].values():
            if isinstance(value,dict):
                engine.fields(value,['parameter']);bound.add(value['parameter'])
    if bound!=set(flow['parameters']) or flow['check']['after_step']!=flow['steps'][-1]['id']:
        raise ValueError('Each parameter must be bound; final check must follow final step')
    if flow['check']['target'] not in outputs or flow['check']['checks']!=['minimum_volume']:
        raise ValueError('Invalid pipeline check')
    return flow


def parameters(flow, supplied, policy, previous=None):
    if not isinstance(supplied,dict) or set(supplied)-set(flow['parameters']):
        raise ValueError('Unknown parameter')
    result=copy.deepcopy(previous or {})
    for name,spec in flow['parameters'].items():
        if name in supplied:
            value=supplied[name];source='user_or_model'
        elif name in result:
            continue
        elif 'default' in spec:
            value=spec['default'];source='default: '+spec['source']
        else:
            continue
        if not engine.number(value) or not policy[spec['policy_min']]<=value<=policy[spec['policy_max']]:
            raise ValueError('Parameter outside fixed bounds: '+name)
        result[name]={'value':float(value),'unit':spec['unit'],'source':source}
    return result


def resolved(step, values):
    result=copy.deepcopy(step)
    for name,value in result['parameters'].items():
        if isinstance(value,dict):
            result['parameters'][name]=values[value['parameter']]['value']
    return result


def response(state):
    result=engine.view(state)
    result.update(parameters=state['automatic']['parameters'],
                  pipeline=state['automatic']['flow']['id'],
                  recovery=state['automatic'].get('recovery'),
                  attempted_parameters=state['automatic']['attempts'])
    if state['status']=='check_failed':
        result['decision']={'reason':'engineering_check_failed','allowed_changes':list(state['automatic']['flow']['parameters']),
                            'next_action':'resume with parameter_changes; executor selects rollback'}
    elif state['status']=='needs_input':
        result['decision']={'reason':'missing_parameters','required':state['automatic']['missing']}
    elif state['status']=='execution_error':
        result['decision']={'reason':'technical_error','error':state['automatic']['error'],
                            'next_action':'resolve technical issue before explicit resume with empty changes'}
    return result


def drive(folder,state):
    flow=state['automatic']['flow']
    try:
        done={s['id'] for s in state['steps']}
        for step in flow['steps']:
            if step['id'] in done:continue
            missing=[v['parameter'] for v in step['parameters'].values() if isinstance(v,dict) and v['parameter'] not in state['automatic']['parameters']]
            if missing:
                state['status']='needs_input';state['automatic']['missing']=missing
                engine.publish(folder,state,'needs_input',{'parameters':missing})
                return response(state)
            engine.execute(folder,state,[resolved(step,state['automatic']['parameters'])])
            state=engine.read_json(folder/'state.json')
        values={k:v['value'] for k,v in state['automatic']['parameters'].items()}
        if values not in state['automatic']['attempts']:
            state['automatic']['attempts'].append(values)
            engine.publish(folder,state,'candidate_built',{'parameters':values})
        check=flow['check']
        engine.inspect(folder,state,check['target'],check['checks'])
        state=engine.read_json(folder/'state.json')
    except Exception as error:
        # Every completed step is committed. Never infer completion from COM memory.
        state=engine.read_json(folder/'state.json')
        state['status']='execution_error';state['automatic']['error']=str(error)
        engine.publish(folder,state,'execution_error',{'error':str(error)})
    return response(state)


def rollback_plan(flow,completed,changed):
    affected=set();affected_outputs=set();first=None
    for index,step in enumerate(flow['steps']):
        bound={v['parameter'] for v in step['parameters'].values() if isinstance(v,dict)}
        if bound & changed or any(v in affected_outputs for v in step['inputs'].values()):
            affected.add(step['id']);affected_outputs.add(step['output'])
            if first is None and step['id'] in completed:first=index
    if first is None:return None
    invalidated=[s['id'] for s in flow['steps'][first:] if s['id'] in completed]
    return {'before_step':flow['steps'][first]['id'],'dependency_affected':sorted(affected),
            'invalidated_steps':invalidated,'rerun_steps':[s['id'] for s in flow['steps'][first:]],
            'snapshot_extra_steps':[s for s in invalidated if s not in affected]}


def dispatch(command,request,workspace):
    workspace=Path(workspace).resolve()
    if command=='workflow':
        engine.fields(request,[])
        return {'definition':definition(),'commands':['workflow','start','inspect','resume'],
                'scope':'frozen historical placement; one radius parameter; DS not evaluated','process_id':os.getpid()}
    if command=='start':
        engine.fields(request,['policy','parameters']);engine.policy_valid(request['policy'])
        flow=definition();values=parameters(flow,request['parameters'],request['policy'])
        # Validate all currently resolvable geometry requests before creating a file.
        if set(values)==set(flow['parameters']):
            engine.validate_steps([resolved(s,values) for s in flow['steps']],{'objects':{},'steps':[],'builds':0,'policy':request['policy']})
        result=engine.start(workspace,{'policy':request['policy']})
        folder=workspace/result['run_id']
        with engine.lock(folder):
            state=engine.read_json(folder/'state.json')
            state['automatic']={'flow':flow,'parameters':values,'attempts':[],'recovery':None}
            engine.publish(folder,state,'pipeline_started',{'pipeline':flow['id'],'version':flow['version']})
            return drive(folder,state)
    engine.fields(request,['run_id'] if command=='inspect' else ['run_id','expected_revision','parameter_changes'])
    run_id=request['run_id']
    if not isinstance(run_id,str) or not re.fullmatch(r'run-[0-9a-f]{32}',run_id):raise ValueError('Invalid run ID')
    folder=(workspace/run_id).resolve(strict=True)
    if folder.parent!=workspace:raise ValueError('Run escaped workspace')
    with engine.lock(folder):
        state=engine.read_json(folder/'state.json')
        if 'automatic' not in state:raise ValueError('Not an automatic pipeline run')
        if command=='inspect':return response(state)
        if type(request['expected_revision']) is not int or request['expected_revision']!=state['revision']:
            raise ValueError('Stale revision; inspect before retrying')
        if state['identity']!=engine.identity():raise ValueError('Code or pipeline changed; start a new run')
        cad.sources()
        if state['status'] not in ('check_failed','needs_input','ready','execution_error'):
            raise ValueError('Run is already complete')
        changes=request['parameter_changes']
        if state['status']=='execution_error' and changes:
            raise ValueError('Technical failures are not parameter decisions')
        values=parameters(state['automatic']['flow'],changes,state['policy'],state['automatic']['parameters'])
        changed={k for k,v in values.items() if k not in state['automatic']['parameters'] or v['value']!=state['automatic']['parameters'][k]['value']}
        if state['status'] in ('check_failed','needs_input') and not changed:
            raise ValueError('Supply a new parameter value')
        if changed and {k:v['value'] for k,v in values.items()} in state['automatic']['attempts']:
            raise ValueError('Parameter combination already attempted')
        if state['builds']>=4 and changed:raise ValueError('Build budget exhausted')
        plan=rollback_plan(state['automatic']['flow'],{s['id'] for s in state['steps']},changed)
        state['automatic']['parameters']=values
        state['automatic']['recovery']=plan
        if plan:
            engine.restore(folder,state,plan['before_step'])
            state=engine.read_json(folder/'state.json')
        else:
            state['status']='ready'
            engine.publish(folder,state,'continue',{'parameter_changes':changes})
        return drive(folder,state)
