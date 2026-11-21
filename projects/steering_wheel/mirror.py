"""在单个阶段工作副本中镜像主Body，不访问其他阶段资产。"""
from .datum import dot,unit,vector


def create(doc,basis):
    part=doc.Part
    origin=vector(basis['origin_mm']);normal=unit(vector(basis['y']))
    supports=part.HybridBodies.Add();supports.Name='B60_MirrorSupport'
    plane=part.HybridShapeFactory.AddNewPlaneEquation(*normal,dot(origin,normal))
    plane.Name='B60_SymmetryPlane';supports.AppendHybridShape(plane)
    part.Update();part.InWorkObject=part.MainBody
    feature=part.ShapeFactory.AddNewMirror(part.CreateReferenceFromObject(plane))
    feature.Name='B60_StageMirror';part.Update()
    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody))
    return {'volume_mm3':measured.Volume*1e9,'area_mm2':measured.Area*1e6}
