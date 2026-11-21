"""只读探针：由实际平面和直边重构矩形端面；不自动确定桥接角点对应。"""
import argparse,json,math,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime
from projects.steering_wheel.datum import dot,unit


def main():
    import pythoncom,win32com.client
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('part',type=Path)
    parser.add_argument('--width',type=float,required=True)
    parser.add_argument('--thickness',type=float,required=True)
    args=parser.parse_args()
    if any(not math.isfinite(v) or v<=0 for v in [args.width,args.thickness]):
        parser.error('Dimensions must be positive finite millimetres')
    source=args.part.resolve();before=runtime.digest(source)
    output=Path(__file__).resolve().parents[1]/'runs'/datetime.now().strftime('rectangle-endpoints-probe-%Y%m%d-%H%M%S-%f')
    output.mkdir()
    app=win32com.client.GetActiveObject('CATIA.Application')
    # 只操作自有副本，避免关闭或改变用户已打开的源文档。
    import shutil
    copy=output/'Probe.CATPart';shutil.copy2(source,copy)
    doc=app.Documents.Open(str(copy))
    try:
        spa=doc.GetWorkbench('SPAWorkbench');selection=doc.Selection
        def coordinates(measured,method,count):
            values=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*count)
            measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames(method),0,1,0,values)
            return list(values.value)
        geometry={}
        for kind in ('CGMFace','CGMEdge'):
            selection.Clear();selection.Add(doc.Part.MainBody)
            selection.Search('Topology.'+kind+',sel')
            geometry[kind]=[selection.Item2(i).Reference for i in range(1,selection.Count2+1)]
        selection.Clear();edges=[];raw_count=0
        for ref in geometry['CGMEdge']:
            measured=spa.GetMeasurable(ref)
            if measured.GeometryName!=10:continue
            values=coordinates(measured,'GetPointsOnCurve',9)
            ends=[values[:3],values[6:]];raw_count+=1
            if any(min(max(math.dist(a,b) for a,b in zip(ends,order)) for order in [existing,existing[::-1]])<=1e-6 for existing in edges):continue
            if abs(math.dist(*ends)-measured.Length)>1e-6:raise ValueError('Line endpoint length mismatch')
            edges.append(ends)
        results=[]
        for ref in geometry['CGMFace']:
            measured=spa.GetMeasurable(ref)
            if measured.GeometryName!=7 or abs(measured.Area*1e6-args.width*args.thickness)>1e-6:continue
            center=coordinates(measured,'GetCOG',3);plane=coordinates(measured,'GetPlane',9)
            u,v=plane[3:6],plane[6:]
            normal=unit([u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]])
            boundary=[edge for edge in edges if all(abs(dot([a-b for a,b in zip(point,center)],normal))<=1e-6 for point in edge)]
            if len(boundary)!=4:continue
            widths=[edge for edge in boundary if abs(math.dist(*edge)-args.width)<=1e-6]
            heights=[edge for edge in boundary if abs(math.dist(*edge)-args.thickness)<=1e-6]
            square=abs(args.width-args.thickness)<=1e-6
            if len(widths)!=(4 if square else 2) or len(heights)!=(4 if square else 2):continue
            x=unit([b-a for a,b in zip(*widths[0])])
            y=unit([normal[1]*x[2]-normal[2]*x[1],normal[2]*x[0]-normal[0]*x[2],normal[0]*x[1]-normal[1]*x[0]])
            actual=[]
            for edge in boundary:
                for point in edge:
                    if not any(math.dist(point,other)<=1e-6 for other in actual):actual.append(point)
            if len(actual)!=4:continue
            predicted=[[center[i]+sx*args.width/2*x[i]+sy*args.thickness/2*y[i] for i in range(3)] for sx,sy in [(-1,-1),(1,-1),(1,1),(-1,1)]]
            error=max(min(math.dist(point,other) for other in actual) for point in predicted)
            if error>1e-6:continue
            results.append({'center_mm':center,'x_unsigned':x,'y_unsigned':y,'plane_normal_unsigned':normal,
                'actual_corners_mm':actual,'reconstructed_corners_mm':predicted,'maximum_corner_error_mm':error,
                'width_thickness_ambiguous':square,'axis_sign_and_bridge_pairing_unresolved':True})
        report={'source_sha256':before,'width_mm':args.width,'thickness_mm':args.thickness,
            'raw_straight_edge_count':raw_count,'unique_straight_edge_count':len(edges),'candidate_count':len(results),
            'rectangular_faces':results,'not_bridge_ready':True,'ds_status':'not_evaluated'}
    finally:doc.Close()
    assert runtime.digest(source)==before
    report['source_unchanged']=True
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(output/'result.json'),**report},ensure_ascii=False))


if __name__=='__main__':main()
