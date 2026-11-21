"""按白名单生成独立开发包；不收录Agent、密钥、日志和业务原始资产。"""
import argparse,hashlib,json,shutil,zipfile
from datetime import datetime
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--zip',action='store_true',help='Also create a ZIP containing only manifest-listed files')
    args=parser.parse_args()
    target=(args.output or root/'delivery'/datetime.now().strftime('steering-wheel-dev-%Y%m%d-%H%M%S')).resolve()
    if target==root or root.is_relative_to(target):raise ValueError('Output must not contain repository root')
    target.mkdir(parents=True,exist_ok=False)
    selected=list((root/'projects/steering_wheel').glob('*.py'))
    selected+=list((root/'projects/steering_wheel/skill').rglob('SKILL.md'))
    selected+=list((root/'tools').glob('verify_steering_*.py'))
    selected+=list((root/'tools').glob('investigate_steering_*.py'))
    selected+=[root/'tools/steering_cli.py',root/'tools/check_steering_install.py',root/'requirements.txt']
    selected+=[root/'projects/steering_wheel/README.md',root/'projects/steering_wheel/STATUS.md',root/'projects/steering_wheel/IMPLEMENTATION.md']
    selected+=list((root/'tests').glob('test_steering_*.py'))
    selected+=list((root/'tests/fixtures').glob('steering_*.json'))
    for source in selected:
        destination=target/source.relative_to(root);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
    shutil.copyfile(root/'projects/steering_wheel/PACKAGE_README.md',target/'README.md')
    commands={
        'install.bat':['python -m venv .venv','if errorlevel 1 exit /b 1',r'".venv\Scripts\python.exe" -m pip install -r requirements.txt'],
        'check.bat':[r'".venv\Scripts\python.exe" -X utf8 tools\check_steering_install.py'],
        'verify.bat':[r'".venv\Scripts\python.exe" -X utf8 tools\verify_steering_runtime.py']}
    for name,lines in commands.items():
        text='\r\n'.join(['@echo off','pushd "%~dp0"',*lines,'set "RUN_EXIT=%ERRORLEVEL%"','popd','exit /b %RUN_EXIT%',''])
        (target/name).write_bytes(text.encode('ascii'))
    (target/'examples').mkdir()
    (target/'examples/start-baffle.json').write_text(json.dumps({'flow':'tests/fixtures/steering_baffle_flow.json','runs_root':'runs','parameters':{'thickness_mm':8.4}},indent=2),encoding='utf-8')
    files={str(path.relative_to(target)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
           for path in sorted(target.rglob('*')) if path.is_file()}
    manifest={'release_status':'development_partial','fixture_only':True,'files':files,
              'known_gaps':['CAS workflow and real sample validation','HUB and attachment libraries','CAE material addition',
                            'Full business DS rules','Loft and spline strict analytic volume discrepancy','R34/V6/VDI and formal local host acceptance']}
    (target/'package-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=None
    if args.zip:
        archive=target.with_name(target.name+'.zip')
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in [*files,'package-manifest.json']:bundle.write(target/name,name)
    print(json.dumps({'package':str(target),'files':len(files),'status':manifest['release_status'],'zip':str(archive) if archive else None}),flush=True)


if __name__=='__main__':main()
