"""B10基准求解；输入为上游提取的轴、平面和特征点，单位mm。"""
import math


def vector(value):
    if len(value) != 3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in value):
        raise ValueError('Expected three finite coordinates')
    return list(value)


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def unit(value):
    value=vector(value)
    length=math.sqrt(dot(value,value))
    if length<1e-12:
        raise ValueError('Zero direction')
    return [v/length for v in value]


def intersect(point,direction,plane_point,normal):
    denominator=dot(direction,normal)
    if abs(denominator)<1e-10:
        raise ValueError('Line and plane have no unique intersection')
    distance=dot([b-a for a,b in zip(point,plane_point)],normal)/denominator
    return [a+distance*b for a,b in zip(point,direction)]


def projection_seed(inputs):
    """显式选择原点规则；不将轴自动修正到不相容的对称面上。"""
    z=unit(inputs['column_direction'])
    y=unit(inputs['symmetry_normal'])
    plane_point=vector(inputs['symmetry_point'])
    axis_point=vector(inputs['column_point'])
    if abs(dot(y,z))>1e-8 or abs(dot([a-b for a,b in zip(axis_point,plane_point)],y))>1e-6:
        raise ValueError('Column axis must lie in symmetry plane')
    if inputs['origin_rule']=='sor_3_9':
        a=vector(inputs['outer_3']);b=vector(inputs['outer_9'])
        seed=intersect(a,unit([v-u for u,v in zip(a,b)]),plane_point,y)
    elif inputs['origin_rule']=='flow_y_extremum':
        seed=vector(inputs['y_negative_extremum'])
    else:
        raise ValueError('Choose sor_3_9 or flow_y_extremum explicitly')
    return seed,y,z


def solve(inputs,projected_origin=None):
    seed,y,z=projection_seed(inputs)
    if projected_origin is None:
        origin=intersect(seed,z,vector(inputs['bottom_point']),unit(inputs['bottom_normal']))
    else:
        origin=vector(projected_origin)
        delta=[a-b for a,b in zip(origin,seed)];along=dot(delta,z)
        if math.sqrt(sum((v-along*d)**2 for v,d in zip(delta,z)))>1e-6:
            raise ValueError('Projected origin does not lie on the column-direction line')
    x=[y[1]*z[2]-y[2]*z[1],y[2]*z[0]-y[0]*z[2],y[0]*z[1]-y[1]*z[0]]
    return {'origin_rule':inputs['origin_rule'],'origin_mm':origin,'x':x,'y':y,'z':z,
            'sketch_frame':origin+x+y}


def create(doc, frame):
    """复用历史代码已使用的原生轴系接口，方向由显式输入控制。"""
    axis=doc.Part.AxisSystems.Add()
    axis.Name='B10_DesignAxis'
    axis.OriginType=1
    axis.PutOrigin(tuple(float(v) for v in frame['origin_mm']))
    axis.XAxisType=axis.YAxisType=axis.ZAxisType=1
    axis.PutXAxis(tuple(float(v) for v in frame['x']))
    axis.PutYAxis(tuple(float(v) for v in frame['y']))
    axis.PutZAxis(tuple(float(v) for v in frame['z']))
    doc.Part.Update()
    return axis
