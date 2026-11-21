"""主Body原生刚体定位；输入两套明确的右手正交轴系。"""
import math
from . import datum


def validate_frame(frame):
    datum.vector(frame['origin_mm'])
    axes=[datum.vector(frame[name]) for name in ['x','y','z']]
    if any(abs(datum.dot(axis,axis)-1)>1e-8 for axis in axes):
        raise ValueError('Placement axes must be unit vectors')
    if any(abs(datum.dot(axes[i],axes[j]))>1e-8 for i,j in [(0,1),(0,2),(1,2)]):
        raise ValueError('Placement axes must be orthogonal')
    x,y,z=axes;cross=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
    if datum.dot(cross,z)<1-1e-8:raise ValueError('Placement frame must be right handed')


def clocked_frame(frame,degrees):
    """绕目标轴系自身Z轴右手旋转X/Y，保持原点及Z轴；不改写输入基准。"""
    validate_frame(frame)
    if isinstance(degrees,bool) or not isinstance(degrees,(int,float)) or not math.isfinite(degrees):
        raise ValueError('Clocking angle must be finite degrees')
    angle=math.radians(degrees);c=math.cos(angle);s=math.sin(angle)
    return {'origin_mm':list(frame['origin_mm']),'z':list(frame['z']),
            'x':[c*x+s*y for x,y in zip(frame['x'],frame['y'])],
            'y':[-s*x+c*y for x,y in zip(frame['x'],frame['y'])]}


def _clocking_axis(doc,frame,degrees,prefix):
    """用单个原生角度及公式驱动目标方向线，保持目标XYZ语义。"""
    part=doc.Part;factory=part.HybridShapeFactory
    support=part.HybridBodies.Add();support.Name=prefix+'_ClockingSupport'
    point=factory.AddNewPointCoord(*frame['origin_mm']);support.AppendHybridShape(point)
    lines=[]
    for key in ('x','y','z'):
        line=factory.AddNewLinePtDir(part.CreateReferenceFromObject(point),factory.AddNewDirectionByCoord(*frame[key]),0,10,False)
        line.Name=prefix+'_'+key+'_BaseDirection';support.AppendHybridShape(line);lines.append(line)
    part.Update()
    angle=part.Parameters.CreateDimension(prefix+'_ClockingAngle','ANGLE',0.)
    angle.ValuateFromString(format(degrees,'.17g')+'deg')
    rotated=[]
    for index,line in enumerate(lines[:2]):
        feature=factory.AddNewRotate(part.CreateReferenceFromObject(line),part.CreateReferenceFromObject(lines[2]),float(degrees))
        feature.Name=prefix+'_ClockedDirection_'+str(index);support.AppendHybridShape(feature);part.UpdateObject(feature)
        part.Relations.CreateFormula(prefix+'_ClockingFormula_'+str(index),'',feature.Angle,part.Parameters.GetNameToUseInRelation(angle))
        rotated.append(feature)
    axis=part.AxisSystems.Add();axis.Name=prefix+'_TargetAxis'
    axis.OriginType=1;axis.PutOrigin(tuple(float(v) for v in frame['origin_mm']))
    axis.XAxisType=axis.YAxisType=axis.ZAxisType=0
    axis.XAxisDirection=part.CreateReferenceFromObject(rotated[0]);axis.YAxisDirection=part.CreateReferenceFromObject(rotated[1])
    axis.ZAxisDirection=part.CreateReferenceFromObject(lines[2]);part.Update()
    return axis,angle.Name


def create(doc,source_frame,target_frame,clocking_deg=None):
    import pythoncom,win32com.client
    validate_frame(source_frame);nominal_frame=target_frame
    target_frame=clocked_frame(target_frame,0 if clocking_deg is None else clocking_deg)
    part=doc.Part;body=part.MainBody;spa=doc.GetWorkbench('SPAWorkbench')
    before=spa.GetMeasurable(part.CreateReferenceFromObject(body))
    volume_before=before.Volume*1e9
    if not math.isfinite(volume_before) or volume_before<=0:raise ValueError('Placement requires a measurable solid')
    coordinates=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
    before._oleobj_.Invoke(before._oleobj_.GetIDsOfNames('GetCOG'),0,1,0,coordinates)
    original_cog=datum.vector(list(coordinates.value))
    local=[datum.dot([a-b for a,b in zip(original_cog,source_frame['origin_mm'])],source_frame[name]) for name in ['x','y','z']]
    expected=[target_frame['origin_mm'][i]+sum(local[j]*target_frame[name][i] for j,name in enumerate(['x','y','z'])) for i in range(3)]
    prefix='B00_Placement_'+str(body.Shapes.Count+1)
    source=datum.create(doc,source_frame);source.Name=prefix+'_SourceAxis'
    clocking={}
    if clocking_deg is None:
        target=datum.create(doc,target_frame);target.Name=prefix+'_TargetAxis'
    else:
        target,parameter_name=_clocking_axis(doc,nominal_frame,clocking_deg,prefix)
        clocking={'clocking_parameter':parameter_name}
    part.InWorkObject=body;count=body.Shapes.Count
    part.ShapeFactory.AddNewAxisToAxis2(part.CreateReferenceFromObject(source),part.CreateReferenceFromObject(target))
    part.Update()
    if body.Shapes.Count!=count+1:raise RuntimeError('Expected one native placement feature')
    feature=body.Shapes.Item(count+1);feature.Name=prefix
    after=spa.GetMeasurable(part.CreateReferenceFromObject(body))
    volume_after=after.Volume*1e9
    after._oleobj_.Invoke(after._oleobj_.GetIDsOfNames('GetCOG'),0,1,0,coordinates)
    actual=datum.vector(list(coordinates.value))
    if not math.isfinite(volume_after) or volume_after<=0:raise ValueError('Invalid placed solid volume')
    if abs(volume_after-volume_before)>max(1e-6,abs(volume_before)*1e-9) or math.dist(actual,expected)>1e-6:
        raise ValueError('Native placement differs from the declared rigid transform')
    return {'volume_mm3':volume_after,'source_volume_mm3':volume_before,'cog_mm':actual,'clocking_deg':0 if clocking_deg is None else clocking_deg,**clocking,
            'expected_cog_mm':expected,'source_cog_mm':original_cog,
            'feature_name':prefix,'source_axis_name':source.Name,'target_axis_name':target.Name}
