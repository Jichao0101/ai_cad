"""方向盘开发模型宿主；不属于独立脚本与Skill交付包。"""
import argparse,http.client,json,os,subprocess,sys,urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from projects.steering_wheel import runtime


def tool_schemas(definition):
    parameters={'type':'object','properties':{name:{'type':'number','minimum':spec['min'],'maximum':spec['max']}
                for name,spec in definition['parameters'].items()},'additionalProperties':False}
    properties={'get_workflow':{},'start_build':{'parameters':parameters},
                'inspect_build':{'run_id':{'type':'string'}},
                'resume_build':{'run_id':{'type':'string'},'expected_revision':{'type':'integer'},'parameter_changes':parameters}}
    return [{'type':'function','function':{'name':name,'parameters':{'type':'object','properties':fields,
             'required':list(fields),'additionalProperties':False}}} for name,fields in properties.items()]


def model_state(state,folder):
    """只向模型返回决策所需状态和标量测量，不发送CAD内容或完整输入清单。"""
    result={key:state[key] for key in ['run_id','revision','status','parameters','attempts','completed','check',
            'recovery','pending_confirmation','input_issues','error','ds_status'] if key in state}
    result['measurements']={name:{k:v for k,v in record['measurements'].items() if isinstance(v,(int,float))}
                            for name,record in state['outputs'].items() if record['measurements']}
    for record in state['outputs'].values():
        if runtime.digest(Path(folder)/record['file'])!=record['sha256']:
            raise ValueError('Persisted asset differs from executor state')
    produced={step['output'] for step in state['flow']['steps']}
    result['saved_cad_outputs']=[name for name,record in state['outputs'].items()
                                 if name in produced and record['file'].lower().endswith('.catpart')]
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Redirects disabled')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prompt');parser.add_argument('--flow',type=Path,required=True)
    parser.add_argument('--allow-cloud',action='store_true')
    parser.add_argument('--keep-open',action='store_true')
    parser.add_argument('--continue-session',type=Path)
    args=parser.parse_args()
    env=ROOT/'.env.local'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key,value=line.split('=',1);os.environ.setdefault(key.strip(),value.strip().strip(chr(34)).strip(chr(39)))
    endpoint=os.environ.get('QWEN_BASE_URL','').rstrip('/');model=os.environ.get('QWEN_MODEL','')
    url=urlparse(endpoint);local=url.hostname in ('localhost','127.0.0.1','::1')
    if not model or not url.hostname or url.username or url.password or url.query or url.fragment:parser.error('Invalid model endpoint')
    if url.scheme not in ('http','https') or (not local and (not args.allow_cloud or url.scheme!='https')):
        parser.error('Public endpoint requires HTTPS and --allow-cloud')
    definition=runtime.read(args.flow)
    skill=(ROOT/'projects/steering_wheel/skill/steering-wheel-design/SKILL.md').read_text(encoding='utf-8')
    owned=None;latest=None;count=0
    skill_hash=runtime.digest(ROOT/'projects/steering_wheel/skill/steering-wheel-design/SKILL.md')
    if args.continue_session:
        folder=args.continue_session.resolve();frozen=folder/'flow.json'
        transcript=runtime.read(folder/'transcript.json')
        if runtime.read(frozen)!=definition or runtime.digest(frozen)!=transcript['flow_sha256'] or skill_hash!=transcript['skill_sha256']:
            raise ValueError('Cannot continue a session with changed flow or Skill')
        messages=transcript['messages'];count=sum(m['role']=='tool' for m in messages)
        if transcript['commands']:
            previous=transcript['commands'][-1]['result']
            owned=folder/'builds'/previous['run_id'];latest=runtime.read(owned/'state.json')
            if latest['revision']!=previous['revision']:raise ValueError('Run changed since recorded model session')
        messages.append({'role':'user','content':args.prompt})
    else:
        folder=ROOT/'runs'/datetime.now().strftime('qwen-steering-%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
        frozen=folder/'flow.json';frozen.write_text(json.dumps(definition,ensure_ascii=False,indent=2),encoding='utf-8')
        messages=[{'role':'system','content':skill},{'role':'user','content':args.prompt}]
        transcript={'model':model,'skill_sha256':skill_hash,'flow_sha256':runtime.digest(frozen),'messages':messages,'commands':[]}
    opener=urllib.request.build_opener(NoRedirect)
    try:
        for _ in range(max(0,16-count)):
            request=urllib.request.Request(endpoint+'/chat/completions',
                data=json.dumps({'model':model,'messages':messages,'tools':tool_schemas(definition),'tool_choice':'auto'}).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ.get('QWEN_API_KEY','')})
            for network_attempt in range(2):
                try:
                    with opener.open(request,timeout=90) as response:message=json.load(response)['choices'][0]['message']
                    break
                except http.client.RemoteDisconnected:
                    if network_attempt:raise
                    transcript.setdefault('network_events',[]).append({'event':'remote_disconnected','retry':1})
            messages.append({k:message[k] for k in ('role','content','tool_calls') if k in message})
            calls=message.get('tool_calls') or []
            if not calls:
                transcript['final_state']=latest
                print(json.dumps({'status':latest['status'] if latest else 'not_executed','acceptance_dir':str(folder),
                    'run_directory':str(owned) if owned else None,'assistant':message.get('content')},ensure_ascii=False),flush=True)
                return 0 if latest and latest['status']=='completed' else 2
            for call in calls:
                count+=1
                if count>16:raise ValueError('Tool call budget exhausted')
                name=call['function']['name'];fields=json.loads(call['function']['arguments'])
                if name=='get_workflow':
                    if fields:raise ValueError('get_workflow takes no arguments')
                    result=runtime.flow.describe(definition)
                else:
                    if name=='start_build':
                        if owned or set(fields)!={'parameters'}:raise ValueError('Only one start with parameter fields is allowed')
                        command='start';payload={'flow':str(frozen),'runs_root':str(folder/'builds'),'parameters':fields['parameters']}
                    else:
                        if not owned or fields.get('run_id')!=latest['run_id']:raise ValueError('Tool may access only this session run')
                        if name=='inspect_build' and set(fields)=={'run_id'}:command='inspect';payload={'run_directory':str(owned)}
                        elif name=='resume_build' and set(fields)=={'run_id','expected_revision','parameter_changes'}:
                            if latest['status']!='check_failed':raise ValueError('Model recovery requires an engineering check failure')
                            command='resume';payload={'run_directory':str(owned),'expected_revision':fields['expected_revision'],'parameter_changes':fields['parameter_changes']}
                        else:raise ValueError('Unknown tool or unexpected fields')
                    path=folder/('request-'+str(count)+'.json');path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
                    process=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/steering_cli.py'),command,str(path)],capture_output=True,text=True,encoding='utf-8')
                    if process.returncode:raise RuntimeError(process.stderr)
                    state=json.loads(process.stdout);owned=Path(state.pop('run_directory'));latest=state
                    result=model_state(state,owned)
                    transcript['commands'].append({'command':command,'request':payload,'result':result})
                    if args.keep_open and state['status']=='completed':
                        import win32com.client
                        final=next((state['outputs'][s['output']]['file'] for s in reversed(runtime.flow.ordered_steps(state['flow']))
                                    if state['outputs'][s['output']]['file'].lower().endswith('.catpart')),None)
                        if final:
                            app=win32com.client.GetActiveObject('CATIA.Application')
                            doc=app.Documents.Open(str(owned/final));doc.Activate();app.Visible=True
                            runtime.publications.prepare_display(doc)
                            viewer=app.ActiveWindow.ActiveViewer;view=viewer.Viewpoint3D
                            view.PutSightDirection((0.0,0.0,-1.0));view.PutUpDirection((0.0,1.0,0.0))
                            viewer.Viewpoint3D=view;viewer.Reframe();viewer.Update()
                            result['model_kept_open']=True
                messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result,ensure_ascii=False)})
                (folder/'transcript.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding='utf-8')
        raise RuntimeError('Model turn budget exhausted')
    finally:
        (folder/'transcript.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':raise SystemExit(main())
