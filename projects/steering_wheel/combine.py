"""复制阶段原生Body及支撑，执行布尔添加或按stock/tool顺序减料。"""


def create(app, target, assets, mode='union'):
    """assets为有序的(role, CATPart路径)；调用方负责最终保存和关闭。"""
    if mode not in {'union','subtract'}:
        raise ValueError('Unsupported Boolean mode: '+mode)
    if mode=='subtract' and [role for role,_ in assets]!=['stock','tool']:
        raise ValueError('Subtract requires ordered stock and tool assets')
    if len(assets)<2:
        raise ValueError('Combine requires at least two stage assets')
    part=target.Part
    part.MainBody.Name='B90_Skeleton'
    parameter_names={}
    for role,path in assets:
        source=app.Documents.Open(str(path))
        try:
            selection=source.Selection
            selection.Clear()
            source_parameters=source.Part.Parameters.RootParameterSet.DirectParameters
            names=[source_parameters.Item(i).Name.rsplit('\\',1)[-1] for i in range(1,source_parameters.Count+1)]
            for index in range(1,source_parameters.Count+1):selection.Add(source_parameters.Item(index))
            for index in range(1,source.Part.AxisSystems.Count+1):
                selection.Add(source.Part.AxisSystems.Item(index))
            for index in range(1,source.Part.HybridBodies.Count+1):
                selection.Add(source.Part.HybridBodies.Item(index))
            selection.Add(source.Part.MainBody)
            selection.Copy()
            target.Activate()
            before=part.Bodies.Count
            before_axes=part.AxisSystems.Count
            before_parameters=part.Parameters.RootParameterSet.DirectParameters.Count
            dest=target.Selection
            dest.Clear();dest.Add(part);dest.PasteSpecial('CATPrtCont');dest.Clear()
            for index in range(before_axes+1,part.AxisSystems.Count+1):
                axis=part.AxisSystems.Item(index)
                axis.Name='Stage_'+role+'_'+axis.Name
            copied_parameters=part.Parameters.RootParameterSet.DirectParameters
            if copied_parameters.Count-before_parameters!=len(names):
                raise RuntimeError('Copied root parameter count differs from source: '+role)
            parameter_names[role]=[]
            for index,name in enumerate(names,before_parameters+1):
                parameter=copied_parameters.Item(index);parameter.Rename('Stage_'+role+'_'+name)
                parameter_names[role].append(parameter.Name)
            part.Update()
            if part.Bodies.Count!=before+1:
                raise RuntimeError('Expected one copied native Body: '+role)
            body=part.Bodies.Item(part.Bodies.Count)
            body.Name='Stage_'+role
        finally:
            source.Close()
        part.InWorkObject=part.MainBody
        if mode=='subtract' and role=='tool':
            stock_volume=target.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
            feature=part.ShapeFactory.AddNewRemove(body)
            feature.Name='Subtract_tool'
        else:
            feature=part.ShapeFactory.AddNewAdd(body)
            feature.Name='Combine_'+role
        part.Update()
    measured=target.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody))
    result={'volume_mm3':measured.Volume*1e9,'area_mm2':measured.Area*1e6,'stage_count':len(assets),'copied_parameters':parameter_names}
    if mode=='subtract':
        result.update(stock_volume_mm3=stock_volume,removed_volume_mm3=stock_volume-result['volume_mm3'])
    return result
