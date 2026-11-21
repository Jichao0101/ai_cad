"""跨进程验证B10/B20检查失败、单参数继续及基准资产保留。"""
import json,subprocess,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'runs'/datetime.now().strftime('steering-runtime-test-%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    def call(command,request):
        path=folder/(command+'-'+str(len(list(folder.glob('*.json'))))+'.json')
        path.write_text(json.dumps(request),encoding='utf-8')
        process=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/steering_cli.py'),command,str(path)],capture_output=True,text=True,encoding='utf-8',timeout=90)
        if process.returncode:raise RuntimeError(process.stderr)
        return json.loads(process.stdout)
    request={'flow':str(ROOT/'tests/fixtures/steering_baffle_flow.json'),'runs_root':str(folder),'parameters':{'thickness_mm':8.4}}
    initial=call('start',request)
    assert initial['status']=='check_failed',initial
    updated=call('resume',{'run_directory':initial['run_directory'],'expected_revision':initial['revision'],'parameter_changes':{'thickness_mm':10}})
    assert updated['status']=='completed',updated
    assert updated['outputs']['basis']==initial['outputs']['basis']
    assert updated['recovery']['retained']==['datum']
    assert updated['recovery']['execute']==['baffle']
    request['parameters']={'thickness_mm':10}
    clean=call('start',request)
    assert clean['status']=='completed'
    assert updated['outputs']['baffle_part']['measurements']==clean['outputs']['baffle_part']['measurements']
    inspected=call('inspect',{'run_directory':updated['run_directory']})
    assert inspected['revision']==updated['revision']
    import win32com.client
    app=win32com.client.GetActiveObject('CATIA.Application')
    path=Path(updated['run_directory'])/updated['outputs']['baffle_part']['file']
    doc=app.Documents.Open(str(path));doc.Activate();app.Visible=True;app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'passed':True,'initial':initial,'updated':updated,'clean':clean}
    (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'report':str(folder/'result.json'),'retained':updated['recovery']['retained'],'measurements':updated['outputs']['baffle_part']['measurements']}),flush=True)


if __name__=='__main__':main()
