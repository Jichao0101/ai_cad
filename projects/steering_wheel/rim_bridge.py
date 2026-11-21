"""B45显式端部截面的原生Loft；端部识别和业务配对由上游提供。"""
import math
from . import sections
from .datum import vector,dot


def from_endpoints(basis,records,ends):
    """将显式选定的上游全局圆截面转为桥接使用的基准局部坐标。"""
    if set(records)!={'first','second'} or set(ends)!={'first','second'}:
        raise ValueError('Endpoint bridge requires first and second inputs and selectors')
    specs=[]
    for role in ('first','second'):
        data=records[role]['measurements'].get('end_sections')
        if not data or data['coordinate_system']!='design_global' or data['section_kind']!='circle':
            raise ValueError('Source has no supported global circular endpoint sections: '+role)
        if ends[role] not in ('start','end'):raise ValueError('Endpoint selector must be start or end')
        spec=data['sections'][ends[role]]
        origin=[a-b for a,b in zip(vector(spec['center_mm']),basis['origin_mm'])]
        local={'center_mm':[dot(origin,basis[key]) for key in ('x','y','z')],'radius_mm':spec['radius_mm']}
        for axis in ('x','y'):local[axis]=[dot(vector(spec[axis]),basis[key]) for key in ('x','y','z')]
        specs.append(local)
    return {'section_kind':'circle','sections':specs}


def create(doc,basis,parameters):
    specs=parameters['sections'];kind=parameters['section_kind']
    if kind not in {'circle','rectangle'} or len(specs)!=2:
        raise ValueError('Bridge requires two sections of one explicit circle/rectangle kind')
    frames=[]
    for spec in specs:
        center=vector(spec['center_mm']);x=vector(spec['x']);y=vector(spec['y'])
        if abs(dot(x,x)-1)>1e-8 or abs(dot(y,y)-1)>1e-8 or abs(dot(x,y))>1e-8:
            raise ValueError('Bridge section axes must be orthonormal')
        dimensions=[spec['radius_mm']] if kind=='circle' else [spec['width_mm'],spec['thickness_mm']]
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in dimensions):
            raise ValueError('Bridge section dimensions must be positive finite millimetres')
        frames.append((center,x,y))
    chord=[b-a for a,b in zip(frames[0][0],frames[1][0])]
    length=math.sqrt(dot(chord,chord))
    if length<1e-6:raise ValueError('Bridge section centers must be distinct')
    for _,x,y in frames:
        normal=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
        if dot(normal,chord)/length<=1e-8:
            raise ValueError('Both section normals must face the declared bridge travel direction')
    def rotate(v):
        return [sum(v[j]*basis[key][i] for j,key in enumerate(('x','y','z'))) for i in range(3)]
    part=doc.Part;body=part.MainBody;body.Name='B45_RimBridge'
    support=part.HybridBodies.Add();support.Name='B45_BridgeGuides'
    factory=part.HybridShapeFactory;profiles=[];corners=[]
    for index,(spec,(center,x,y)) in enumerate(zip(specs,frames)):
        origin=[a+b for a,b in zip(basis['origin_mm'],rotate(center))]
        frame=origin+rotate(x)+rotate(y);name='B45_EndSection_'+str(index+1)
        if kind=='rectangle':
            profile,points=sections.rectangle(doc,body,name,frame,spec['width_mm'],spec['thickness_mm'])
        else:
            profile=sections.circle(doc,body,name,frame,spec['radius_mm'])
            point=factory.AddNewPointCoord(*[a+spec['radius_mm']*b for a,b in zip(origin,frame[3:6])])
            point.Name=name+'_ClosingPoint';support.AppendHybridShape(point);points=[point]
        profiles.append(profile);corners.append(points)
    part.Update();guides=[]
    for index,(first,last) in enumerate(zip(*corners)):
        guide=factory.AddNewLinePtPt(part.CreateReferenceFromObject(first),part.CreateReferenceFromObject(last))
        guide.Name='B45_EdgeGuide_'+str(index+1);support.AppendHybridShape(guide);guides.append(guide)
    part.Update()
    feature=sections.bridge(doc,body,profiles,[points[0] for points in corners],'B45_Bridge',guides)
    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(feature))
    return {'volume_mm3':measured.Volume*1e9,'area_mm2':measured.Area*1e6,
            'section_count':2,'center_distance_mm':length,'section_kind':kind,'guide_count':len(guides)}
