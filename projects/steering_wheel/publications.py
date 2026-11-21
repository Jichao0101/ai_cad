"""B90具名几何发布；对象定位沿用唯一名称路径，不覆盖已有发布项。"""
from .inputs import resolve_object


def prepare_display(doc):
    """只整理发布副本的显隐：显示主实体，保留并隐藏辅助对象。"""
    part=doc.Part;main=part.MainBody
    hidden=[]
    for collection in [part.AxisSystems,part.HybridBodies,main.HybridBodies,main.Sketches]:
        if collection is not None:
            hidden.extend(collection.Item(i) for i in range(1,collection.Count+1))
    hidden.extend([part.OriginElements.PlaneXY,part.OriginElements.PlaneYZ,part.OriginElements.PlaneZX])
    for i in range(1,part.Bodies.Count+1):
        body=part.Bodies.Item(i)
        if body.Name!=main.Name:hidden.append(body)
    selection=doc.Selection
    try:
        selection.Clear()
        for obj in hidden:selection.Add(obj)
        selection.VisProperties.SetShow(1)
        if selection.VisProperties.GetShow()!=(0,1):
            raise ValueError('Auxiliary geometry visibility could not be set uniformly')
        selection.Clear();selection.Add(main);selection.VisProperties.SetShow(0)
        if selection.VisProperties.GetShow()!=(0,0):
            raise ValueError('Main body is not shown')
    finally:selection.Clear()
    doc.Activate()
    viewer=doc.Application.ActiveWindow.ActiveViewer
    viewer.Reframe();viewer.Update()
    return {'hidden_support_count':len(hidden),'main_body_shown':True}


def create(doc,bindings):
    if not isinstance(bindings,dict) or not bindings:
        raise ValueError('Publication bindings must be a nonempty mapping')
    product=doc.Product;publications=product.Publications
    existing={publications.Item(i).Name for i in range(1,publications.Count+1)}
    targets=[]
    for name,path in bindings.items():
        if not isinstance(name,str) or not name.strip():raise ValueError('Publication name is required')
        if name in existing:raise ValueError('Publication already exists: '+name)
        obj=resolve_object(doc.Part,path)
        names=[segment['name'] for segment in path]
        if any('/' in value or '!' in value for value in [product.PartNumber,*names]):
            raise ValueError('Object names contain publication reference separators')
        reference=product.CreateReferenceFromName(product.PartNumber+'/!'+'/'.join(names))
        targets.append((name,path,obj,reference))
    result=[]
    for name,path,obj,reference in targets:
        publications.Add(name);publications.SetDirect(name,reference)
        value=publications.Item(name).Valuation
        selection=doc.Selection;selection.Clear();selection.Add(value)
        try:
            if selection.Count2!=1 or selection.Item2(1).Value.Name!=obj.Name:
                raise ValueError('Publication does not resolve to the requested object: '+name)
        finally:selection.Clear()
        result.append({'name':name,'object_path':path,'reference':value.DisplayName})
    return {'published_count':len(result),'publications':result}
