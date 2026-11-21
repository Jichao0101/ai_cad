"""安装自检：依赖及CATIA连接只读检查，不自动创建或关闭用户零件。"""
import hashlib,json,platform,sys
from pathlib import Path


def main():
    report={'python':platform.python_version(),'platform':platform.platform(),'package_root':str(Path(__file__).resolve().parents[1])}
    try:
        root=Path(report['package_root']);manifest=root/'package-manifest.json'
        if manifest.exists():
            files=json.loads(manifest.read_text(encoding='utf-8'))['files']
            changed=[name for name,expected in files.items()
                     if not (root/name).is_file() or hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected]
            report['package_files_checked']=len(files)
            if changed:
                report['changed_package_files']=changed
                raise ValueError('Package files missing or changed')
        import win32com.client
        from importlib.metadata import version
        report['pywin32']=version('pywin32')
        app=win32com.client.GetActiveObject('CATIA.Application')
        report.update(catia_client=app.FullName,open_documents=app.Documents.Count,status='ready_for_cad_test')
    except Exception as error:
        report.update(status='not_ready',error=str(error))
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return 0 if report['status']=='ready_for_cad_test' else 1


if __name__=='__main__':raise SystemExit(main())
