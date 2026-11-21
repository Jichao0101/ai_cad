"""B00外部CATPart输入核对：原件只读，运行使用独立副本。"""
import hashlib,shutil,uuid
from pathlib import Path


def resolve_object(part,path):
    """逐层匹配名称且要求唯一；不采用FindObjectByName的首个同名结果。"""
    current=part
    allowed={'Bodies','Shapes','Sketches','HybridBodies','HybridShapes','AxisSystems','Parameters'}
    if not isinstance(path,list) or not path:raise ValueError('Object path must contain collection/name segments')
    for segment in path:
        if segment.get('collection') not in allowed or not isinstance(segment.get('name'),str):
            raise ValueError('Invalid object path segment')
        collection=getattr(current,segment['collection'])
        matches=[collection.Item(i) for i in range(1,collection.Count+1) if collection.Item(i).Name==segment['name']]
        if len(matches)!=1:raise ValueError('Expected unique object: '+segment['name']+'; found '+str(len(matches)))
        current=matches[0]
    return current


def load(folder,manifest):
    """返回已核对的阶段资产及缺项；清单未满足时不进入建模。"""
    import win32com.client
    records={};issues=[];candidates=[]
    for logical_id,spec in manifest.items():
        try:
            source=Path(spec['path'])
            if not source.is_absolute() or source.suffix.lower()!='.catpart':raise ValueError('Expected absolute CATPart path')
            if spec['unit']!='mm':raise ValueError('Explicit millimetre input required; unit conversion is not implemented')
            if spec['coordinate_system'] not in {'design_global','part_local'}:raise ValueError('Input must explicitly declare design_global or part_local coordinates')
            if not isinstance(spec['objects'],dict) or not spec['objects']:raise ValueError('Required object bindings are missing')
            expected=spec['sha256']
            if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
                raise ValueError('Expected lowercase SHA256 fingerprint')
            if not source.is_file():raise ValueError('Input file is missing: '+str(source))
            if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('Input file differs from declared SHA256')
            candidates.append((logical_id,spec,source))
        except (KeyError,ValueError,OSError,TypeError) as error:
            issues.append({'object_id':logical_id,'category':'input_manifest','message':str(error)})
    if issues:return {},issues
    if not candidates:return {},[]
    app=win32com.client.GetActiveObject('CATIA.Application')
    for logical_id,spec,source in candidates:
        copied=folder/('input-'+uuid.uuid4().hex+'.CATPart')
        doc=None
        try:
            shutil.copyfile(source,copied)
            if hashlib.sha256(copied.read_bytes()).hexdigest()!=spec['sha256']:raise ValueError('Source changed while copying')
            doc=app.Documents.Open(str(copied))
            for name,path in spec['objects'].items():
                try:resolve_object(doc.Part,path)
                except Exception as error:
                    issues.append({'object_id':logical_id,'binding':name,'category':'input_object','message':str(error)})
            records[logical_id]={'file':copied.name,'sha256':spec['sha256'],'measurements':{},'input_manifest':spec}
        except Exception as error:
            issues.append({'object_id':logical_id,'category':'input_open','message':str(error)})
        finally:
            if doc is not None:doc.Close()
    return ({} if issues else records),issues
