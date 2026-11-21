"""用相交、贴面和分离实体探测原生多域分解；不将未证实的接口当作连通检查。"""
import json,shutil,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-connectivity-probe-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');reports={}
    for label,offset,expected in [('overlap',5,1),('face_contact',10,1),('separated',20,2)]:
        definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
        definition['parameters']['thickness_mm']['default']=10
        definition['steps'][1]['parameters']['outline']=[[0,0],[10,0],[10,10],[0,10]]
        definition['steps'][1].pop('check')
        definition['steps'].extend([
            {'id':'second','operation':'baffle','inputs':{'basis':'basis'},'output':'second_part',
             'parameters':{'outline':[[offset,0],[offset+10,0],[offset+10,10],[offset,10]],'thickness_mm':10}},
            {'id':'union','operation':'combine','inputs':{'first':'baffle_part','second':'second_part'},
             'output':'union_part','parameters':{}}])
        folder,state=runtime.start(definition,{},output)
        assert state['status']=='completed',state.get('error')
        source=folder/state['outputs']['union_part']['file'];copied=output/(label+'.CATPart');shutil.copyfile(source,copied)
        report={'expected_domains':expected,'run_directory':str(folder),'source_sha256':runtime.digest(source)}
        doc=app.Documents.Open(str(copied))
        try:
            part=doc.Part;scope=part.MainBody.Shapes.Item(part.MainBody.Shapes.Count)
            print(label+' AddNewDatums',flush=True)
            try:
                domains=part.HybridShapeFactory.AddNewDatums(part.CreateReferenceFromObject(scope))
                if domains is None:raise ValueError('AddNewDatums returned no domain data; connectivity is unknown')
                report['returned_count']=len(domains)
                support=part.HybridBodies.Add();support.Name='ConnectivityProbe'
                report['volumes_mm3']=[]
                for domain in domains:
                    support.AppendHybridShape(domain)
                    part.UpdateObject(domain)
                    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(domain))
                    report['volumes_mm3'].append(measured.Volume*1e9)
                report['matches_expected']=len(domains)==expected
            except Exception as error:
                report.update(error=str(error),matches_expected=False)
            print(label+' volume datum then AddNewDatums',flush=True)
            volume_probe={}
            try:
                support=part.HybridBodies.Add();support.Name='VolumeDomainProbe'
                volume=part.HybridShapeFactory.AddNewVolumeDatum(part.CreateReferenceFromObject(scope))
                support.AppendHybridShape(volume);part.UpdateObject(volume)
                domains=part.HybridShapeFactory.AddNewDatums(part.CreateReferenceFromObject(volume))
                if domains is None:raise ValueError('AddNewDatums returned no domain data; connectivity is unknown')
                volume_probe['returned_count']=len(domains);volume_probe['volumes_mm3']=[]
                for domain in domains:
                    support.AppendHybridShape(domain);part.UpdateObject(domain)
                    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(domain))
                    volume_probe['volumes_mm3'].append(measured.Volume*1e9)
                volume_probe['matches_expected']=len(domains)==expected
            except Exception as error:
                volume_probe.update(error=str(error),matches_expected=False)
            report['volume_datum_probe']=volume_probe
        finally:doc.Close()
        report['source_unchanged']=runtime.digest(source)==report['source_sha256'];reports[label]=report
        (output/'result.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
        print(json.dumps({label:report}),flush=True)
    print(str(output/'result.json'),flush=True)


if __name__=='__main__':main()
