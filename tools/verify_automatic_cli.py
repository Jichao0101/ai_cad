"""Real CATIA automatic recovery and portable package acceptance."""
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'delivery/glovebox'

def main():
    folder=ROOT/'runs'/datetime.now().strftime('automatic-acceptance-%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    records=[];cli=PACKAGE/'cad_cli.py'
    policy={'radius_min_mm':5,'radius_max_mm':5.5,'minimum_volume_mm3':1300,'check_source':'automatic recovery regression; not DS'}
    def call(command,request,code=0):
        path=folder/f'request-{len(records):03d}.json';path.write_text(json.dumps(request),encoding='utf-8')
        proc=subprocess.run([sys.executable,'-X','utf8',str(cli),command,'--request',str(path),'--workspace',str(folder/'builds')],capture_output=True,text=True,encoding='utf-8',timeout=180,cwd=cli.parent)
        result=json.loads(proc.stdout)
        records.append({'command':command,'request':request,'result':result,'exit_code':proc.returncode})
        (folder/'commands.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        assert proc.returncode==code,result
        return result
    def req(state,changes):return {'run_id':state['run_id'],'expected_revision':state['revision'],'parameter_changes':changes}
    def measure(state):return state['check']['measurement']
    call('workflow',{})
    for bad in (True,0,6,float('nan')):call('start',{'policy':policy,'parameters':{'radius_mm':bad}},3)
    failed=call('start',{'policy':policy,'parameters':{'radius_mm':5}},2)
    assert failed['completed_steps']==['bottom','top','profile','pad']
    assert 1128<measure(failed)['volume_mm3']<1130
    for extra in ({'expected_revision':failed['revision']-1},{'policy':policy},{'before_step':'bottom'}):
        call('resume',{**req(failed,{'radius_mm':5.5}),**extra},3)
    for value in (5,6):call('resume',req(failed,{'radius_mm':value}),3)
    queried=call('inspect',{'run_id':failed['run_id']},2)
    assert queried['revision']==failed['revision']
    passed=call('resume',req(failed,{'radius_mm':5.5}))
    assert passed['status']=='passed' and passed['remaining_builds']==2
    assert passed['recovery']['before_step']=='profile'
    assert passed['recovery']['invalidated_steps']==['profile','pad']
    assert passed['recovery']['rerun_steps']==['profile','pad']
    call('resume',req(passed,{'radius_mm':5.4}),3)
    clean=call('start',{'policy':policy,'parameters':{}})
    assert clean['parameters']['radius_mm']['source'].startswith('default:')
    for key in ('volume_mm3','area_mm2','radius_mm','solid_features','sketches','limit_mode'):
        assert abs(measure(passed)[key]-measure(clean)[key])<0.001,key
    impossible=call('start',{'policy':{**policy,'minimum_volume_mm3':2000},'parameters':{'radius_mm':5}},2)
    impossible=call('resume',req(impossible,{'radius_mm':5.1}),2)
    call('resume',req(impossible,{'radius_mm':5}),3)
    for value in (5.2,5.3):impossible=call('resume',req(impossible,{'radius_mm':value}),2)
    assert impossible['remaining_builds']==0
    call('resume',req(impossible,{'radius_mm':5.4}),3)
    names=['cad_cli.py','automatic.py','executor.py','operations.py','pipeline.json','requirements.txt','README.md','skill/glovebox-design/SKILL.md']
    names += [p.relative_to(PACKAGE).as_posix() for p in sorted((PACKAGE/'assets').glob('*.json'))]
    archive=folder/'glovebox-delivery.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in names:z.write(PACKAGE/name,name)
    isolated=folder/'extracted-package'
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist())==set(names);z.extractall(isolated)
    cli=isolated/'cad_cli.py'
    portable=call('start',{'policy':policy,'parameters':{'radius_mm':5.5}})
    assert portable['status']=='passed'
    assert abs(measure(portable)['volume_mm3']-measure(clean)['volume_mm3'])<0.001
    summary={'passed':True,'commands':len(records),'process_ids':[r['result']['process_id'] for r in records],
        'checks':['automatic_full_run','parameter_provenance','automatic_rollback','clean_equivalence','stale_rejection','policy_immutable','no_manual_rollback','parameter_validation','duplicate_rejection','bounded_attempts','portable_extraction'],
        'recovery':passed['recovery'],'measurement':measure(passed),
        'package':str(archive),'package_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'source_hashes':{name:hashlib.sha256((PACKAGE/name).read_bytes()).hexdigest() for name in names}}
    (folder/'verification.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'evidence':str(folder),'commands':len(records),'package':str(archive)}),flush=True)

if __name__=='__main__':main()
