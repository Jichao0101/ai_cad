"""在唯一命名副本中比较SPA与指定密度的Inertia体积，逐阶段落盘进度。"""
import argparse,hashlib,json,math,shutil,uuid
from datetime import datetime
from pathlib import Path


def main():
    import win32com.client
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',type=Path)
    parser.add_argument('--expected-volume-mm3',type=float)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    source=args.file.resolve()
    if args.expected_volume_mm3 is not None and not math.isfinite(args.expected_volume_mm3):
        raise ValueError('Expected volume must be finite')
    root=Path(__file__).resolve().parents[1]
    output=(args.output or root/'runs'/datetime.now().strftime('steering-volume-%Y%m%d-%H%M%S-%f')).resolve()
    output.mkdir(parents=True,exist_ok=False)
    report={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'expected_volume_mm3':args.expected_volume_mm3,'fixture_only':True}
    def progress(stage):
        report['stage']=stage
        (output/'progress.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'stage':stage,'directory':str(output)}),flush=True)
    progress('copy')
    working=output/('VolumeProbe_'+uuid.uuid4().hex+'.CATPart')
    shutil.copyfile(source,working)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=None
    try:
        progress('open_document')
        doc=app.Documents.Open(str(working))
        progress('measure_spa_main_body')
        part=doc.Part
        report['body_count']=part.Bodies.Count
        spa=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody))
        report['spa_volume_mm3']=spa.Volume*1e9
        progress('obtain_product_inertia')
        inertia=doc.Product.GetTechnologicalObject('Inertia')
        progress('set_uniform_density')
        inertia.Density=1000.0
        progress('measure_product_inertia')
        report['density_kg_m3']=inertia.Density
        report['mass_kg']=inertia.Mass
        report['inertia_volume_mm3']=report['mass_kg']/1000.0*1e9
        report['interface_difference_mm3']=report['inertia_volume_mm3']-report['spa_volume_mm3']
        if args.expected_volume_mm3 is not None:
            report['spa_analytic_error_mm3']=report['spa_volume_mm3']-args.expected_volume_mm3
            report['inertia_analytic_error_mm3']=report['inertia_volume_mm3']-args.expected_volume_mm3
        report['source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==report['source_sha256']
        report['scope_note']='SPA measures MainBody; product Inertia may include other bodies. Compare equal scopes before interpreting differences.'
        progress('measured')
    except Exception as error:
        report['failed_stage']=report['stage'];report['error']=str(error)
        progress('execution_error')
        raise
    finally:
        if doc is not None:
            progress('close_working_copy_without_save')
            doc.Close()
    progress('completed')
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
