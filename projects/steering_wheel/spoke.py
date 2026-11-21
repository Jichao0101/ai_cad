"""按已给定定位截面构建辐条连接体；包络选型和挖槽由后续工序处理。"""
from . import sections
from .datum import vector,dot


def create(doc,basis,parameters):
    specifications=parameters['sections']
    if len(specifications)!=3:
        raise ValueError('Spoke requires three explicitly positioned sections')
    thickness=parameters['thickness_mm']
    bends=parameters.get('guide_bends_mm')
    if bends is not None:
        if len(bends)!=2:raise ValueError('Expected one guide bend vector per connection')
        bends=[vector(value) for value in bends]
    part=doc.Part;body=part.MainBody;body.Name='B60_Spoke'
    profiles=[];corners=[];normals=[];guide_length=0.0
    def rotate(v):
        return [sum(v[j]*basis[key][i] for j,key in enumerate(['x','y','z'])) for i in range(3)]
    for index,spec in enumerate(specifications):
        origin=[a+b for a,b in zip(basis['origin_mm'],rotate(vector(spec['center_mm'])))]
        frame=origin+rotate(vector(spec['x']))+rotate(vector(spec['y']))
        x,y=frame[3:6],frame[6:9]
        normals.append([x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]])
        profile,corner=sections.rectangle(doc,body,'B50_Section_'+str(index+1),frame,spec['width_mm'],thickness)
        profiles.append(profile);corners.append(corner)
    for index in range(2):
        support=part.HybridBodies.Add();support.Name='B60_Guides_'+str(index+4)
        guides=[]
        factory=part.HybridShapeFactory
        for edge_index,(start,end) in enumerate(zip(corners[index],corners[index+1])):
            start_ref=part.CreateReferenceFromObject(start);end_ref=part.CreateReferenceFromObject(end)
            if bends is None:
                guide=factory.AddNewLinePtPt(start_ref,end_ref)
            else:
                midpoint=factory.AddNewPointBetween(start_ref,end_ref,.5,1)
                support.AppendHybridShape(midpoint)
                control=factory.AddNewPointCoord(*rotate(bends[index]))
                control.PtRef=part.CreateReferenceFromObject(midpoint)
                control.Name='B60_Bend_'+str(index+4)+'_'+str(edge_index)
                support.AppendHybridShape(control);part.Update()
                guide=factory.AddNewSpline();guide.SetClosing(0)
                chord=rotate([b-a for a,b in zip(specifications[index]['center_mm'],specifications[index+1]['center_mm'])])
                directions=[]
                for normal in normals[index:index+2]:
                    sense=dot(normal,chord)
                    if abs(sense)<1e-8:raise ValueError('Section normal does not determine guide travel direction')
                    directions.append(factory.AddNewDirectionByCoord(*[v if sense>0 else -v for v in normal]))
                guide.AddPointWithConstraintExplicit(start_ref,directions[0],1.0,1,None,0.0)
                guide.AddPoint(part.CreateReferenceFromObject(control))
                guide.AddPointWithConstraintExplicit(end_ref,directions[1],1.0,1,None,0.0)
            guide.Name='B60_Guide_'+str(index+4)+'_'+str(edge_index)
            support.AppendHybridShape(guide);guides.append(guide)
        part.Update()
        spa=doc.GetWorkbench('SPAWorkbench')
        guide_length+=sum(spa.GetMeasurable(part.CreateReferenceFromObject(g)).Length for g in guides)
        sections.bridge(doc,body,profiles[index:index+2],[points[0] for points in corners[index:index+2]],
                        'B60_Connection_'+str(index+4),guides=guides)
    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(body))
    return {'volume_mm3':measured.Volume*1e9,'area_mm2':measured.Area*1e6,
            'thickness_mm':thickness,'half_thickness_mm':thickness/2,'section_count':3,'guide_length_mm':guide_length}
