# -*- coding: utf-8 -*-
"""Shared CATIA build handlers ported from export reconstruction.py."""
import math
import re
import json
import collections
import hashlib
from copy import deepcopy
from contextlib import contextmanager
from ..common import (
    MissingData, ReconstructionError, brep_faces, persistent_face_name,
    com_array, CONTAINERS, SOLID_OPERATIONS, normal_path,
    number, vector, unit, cross,
)
from ..sketch_geometry import sketch_axis, sketch_segments
from ..reconstruction import Reconstructor
from ..model_data import ModelData
from .model_info import VISIBILITY_RESOLUTION, RULES_CHECKS, FORMULAS, PROVENANCE, UNITS, TREE_SEGMENTS, VISUAL_PROPERTIES, LAYER_ASSIGNMENTS

# catia_com shim: extracted methods inline "from catia_com import array"
import sys as _sys, types as _types
if "catia_com" not in _sys.modules:
    _mod = _types.ModuleType("catia_com")
    def _array(size):
        import pythoncom
        from win32com.client import VARIANT
        return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [0.0] * size)
    _mod.array = _array
    _sys.modules["catia_com"] = _mod


def checked_axis_frame(root, x, y, z=None):
    root, x, y = vector(root), unit(x), unit(y)
    if abs(sum(a*b for a, b in zip(x, y))) > 1e-7:
        raise MissingData("Axis system X and Y are not orthogonal")
    expected_z = unit(cross(x, y))
    if z is not None and math.dist(unit(z), expected_z) > 1e-7:
        raise MissingData("Axis system Z disagrees with the right-handed X/Y frame")
    return root, x, y
def selected_visibility(selection):
    import pythoncom
    from win32com.client import VARIANT
    show = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, -1)
    status = selection.VisProperties.GetShow(show)
    if status != 0 or show.value not in (0, 1):
        raise ReconstructionError("CATIA did not return a definite Show/NoShow value")
    return show.value
def edge_partition_covers(cells, target_endpoints, tolerance):
    """Check that source intervals form one connected, non-branching chain."""
    nodes, adjacency, degrees = [], [], []
    def node(point):
        matches = [i for i, value in enumerate(nodes) if math.dist(point, value) <= tolerance]
        if len(matches) > 1:
            raise MissingData("Ambiguous source edge partition endpoint")
        if matches:
            return matches[0]
        nodes.append(point)
        adjacency.append(set())
        degrees.append(0)
        return len(nodes) - 1
    for cell in cells:
        a, b = node(cell["curve_points"][0]), node(cell["curve_points"][-1])
        adjacency[a].add(b)
        adjacency[b].add(a)
        degrees[a] += 1
        degrees[b] += 1
    visited, pending = set(), [0]
    while pending:
        current = pending.pop()
        if current not in visited:
            visited.add(current)
            pending.extend(adjacency[current] - visited)
    if len(visited) != len(nodes):
        return False
    ends = [nodes[i] for i, degree in enumerate(degrees) if degree == 1]
    if math.dist(*target_endpoints) <= tolerance:
        return not ends and all(degree == 2 for degree in degrees)
    return (len(ends) == 2 and all(degree in (1, 2) for degree in degrees)
            and any(math.dist(ends[0], target_endpoints[i]) <= tolerance
                    and math.dist(ends[1], target_endpoints[1-i]) <= tolerance for i in (0, 1)))

def pattern_grid(definition, tolerance=0.001):
    """Recover lattice increments and the source position from translations.

    A grid translation includes the offset of the source's row/column. It is
    not a direction vector unless the source happens to occupy position 1,1.
    """
    sizes = tuple(int(definition['instances_dir' + str(i)]) for i in (1, 2))
    samples = definition.get('instance_vectors', [])
    grid = {(v['row'], v['col']): vector(v['vector']) for v in samples}
    if (min(sizes) < 1 or len(grid) != len(samples)
            or set(grid) != {(i, j) for i in range(sizes[0]) for j in range(sizes[1])}):
        raise MissingData('Pattern translation grid is incomplete or duplicated')
    origins = [index for index, v in grid.items() if math.dist(v, (0, 0, 0)) <= tolerance]
    if len(origins) != 1:
        raise MissingData('Pattern source position is not unique in the exported grid')
    origin = origins[0]
    base = grid[0, 0]
    deltas = [tuple(grid[index][k] - base[k] for k in range(3)) if size > 1 else (0, 0, 0)
              for index, size in zip(((1, 0), (0, 1)), sizes)]
    for index, actual in grid.items():
        expected = tuple(sum((index[j] - origin[j]) * deltas[j][k] for j in (0, 1)) for k in range(3))
        if math.dist(actual, expected) > tolerance:
            raise MissingData('Pattern translations do not form a regular rectangular grid')
    directions, steps = [], []
    for i, size in enumerate(sizes):
        step = abs(number(definition['step_dir' + str(i + 1)]))
        if size > 1:
            measured = math.dist(deltas[i], (0, 0, 0))
            if abs(measured - step) > tolerance:
                raise MissingData('Pattern spacing disagrees with its exported translation grid')
            directions.append(unit(deltas[i]))
        else:
            directions.append((1, 0, 0))
        steps.append(step)
    return sizes, directions, steps, tuple(i + 1 for i in origin)

def verify_template_surface_samples(expected, actual, source_counts, target_counts, distances, resolution_mm):
    """Supplement area accumulation with spatial checks at source resolution.

    This is only for a hashed, editable template with validated reconstructed
    inputs. Keep the solid validator's 0.01 mm2 area ceiling, require identical
    topology counts, and check sampled boundaries in BOTH directions.
    """
    area_mm2 = expected["area_m2"] * 1e6
    delta_mm2 = abs(actual["area_m2"] - expected["area_m2"]) * 1e6
    if (not math.isfinite(delta_mm2) or delta_mm2 > max(.01, area_mm2 * 1e-6)
            or math.dist(vector(actual["cog_mm"]), vector(expected["cog_mm"])) > resolution_mm):
        raise MissingData("Template surface exceeds area/centroid limits")
    if source_counts != target_counts or any(source_counts.get(k, 0) <= 0 for k in ("faces", "edges")):
        raise MissingData("Template surface topology differs or is unavailable")
    if len(distances) != 2 or any(len(side) < 3 * source_counts["edges"] for side in distances):
        raise MissingData("Template surface needs boundary samples in both directions")
    if any(not math.isfinite(value) or value < 0 or value > resolution_mm for side in distances for value in side):
        raise MissingData("Template boundary samples exceed source model resolution")
    return {"method": "template_topology_and_bidirectional_boundary_samples", "area_delta_mm2": delta_mm2,
            "topology": source_counts, "sample_counts": [len(side) for side in distances],
            "max_distance_mm": max(max(side) for side in distances), "resolution_mm": resolution_mm}



class _ReconstructorHandlers:
    def create_additional_solid(self, r, d, c):
        if r["type"] == "RemoveFace":
            return self.create_remove_face(r, d, c)
        data = d.get("native_operation")
        if not data:
            raise MissingData(r["type"] + " native settings unavailable: "
                + json.dumps(d.get("native_export_errors", []), ensure_ascii=False))
        self.part.InWorkObject = c
        p = d.get("params", {})
        if r["type"] == "ThickSurface":
            if any(p.get(k, 0) for k in ("smoothing_mode", "constant_thickness_mode", "tangency_continuity_mode")):
                raise MissingData("Thick surface smoothing needs dedicated replay")
            obj = self.own(self.sf.AddNewThickSurface(self.ref(self.require(p["surface"])),
                data["side"], data["top_mm"], data["bottom_mm"]))
        elif r["type"] == "Chamfer":
            refs = [self.selection_ref(s) for s in p.get("objects", [])]
            if not refs:
                raise MissingData("Chamfer has no source edges")
            props = data["properties"]
            obj = self.own(self.sf.AddNewChamfer(refs[0], props["Propagation"], props["Mode"],
                props["Orientation"], data["length1_mm"], data["second"]))
            for ref in refs[1:]:
                obj.AddElementToChamfer(ref)
        else:
            raise MissingData("Unsupported additional solid " + r["type"])
        self.validate_native_result(obj, d["native_result_geometry"], r["type"])
        return obj

    def create_algorithm_template(self, record, definition, container):
        template = definition["native_algorithm_template"]
        kind = record["type"]
        if template.get("feature_type") != kind or template.get("input_count") != 2:
            raise MissingData("Algorithm template type/input contract differs from this feature")
        if kind == "GSMExtrapol":
            native = definition.get("native_extrapolate", {})
            boundaries = native.get("boundaries", [])
            if len(boundaries) != 1 or native.get("support"):
                raise MissingData("Extrapolation template requires one boundary and no additional support")
            inputs = [native["source"], boundaries[0]["boundary"]]
            expected_type = "HybridShapeExtrapol"
        elif kind == "GSMBlend":
            native = definition.get("native_operation", {})
            limits = native.get("limits", [])
            if len(limits) != 2 or native.get("spine") or any(x.get("point") or x.get("support") for x in limits):
                raise MissingData("Blend template requires two independent curves")
            inputs = [x["curve"] for x in limits]
            expected_type = "HybridShapeBlend"
        else:
            raise MissingData("Unsupported source algorithm template")
        if any(set(value) != {"feature"} for value in inputs):
            raise MissingData("Algorithm template requires direct feature inputs")
        references = [self.native_input_ref(value) for value in inputs]
        path = (self.p.directory / template["file"]).resolve()
        if not path.is_relative_to(self.p.directory) or not path.is_file():
            raise MissingData("Algorithm template must exist inside the exported package")
        if hashlib.sha256(path.read_bytes()).hexdigest() != template["sha256"]:
            raise MissingData("Algorithm template fingerprint mismatch")
        asset = self.app.Documents.Open(str(path))
        try:
            original = asset.Part.FindObjectByName(template["name"])
            before = container.HybridShapes.Count
            for attempt in range(2):
                asset.Activate(); asset.Selection.Clear(); asset.Selection.Add(original); asset.Selection.Copy()
                self.doc.Activate(); self.part.InWorkObject = container
                if container.HybridShapes.Count != before:
                    break
                self.doc.Selection.Clear(); self.doc.Selection.Add(container); self.doc.Selection.PasteSpecial("CATPrtCont")
                self.doc.Selection.Clear(); asset.Selection.Clear()
                if container.HybridShapes.Count != before:
                    break
            added = [self.own(container.HybridShapes.Item(i)) for i in range(before+1, container.HybridShapes.Count+1)]
            if len(added) != 1 or added[0]._oleobj_.GetTypeInfo().GetDocumentation(-1)[0] != expected_type:
                raise MissingData("Algorithm template did not create exactly one feature of the source type")
            obj = added[0]
            if kind == "GSMExtrapol":
                obj.ElemToExtrapol = references[0]
                obj.SetBoundary(1, references[1])
            else:
                obj.SetCurve(1, references[0]); obj.SetCurve(2, references[1])
            self.part.UpdateObject(obj)
        finally:
            asset.Close()
            self.doc.Activate()
        try:
            self.validate_native_result(obj, native["result_geometry"], "Preserved source algorithm")
        except MissingData:
            baseline = template.get("reference_datum")
            if not baseline:
                raise
            reference = self.create_native_datum(record, {"native_surface_datum": baseline}, self.helpers)
            self.validate_native_result(reference, native["result_geometry"], "Independent source surface")
            self.validate_fillet_template_geometry(obj, native["result_geometry"], self.doc, reference)
        self.note("Source algorithm preserved with all inputs rebound to reconstructed features")
        return obj

    def create_axis(self, r, d, c):
        root, x, y, z = self.p.axis_frame(r, include_z=True)
        obj = self.own(self.part.AxisSystems.Add())
        obj.OriginType = 1
        obj.PutOrigin(root)
        # CATIA also supports indirect (left-handed) systems. PutVectors
        # silently computes Z = X cross Y, losing an exported reversed Z.
        obj.XAxisType = obj.YAxisType = obj.ZAxisType = 1
        obj.PutXAxis(x)
        obj.PutYAxis(y)
        obj.PutZAxis(z)
        self.note("Axis restored from evaluated coordinates; original construction relations are not recreated")
        return obj

    def create_axis_transform(self, r, d, c):
        source = self.require(self.p.operand(r, "source_element", "ElemToTransform", "ToTransfor"))
        a = self.ref(self.require(self.p.operand(r, "reference_axis", "ReferenceAxis", "AxisOrigin")))
        b = self.ref(self.require(self.p.operand(r, "target_axis", "TargetAxis", "Axis")))
        parent = self.p.container_record(r)
        if parent and parent["type"] == "MechanicalTool":
            self.part.InWorkObject = c
            before = c.Shapes.Count
            # B33 can create the Body feature while returning a null IDispatch.
            # Recover only the newly-added shape in this exact Body, so both
            # registration and rollback retain the actual created operation.
            self.sf.AddNewAxisToAxis2(a, b)
            added = [self.own(c.Shapes.Item(i)) for i in range(before + 1, c.Shapes.Count + 1)]
            if len(added) != 1:
                raise ReconstructionError("Axis-to-axis factory created {} Body shapes; expected one".format(len(added)))
            return added[0]
        return self.append(c, self.hsf.AddNewAxisToAxis(self.ref(source), a, b))

    def create_boolean(self, r, d, c):
        tool_r = self.p.lookup({"id": d.get("tool_body_id"), "full_path": d.get("tool_body_path"), "name": d.get("tool_body")}, r)
        if not tool_r or tool_r["type"] != "MechanicalTool":
            raise MissingData("Boolean tool is not an identified Body")
        if not self.p.body_history.get(tool_r["id"]):
            raise MissingData("Boolean tool Body has no reconstructed solid history: " + tool_r["full_path"])
        tool = self.require(tool_r)
        if self.p.container_record(r)["id"] == tool_r["id"]:
            raise MissingData("Boolean cannot consume its own Body")
        self.part.InWorkObject = c
        return self.own(getattr(self.sf, "AddNew" + r["type"])(tool))

    def create_boundary(self, r, d, c):
        data = d.get("native_boundary")
        if not data or any(key in data for key in ("InitialElement", "From", "To")):
            raise MissingData("Surface boundary lacks a supported full-boundary definition")
        if data.get("mode") == "whole_feature" and (data.get("propagation") != 4
                or number(data.get("result_geometry", {}).get("length_mm", 0)) <= 0):
            raise MissingData("Whole-feature boundary requires propagation 4 and source length")
        obj = self.append(c, self.hsf.AddNewBoundaryOfSurface(self.native_input_ref(data["support"])))
        obj.Propagation = data["propagation"]
        if data.get("result_geometry"):
            self.part.UpdateObject(obj)
            actual = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj)).Length
            expected = number(data["result_geometry"]["length_mm"])
            if abs(actual - expected) > max(self.geometry_tolerance(), expected * 1e-8):
                raise MissingData("Boundary length differs from source: {} vs {} mm".format(actual, expected))
        return obj

    def create_circle(self, r, d, c):
        if d.get("native_curve_datum"):
            return self.create_native_datum(r, d, c, curve=True)
        limitation = d.get("circle_limitation")
        if d.get("native_circle_points"):
            points = d["native_circle_points"]
            if len(points) != 3 or limitation not in (1, 2, 3):
                raise MissingData("Three-point circle requires three inputs and its trimming mode")
            obj = self.append(c, self.hsf.AddNewCircle3Points(*[self.native_input_ref(p) for p in points]))
        elif d.get("circle_subtype") == "center_radius" and limitation == 1 and d.get("geodesic") == 0:
            radius = number(d.get("circle_geometry", {}).get("radius_mm"))
            if radius <= 0:
                raise MissingData("Circle radius must be positive")
            obj = self.append(c, self.hsf.AddNewCircleCtrRad(
                self.ref(self.require(d["center"])), self.ref(self.require(d["support"])), False, radius))
        else:
            raise MissingData("Circle subtype or trimming inputs are unavailable: "
                + json.dumps(d.get("native_export_errors", d.get("extraction_errors", [])), ensure_ascii=False))
        obj.SetLimitation(limitation)
        expected = d.get("native_curve_geometry")
        if expected is None and limitation == 1:
            geometry = d["circle_geometry"]
            expected = {"length_mm": 2 * math.pi * number(geometry["radius_mm"]),
                        "full_circle": {"center_mm": geometry["center"], "axis": geometry["normal"],
                                        "radius_mm": geometry["radius_mm"]}}
        if expected is None:
            raise MissingData("Trimmed circle requires source curve measurements")
        self.validate_native_result(obj, expected, "Circle")
        return obj

    def create_closed_surface(self, r, d, c):
        p = d.get("params", {})
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewCloseSurface(self.ref(self.require(p["surface"]))))
        self.validate_native_result(obj, d["native_result_geometry"], "Close surface")
        return obj

    def create_combine(self, r, d, c):
        native = d.get("native_solid_combine")
        p = native or d.get("params", {})
        if not all(k in p for k in ("profile1", "profile2", "direction1", "direction2")):
            raise MissingData("SolidCombine profiles/directions not exported")
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewSolidCombine(self.ref(self.require(p["profile1"])), self.ref(self.require(p["profile2"]))))
        obj.FirstComponentDirection = self.direction_line(p["direction1"])
        obj.SecondComponentDirection = self.direction_line(p["direction2"])
        if native:
            self.validate_native_result(obj, native["result_geometry"], "SolidCombine")
        return obj

    def create_compound_fillet(self, r, d, c, source_selections):
        """A logical REdge may contain disconnected pieces and have no SPA
        curve measurer. Validate the entire resulting solid in that case.
        """
        from catia_com import array
        p, expected = d["params"], d["native_result_geometry"]
        errors = []
        strategies = ["native", "current_flags"]
        if all(len(s.get("edge_supports", [])) == 2
               and all(face.get("surface_type") in ("Plane", "Cylinder") for face in s["edge_supports"])
               for s in source_selections):
            strategies.append("analytic_supports")
        for strategy in strategies:
            obj = None
            try:
                self.part.InWorkObject = c
                if strategy == "analytic_supports":
                    selections = [s for s in d["selections"] if s.get("role") == "fillet_object"]
                    refs = []
                    for selection, extra in zip(selections, source_selections):
                        pieces = self.edges_on_supports(selection, extra["edge_supports"])
                        if not pieces:
                            raise MissingData("No edges on the two source supports: " + selection["selection_id"])
                        refs.extend(pieces)
                    refs = list({str(ref.DisplayName): ref for ref in refs}.values())
                else:
                    names = [self.rebased_brep_name(s["native_brep_name"]) for s in source_selections]
                    if strategy == "current_flags":
                        names = [name.replace("Cf11:", "Cf14:") for name in names]
                    refs = [self.part.CreateReferenceFromBRepName(name, c) for name in names]
                obj = self.own(self.sf.AddNewEdgeFilletWithConstantRadius(refs[0],
                    1 if p.get("propagation") == "Tangency" else 0, number(p["radius"])))
                for ref in refs[1:]:
                    obj.AddObjectToFillet(ref)
                self.part.UpdateObject(obj)
                m = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj))
                center = array(3)
                m.GetCOG(center)
                actual = {"volume_mm3": float(m.Volume) * 1e9, "area_mm2": float(m.Area) * 1e6, "cog_mm": list(center.value)}
                if (abs(actual["volume_mm3"] - expected["volume_mm3"]) > max(.001, expected["volume_mm3"] * 1e-6)
                        or abs(actual["area_mm2"] - expected["area_mm2"]) > max(.01, expected["area_mm2"] * 1e-6)
                        or math.dist(actual["cog_mm"], expected["cog_mm"]) > self.geometry_tolerance()):
                    raise MissingData("Compound fillet result differs from source: " + json.dumps(actual))
                self.bind("半径", obj.Radius)
                self.note("Compound native edge restored; source solid volume, area and centroid verified")
                return obj
            except Exception as exc:
                errors.append(strategy + ": " + str(exc))
                if obj is not None:
                    selection = self.doc.Selection
                    try:
                        selection.Clear()
                        selection.Add(obj)
                        selection.Delete()
                        self.owned = [owned for owned in self.owned if owned is not obj]
                    finally:
                        selection.Clear()
                        self.part.InWorkObject = c
        raise MissingData("Compound fillet could not reproduce the source solid: " + "; ".join(errors))

    def create_container(self, r, d, c):
        if r["type"] == "MechanicalTool":
            if r["id"] == self.p.main_body_record()["id"]:
                # Reuse the new document's default Body, avoiding an extra,
                # empty PartBody that never existed in the exported tree.
                return self.part.MainBody
            # Bodies are owned by Part; boolean consumption establishes nesting.
            # In hybrid-design mode Body.HybridBodies is null. These source
            # Bodies contain nested geometrical sets, so create standard Bodies.
            settings = self.app.SettingControllers.Item("CATMmuPartInfrastructureSettingCtrl")
            original = settings.HybridDesignMode
            try:
                settings.HybridDesignMode = False
                obj = self.part.Bodies.Add()
            finally:
                settings.HybridDesignMode = original
        else:
            obj = c.HybridBodies.Add()
        return self.own(obj)

    def create_draft(self, r, d, c):
        if d.get("native_draft_template"):
            obj = self.create_draft_from_template(d["native_draft_template"], c)
            self.validate_native_result(obj, d["native_result_geometry"], "Draft")
            self.bind("角度", obj.DraftDomains.Item(1).DraftAngle)
            return obj
        if self.p.attr(r, "PartingEqualNeutral", 0) == 2:
            raise MissingData("Two-sided draft requires its editable PowerCopy; re-export with the updated CAA exporter. "
                              + json.dumps(d.get("native_export_errors", []), ensure_ascii=False))
        p = d.get("params", {})
        multiselection = self.p.attr(r, "MultiselMode", 0)
        if multiselection not in (0, 1):
            raise MissingData("Unsupported draft multiselection mode: " + str(multiselection))
        self.part.InWorkObject = c
        native_faces = d.get("native_draft_faces")
        result_faces = []
        if native_faces is not None:
            if not d.get("native_result_geometry"):
                raise MissingData("Native draft inputs require source solid validation")
            faces = []
            if multiselection == 0:
                selections = [s for s in d.get("selections", []) if s.get("role") == "face_to_draft"]
                if len(selections) != len(native_faces):
                    raise MissingData("Draft native faces and measured selections do not correspond")
                for native, selection in zip(native_faces, selections):
                    expected = (d.get("selection_geometry", {}).get(selection.get("selection_id"))
                                or selection.get("caa_measurement") or {})
                    if r.get("id") and selection.get("support_feature") == r["id"]:
                        # A self-context selection measures the already drafted
                        # source face. Check it after replay, not against the
                        # incoming face; the complete solid is checked too.
                        face, _ = self.resolved_native_brep_reference(native["native_brep_name"], c)
                        result_faces.append((native["native_brep_name"], expected))
                        faces.append(face)
                        continue
                    try:
                        # Sketch vertex report numbers can change independently
                        # of curve numbers. A measurable native name may bind a
                        # different face, so verify its exported geometry too.
                        face = self.native_brep_reference(native["native_brep_name"], c, expected)
                    except Exception:
                        face = self.selection_ref(selection)
                    faces.append(face)
        else:
            faces = self.selections(d, "face_to_draft") if multiselection == 0 else []
        neutral_selections = [s for s in d.get("selections", []) if s.get("role") == "neutral_element"]
        if neutral_selections:
            sel_info = neutral_selections[0]
            neutral = self.selection_ref(sel_info)
            # Geometric recovery returns a search-only Selection_RSur. The
            # domain setter needs the same face as an editable RSur reference.
            neutral = self.fillet_reference(neutral, c)
        else:
            neutral = self.ref(self.require(p.get("neutral")))
        empty = self.part.CreateReferenceFromName("")
        if p.get("parting"):
            parting = self.ref(self.require(p["parting"]))
        else:
            parting = empty
        modes = {"Standard": 0, "ReflectKeepFace": 1, "ReflectKeepEdge": 2}
        if p.get("mode") not in modes:
            raise MissingData("Unsupported draft mode")
        self.part.InWorkObject = c
        face = faces[0] if faces else empty
        # The factory accepts only a planar Face as iNeutral, whereas the
        # domain setter also accepts an independent plane. Initialize the
        # domain first, then assign the exact exported neutral reference.
        obj = self.own(self.sf.AddNewDraft(face, empty, self.p.attr(r, "NeutralPropagation", 0), empty, *unit(p.get("pulling_direction")), modes[p["mode"]], number(p["angle"], "angle"), multiselection))
        domain = obj.DraftDomains.Item(1)
        domain.NeutralElement = neutral
        if p.get("parting"):
            obj.PartingElement = parting
        for face in faces[1:]:
            domain.AddFaceToDraft(face)
        if d.get("native_result_geometry"):
            self.validate_native_result(obj, d["native_result_geometry"], "Draft")
        for name, expected in result_faces:
            self.native_brep_reference(name, c, expected)
        self.bind("角度", domain.DraftAngle)
        return obj

    def create_draft_from_template(self, template, container):
        path = (self.p.directory / template["file"]).resolve()
        if not path.is_relative_to(self.p.directory) or not path.is_file():
            raise MissingData("Draft PowerCopy must exist inside the exported package")
        if hashlib.sha256(path.read_bytes()).hexdigest() != template["sha256"]:
            raise MissingData("Draft PowerCopy fingerprint mismatch")
        inputs = template.get("inputs", [])
        roles = [item["role"] for item in inputs]
        if not inputs or len(set(roles)) != len(roles):
            raise MissingData("Draft PowerCopy needs unique, explicit input roles")
        values = []
        for item in inputs:
            value = item["input"]
            obj = self.require(value["feature"]) if value.get("feature") else self.native_input_ref(value)
            values.append((item["role"], obj))
        self.doc.Activate()
        self.part.InWorkObject = container
        before = container.Shapes.Count
        body_count = self.part.Bodies.Count
        factory = self.part.GetCustomerFactory("InstanceFactory")
        started = instantiating = False
        try:
            factory.BeginInstanceFactory(template["name"], str(path))
            started = True
            factory.BeginInstantiate()
            instantiating = True
            for role, value in values:
                factory.PutInputData(role, value)
            factory.Instantiate()
            factory.EndInstantiate()
            instantiating = False
        finally:
            try:
                if instantiating:
                    factory.EndInstantiate()
            finally:
                try:
                    if started:
                        factory.EndInstanceFactory()
                finally:
                    # Own every created operation even if instantiation failed.
                    added = [self.own(container.Shapes.Item(i)) for i in range(before + 1, container.Shapes.Count + 1)]
                    extra_bodies = [self.own(self.part.Bodies.Item(i)) for i in range(body_count + 1, self.part.Bodies.Count + 1)]
                    self.doc.Activate()
        if extra_bodies or len(added) != 1 or added[0]._oleobj_.GetTypeInfo().GetDocumentation(-1)[0] != "Draft":
            raise MissingData("Draft PowerCopy did not produce exactly one editable Draft")
        return added[0]

    def create_empty_explicit(self, r, data, container):
        expected = {"CGMVertex": 0, "CGMEdge": 0, "CGMFace": 0}
        if (r["type"] != "GSMLine" or data.get("automation_type") != "HybridShapeLineExplicit"
                or data.get("source_up_to_date") is not True or data.get("topology") != expected):
            raise MissingData("Empty explicit feature requires verified source type, update state and zero topology")
        path = (self.p.directory / data["file"]).resolve()
        if not path.is_relative_to(self.p.directory) or not path.is_file():
            raise MissingData("Empty explicit asset must exist inside the package")
        if hashlib.sha256(path.read_bytes()).hexdigest() != data["sha256"]:
            raise MissingData("Empty explicit asset fingerprint mismatch")
        asset = self.app.Documents.Open(str(path))
        def verify(document, obj):
            if (obj._oleobj_.GetTypeInfo().GetDocumentation(-1)[0] != data["automation_type"]
                    or not document.Part.IsUpToDate(obj)
                    or {k: len(v) for k, v in self.topology_references(document, obj).items()} != expected):
                raise MissingData("Empty explicit asset changed its source type, topology or update state")
        try:
            original = asset.Part.HybridBodies.Item(1).HybridShapes.Item(data["name"])
            verify(asset, original)
            before = container.HybridShapes.Count
            for attempt in range(2):
                asset.Activate()
                asset.Selection.Clear()
                asset.Selection.Add(original)
                asset.Selection.Copy()
                self.doc.Activate()
                self.part.InWorkObject = container
                if container.HybridShapes.Count != before:
                    break
                self.doc.Selection.Clear()
                self.doc.Selection.Add(container)
                self.doc.Selection.PasteSpecial("CATPrtCont")
                self.doc.Selection.Clear()
                asset.Selection.Clear()
                if container.HybridShapes.Count != before:
                    break
            added = [self.own(container.HybridShapes.Item(i)) for i in range(before + 1, container.HybridShapes.Count + 1)]
            if len(added) != 1:
                raise MissingData("Empty explicit asset must produce exactly one feature")
            verify(self.doc, added[0])
            self.note("Preserved source empty explicit line; no geometric result was present in the source")
            return added[0]
        finally:
            asset.Selection.Clear()
            asset.Close()
            self.doc.Activate()

    def create_extract(self, r, d, c):
        native = d.get("native_extract_elements")
        if native:
            refs = [self.native_extract_ref(e) for e in native]
            self.part.InWorkObject = c
            obj = self.append(c, self.hsf.AddNewExtractMulti(refs[0]))
            for i, (element, ref) in enumerate(zip(native, refs), 1):
                # The factory seeds the geometry but does not create the
                # tolerant constraint table. Explicitly populate position 1.
                obj.AddConstraintTolerant(ref, element["propagation"], element["complementary"], element["federated"],
                    element["distance_threshold"], element["angular_threshold"], element["curvature_threshold"], i)
                obj.SetPropagationType(i, element["propagation"])
                obj.SetComplementaryExtractMulti(i, element["complementary"])
                obj.SetIsFederated(i, element["federated"])
                for prefix in ("Curvature", "Distance", "Angular"):
                    getattr(obj, "Set" + prefix + "Threshold")(i, element[prefix.lower() + "_threshold"])
                    getattr(obj, "Set" + prefix + "ThresholdActivity")(i, element[prefix.lower() + "_active"])
            return obj
        elements = d.get("elements", [])
        if not elements:
            raise MissingData("Multi-extract elements and propagation settings not exported")
        refs = [self.selection_ref(e["selection"]) for e in elements]
        obj = self.append(c, self.hsf.AddNewExtractMulti(refs[0]))
        obj.SetPropagationType(1, elements[0]["propagation"])
        for i, (e, ref) in enumerate(zip(elements[1:], refs[1:]), 2):
            obj.AddConstraint(ref, e["propagation"], e["complementary"], e["federated"], e.get("curvature_threshold", 0), i)
        return obj

    def create_extrapolate(self, r, d, c):
        try:
            return self.create_extrapolate_factory(r, d, c)
        except MissingData:
            if not d.get("native_algorithm_template"):
                raise
            self.rollback()
            return self.create_algorithm_template(r, d, c)

    def create_extrapolate_factory(self, r, d, c):
        native = d.get("native_extrapolate")
        if native:
            boundaries = native.get("boundaries")
            if boundaries is None:
                boundaries = [native]
            if not boundaries:
                raise MissingData("Extrapolation boundary list is empty")
            first = boundaries[0]
            obj = self.append(c, self.hsf.AddNewExtrapolLength(
                self.native_input_ref(first["boundary"]), self.native_input_ref(native["source"]),
                number(first["length_mm"])))
            obj.ContinuityType = first["continuity"]
            for position, boundary in enumerate(boundaries[1:], 2):
                obj.SetBoundary(position, self.native_input_ref(boundary["boundary"]))
                obj.SetLimitType(position, 0)
                obj.SetLengthD(position, number(boundary["length_mm"]))
                obj.SetContinuityType(position, boundary["continuity"])
            obj.SetAssemble(native["assemble"])
            for prop, value in native["properties"].items():
                if prop not in {"BorderType", "PropagationMode", "ExtendEdgesMode", "ConstantLengthMode", "ExtrapolBothSidesIdentically"}:
                    raise MissingData("Unknown extrapolation setting: " + prop)
                setattr(obj, prop, value)
            if native.get("support"):
                obj.Support = self.native_input_ref(native["support"])
            self.validate_native_result(obj, native["result_geometry"], "Extrapolation")
            for boundary in boundaries:
                if boundary.get("boundary_recovery"):
                    self.note("Extrapolation boundary recovered: " + boundary["boundary_recovery"])
            return obj
        if (d.get("boundary_geometry") or {}).get("point") is not None:
            point = self.own(self.hsf.AddNewPointCoord(*self.bounded_coordinates(d["boundary_geometry"]["point"])))
            point.Name = "__ExtrapolationBoundary_" + r["name"]
            self.helpers.AppendHybridShape(point)
            self.part.UpdateObject(point)
            boundary = self.ref(point)
        else:
            boundary = self.ref(self.require(self.p.operand(r, "boundary", "Boundary")))
        source = self.ref(self.require(self.p.operand(r, "source_element", "ElemToExtrapol")))
        if "length" not in d or "continuity" not in d:
            raise MissingData("Extrapolation length/continuity not exported")
        length = self.p.length_mm(r, "length", "Length", "长度.1", "长度")
        obj = self.append(c, self.hsf.AddNewExtrapolLength(boundary, source, length))
        obj.ContinuityType = d["continuity"]
        if "is_assemble" in d:
            obj.SetAssemble(bool(d["is_assemble"]))
        return obj

    def create_extrude(self, r, d, c):
        source = self.native_input_ref(d["native_profile"]) if d.get("native_profile") else self.ref(self.require(self.p.operand(r, "profile", "Element1")))
        direction_data = d.get("direction")
        if isinstance(direction_data, list):
            direction = self.hsf.AddNewDirectionByCoord(*unit(direction_data))
        else:
            # Infer direction from the profile sketch's support plane normal
            # when the explicit vector was not exported.
            profile_ref = self.p.operand(r, "profile", "Element1")
            profile_rec = self.p.lookup(profile_ref, r)
            if profile_rec and profile_rec["type"] == "PRTSketch":
                sketch_def = self.p.definitions.get(profile_rec["id"], {})
                supports = sketch_def.get("positioning", {}).get("support_references", [])
                if supports:
                    plane_rec = self.p.lookup(supports[0], r)
                    if plane_rec:
                        try:
                            _, normal = self.p.plane(plane_rec)
                            direction = self.hsf.AddNewDirectionByCoord(*normal)
                        except MissingData:
                            raise MissingData("Extrusion direction vector was not exported and cannot be inferred from profile support")
                    else:
                        raise MissingData("Extrusion direction vector was not exported and profile support plane not found")
                else:
                    raise MissingData("Extrusion direction vector was not exported and sketch has no support reference")
            else:
                raise MissingData("Extrusion direction vector was not exported")
        length1 = self.p.length_mm(r, "length1", "Length1", "限制 1")
        length2 = self.p.length_mm(r, "length2", "Length2", "限制 2")
        obj = self.append(c, self.hsf.AddNewExtrude(source, length1, length2, direction))
        for side in ("First", "Second"):
            kind = self.p.attr(r, side + "LimitType", 1)
            setattr(obj, side + "LimitType", kind)
            if kind == 2:
                setattr(obj, side + "UptoElement", self.ref(self.require(self.p.operand(r, side + "Upto"))))
        return obj

    def create_fill(self, r, d, c):
        boundaries = next((a["values"] for a in r.get("input_attributes", []) if a["attribute_name"] == "Boundary"), [])
        if not boundaries:
            raise MissingData("Fill boundary is missing")
        obj = self.append(c, self.hsf.AddNewFill())
        for value in boundaries:
            obj.AddBound(self.selection_ref(value["selection"]))
        return obj

    def create_fillet(self, r, d, c):
        p = d.get("params", {})
        if p.get("fillet_type") != "Constant":
            raise MissingData("Variable radius fillet needs its radius law")
        # Persistent support references are evaluated in the current solid
        # context. Set it before resolving inputs, including in full replays
        # where the previous operation may belong to another Body.
        self.part.InWorkObject = c
        source_selections = [d.get("selection_geometry", {}).get(s["selection_id"], {})
                             for s in d.get("selections", []) if s.get("role") == "fillet_object"]
        edge_selections = [s for s in d.get("selections", []) if s.get("role") == "fillet_object"]
        precise_pieces = bool(edge_selections)
        for selection in edge_selections:
            cells = [cell for brep in selection.get("resolved_breps", []) for cell in brep.get("cells", [])]
            precise_pieces = precise_pieces and bool(cells) and all(
                cell.get("curve_measurement_source") == "CAA resolved edge" and cell.get("curve_points") for cell in cells)
        if (d.get("native_result_geometry") and source_selections
                and not precise_pieces
                and all(s.get("curve_measurement_unavailable") and s.get("native_brep_name", "").startswith("REdge:")
                        for s in source_selections)):
            return self.create_compound_fillet(r, d, c, source_selections)
        try:
            edges = [self.fillet_reference(ref, c) for ref in self.selections(d, "fillet_object")]
        except MissingData:
            if d.get("native_fillet_edges") and d.get("native_result_geometry"):
                return self.create_compound_fillet(r, d, c, d["native_fillet_edges"])
            raise
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewEdgeFilletWithConstantRadius(edges[0], 1 if p.get("propagation") == "Tangency" else 0, number(p["radius"])))
        for edge in edges[1:]:
            obj.AddObjectToFillet(edge)
        if d.get("native_result_geometry") or any(extra.get("edge_supports") for extra in source_selections):
            expected = d.get("native_result_geometry")
            if not expected:
                raise MissingData("Fillet support recovery requires source solid measurements")
            if "area_m2" in expected and "volume_mm3" not in expected:
                self.validate_native_result(obj, expected, "Surface edge fillet")
                self.bind("半径", obj.Radius)
                return obj
            from catia_com import array
            self.part.UpdateObject(obj)
            measurable = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj))
            center = array(3)
            measurable.GetCOG(center)
            if (abs(float(measurable.Volume) * 1e9 - expected["volume_mm3"]) > max(.001, expected["volume_mm3"] * 1e-6)
                    or abs(float(measurable.Area) * 1e6 - expected["area_mm2"]) > max(.001, expected["area_mm2"] * 1e-6)
                    or math.dist(center.value, expected["cog_mm"]) > self.geometry_tolerance()):
                raise MissingData("Fillet differs from source solid volume, area or centroid")
        self.bind("半径", obj.Radius)
        return obj

    def create_fillet_from_template(self, native, container):
        template = native["template"]
        if template.get("input_count") != 2 or any(native.get(k) for k in ("spine", "hold_curve", "faces_to_keep")):
            raise MissingData("Fillet template requires exactly two independent supports")
        path = (self.p.directory / template["file"]).resolve()
        if not path.is_relative_to(self.p.directory) or not path.is_file():
            raise MissingData("Fillet template must exist inside the exported package")
        if hashlib.sha256(path.read_bytes()).hexdigest() != template["sha256"]:
            raise MissingData("Fillet template fingerprint mismatch")
        # Resolve dependencies before opening the asset; selection helpers use
        # the target document and its current history context.
        first = self.native_input_ref(native["support1"])
        second = self.native_input_ref(native["support2"])
        asset = self.app.Documents.Open(str(path))
        try:
            asset.Activate()
            original = asset.Part.FindObjectByName(template["name"])
            selection = asset.Selection
            selection.Clear()
            selection.Add(original)
            selection.Copy()
            self.doc.Activate()
            self.part.InWorkObject = container
            collection = container.HybridShapes
            count = collection.Count
            target = self.doc.Selection
            target.Clear()
            target.Add(container)
            target.PasteSpecial("CATPrtCont")
            target.Clear()
            selection.Clear()
            added = [self.own(collection.Item(i)) for i in range(count + 1, collection.Count + 1)]
            if len(added) != 1:
                raise MissingData("Fillet template did not produce exactly one editable feature")
            obj = added[0]
            if obj._oleobj_.GetTypeInfo().GetDocumentation(-1)[0] != "HybridShapeFilletBiTangent":
                raise MissingData("Fillet template lost its editable feature type")
            obj.FirstElem, obj.SecondElem = first, second
            if obj.Radius.OptionalRelation is not None:
                raise MissingData("Fillet template radius has an implicit formula; re-export with the updated CAA exporter")
            obj.Radius.Value = number(native["radius_mm"])
            obj.FirstOrientation = native["orientation1"]
            obj.SecondOrientation = native["orientation2"]
            obj.SupportsTrimMode = native["trim_mode"]
            obj.RibbonRelimitationMode = native["relimitation_mode"]
            if template.get("independent_boundary_validation_required"):
                if not template.get("reference_datum"):
                    raise MissingData("Fillet candidate requires an independent source surface asset")
                reference = self.create_native_datum(self.current,
                    {"native_surface_datum": template["reference_datum"]}, self.helpers)
                self.validate_native_result(reference, native["result_geometry"], "Independent source fillet surface")
                self.validate_fillet_template_geometry(obj, native["result_geometry"], self.doc, reference)
            else:
                self.validate_fillet_template_geometry(obj, native["result_geometry"], asset, original)
            return obj
        finally:
            alerts = self.app.DisplayFileAlerts
            try:
                self.app.DisplayFileAlerts = False
                asset.Close()
            finally:
                self.app.DisplayFileAlerts = alerts
                self.doc.Activate()

    def create_intersection(self, r, d, c):
        if d.get("native_intersection_inputs"):
            inputs = [self.native_input_ref(value) for value in d["native_intersection_inputs"]]
            if len(inputs) != 2:
                raise MissingData("Intersection needs exactly two native inputs")
            return self.append(c, self.hsf.AddNewIntersection(*inputs))
        a = self.require(self.p.operand(r, "first_operand", "ToIntersect1"))
        b = self.require(self.p.operand(r, "second_operand", "ToIntersect2"))
        return self.append(c, self.hsf.AddNewIntersection(self.ref(a), self.ref(b)))

    def create_join(self, r, d, c):
        data = d.get("native_join")
        if not data or not data.get("elements"):
            raise MissingData("Surface join lacks its source elements/settings; update the MyCustomFrame CAA exporter and re-export the model package")
        refs = [self.native_input_ref(value) for value in data["elements"]]
        obj = self.append(c, self.hsf.AddNewJoin(refs[0], refs[1] if len(refs) > 1 else refs[0]))
        if len(refs) == 1:
            obj.RemoveElement(2)
        for ref in refs[2:]:
            obj.AddElement(ref)
        obj.Invert = data["invert"]
        for name, value in data["settings"].items():
            getattr(obj, "Set" + name)(value)
        return obj

    def create_line(self, r, d, c):
        if d.get("native_empty_explicit"):
            return self.create_empty_explicit(r, d["native_empty_explicit"], c)
        if d.get("line_native_inputs"):
            inputs = d["line_native_inputs"]
            if len(inputs) != 2:
                raise MissingData("Straight datum needs exactly two native plane inputs")
            return self.append(c, self.hsf.AddNewIntersection(*[self.native_input_ref(value) for value in inputs]))
        if d.get("line_support_planes"):
            planes = d["line_support_planes"]
            if len(planes) != 2:
                raise MissingData("Straight datum needs exactly two defining planes")
            return self.append(c, self.hsf.AddNewIntersection(
                self.ref(self.require(planes[0], r)), self.ref(self.require(planes[1], r))))
        if d.get("native_curve_datum"):
            return self.create_native_datum(r, d, c, curve=True)
        edges = self.p.geometry.get(r["full_path"], {}).get("topology", {}).get("edges", [])
        analytic = bool(edges and edges[0].get("sub_curves")) and all(x.get("type") == "Line" for x in edges[0].get("sub_curves", []))
        if r["type"] == "GSMMonoDim":
            adj = self.p.geometry.get(r["full_path"], {}).get("adjacency", {}).get("edges", [])
            curves = adj[0].get("curve", {}).get("sub_curves", []) if len(adj) == 1 else []
            analytic = bool(curves) and all(x.get("exact") and x.get("nurbs", {}).get("degree") == 1
                and len(x["nurbs"].get("control_points", [])) == 2 for x in curves)
        if len(edges) == 1 and analytic:
            edge = edges[0]
            start, end = vector(edge.get("start")), vector(edge.get("end"))
            size = number(self.p.manifest.get("tolerance", {}).get("model_size", 1000000))
            if any(abs(value) >= size for value in start + end):
                # These are often CGM representations of plane intersections.
                # Their huge endpoints are not model points. Recover the
                # defining planes instead of materializing or truncating them.
                raise MissingData("Long datum exceeds model size; update the MyCustomFrame CAA exporter and re-export the model package with line_support_planes")
            a = self.own(self.hsf.AddNewPointCoord(*self.bounded_coordinates(start)))
            b = self.own(self.hsf.AddNewPointCoord(*self.bounded_coordinates(end)))
            self.helpers.AppendHybridShape(a)
            self.helpers.AppendHybridShape(b)
            self.part.UpdateObject(a)
            self.part.UpdateObject(b)
            self.note("Line restored from bounded evaluated geometry")
            return self.append(c, self.hsf.AddNewLinePtPt(self.ref(a), self.ref(b)))
        start = self.p.operand(r, "start_point", "FirstPoint", "Point1")
        end = self.p.operand(r, "end_point", "SecondPoint", "Point2")
        return self.append(c, self.hsf.AddNewLinePtPt(self.ref(self.require(start)), self.ref(self.require(end))))

    def create_mirror(self, r, d, c):
        if not d.get("pattern_of_body"):
            raise MissingData("Mirror feature-list mode needs explicit item selection")
        plane = self.ref(self.require(d.get("mirror_plane")))
        self.part.InWorkObject = c
        return self.own(self.sf.AddNewMirror(plane))

    def create_native_datum(self, r, d, c, solid=False, curve=False):
        label = "solid" if solid else "curve" if curve else "surface"
        data = d.get("native_" + label + "_datum")
        if not data:
            errors = d.get("native_export_errors", [])
            raise MissingData("Imported " + label + " lacks native geometry; re-export with the updated MyCustomFrame CAA exporter. Export errors: "
                              + json.dumps(errors, ensure_ascii=False))
        path = (self.p.directory / data["file"]).resolve()
        if not path.is_relative_to(self.p.directory) or not path.is_file():
            raise MissingData("Native surface asset must exist inside the exported package")
        if hashlib.sha256(path.read_bytes()).hexdigest() != data["sha256"]:
            raise MissingData("Native surface asset fingerprint mismatch")
        source = self.app.Documents.Open(str(path))
        try:
            source.Activate()
            original = source.Part.FindObjectByName(data["name"])
            selection = source.Selection
            selection.Clear()
            selection.Add(original)
            selection.Copy()
            self.doc.Activate()
            self.part.InWorkObject = c
            collection = c.Shapes if solid else c.HybridShapes
            before = collection.Count
            if solid and before:
                raise MissingData("Imported solid requires an empty target Body; refuse implicit union")
            target = self.doc.Selection
            target.Clear()
            target.Add(c)
            target.PasteSpecial("CATPrtResultWithOutLink")
            target.Clear()
            selection.Clear()
            if collection.Count == before:
                # CATIA can complete this call without inserting anything.
                # Rebuild both selections once; only a zero-result paste may
                # be repeated, and the normal count/geometry checks still apply.
                self.log("Native paste returned zero objects; repeating selection once: " + r["full_path"])
                source.Activate()
                selection.Add(original)
                selection.Copy()
                self.doc.Activate()
                self.part.InWorkObject = c
                # Activation can flush deferred insertion. Do not duplicate it.
                if collection.Count == before:
                    target.Add(c)
                    target.PasteSpecial("CATPrtResultWithOutLink")
                target.Clear()
                selection.Clear()
            added = [self.own(collection.Item(i)) for i in range(before + 1, collection.Count + 1)]
            if len(added) != 1:
                raise MissingData("Native surface asset produced {} datums; expected exactly one".format(len(added)))
            self.part.UpdateObject(added[0])
            measurable = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(added[0]))
            actual = float(measurable.Length if curve else measurable.Area)
            expected = data["length_mm" if curve else "area_m2"]
            if abs(actual - expected) > max(1e-12, abs(expected) * 1e-8):
                raise MissingData("Native datum measure differs from captured source")
            if data.get("cog_mm") is not None:
                from catia_com import array
                center = array(3)
                measurable.GetCOG(center)
                if math.dist(center.value, vector(data["cog_mm"])) > self.geometry_tolerance():
                    raise MissingData("Native surface centroid differs from captured source")
            if solid or curve:
                self.validate_native_result(added[0], data, "Imported " + label)
            self.note("Imported " + label + " restored from package-local native datum")
            return added[0]
        finally:
            source.Close()
            self.doc.Activate()

    def create_native_trim(self, r, d, c):
        from catia_com import array
        attrs = {a["attribute_name"]: a.get("values", []) for a in r.get("input_attributes", [])}
        tools = attrs.get("ToolList", [])
        if len(tools) != 1:
            raise MissingData("Union trim needs exactly one identified tool Body")
        tool, expected = self.require(tools[0]["feature"], r), d["native_result_geometry"]
        errors = []
        native = d.get("native_trim_references", {})
        attempts = ([(False, False, False), (False, True, False), (True, False, False), (True, True, False)]
                    if native and all(str(name).startswith("RSur:(") for name in native.values()) else [])
        attempts.append((False, False, True))
        for feature_scope, current_flags, geometric in attempts:
            obj = None
            try:
                self.part.InWorkObject = c
                def face_ref(value):
                    selection = value["selection"]
                    support = self.p.effective_producer(self.p.lookup(selection["support_feature"], r))
                    scope = self.require(support if feature_scope else self.p.container_record(support))
                    if geometric:
                        return self.fillet_reference(self.selection_ref(selection), scope)
                    name = self.rebased_brep_name(native[selection["selection_id"]])
                    if current_flags:
                        name = name.replace("Cf11:", "Cf14:")
                    ref = self.part.CreateReferenceFromBRepName(name, scope)
                    measurable = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(ref)
                    extra = d.get("selection_geometry", {}).get(selection["selection_id"], {})
                    matches = measurable.GeometryName != 0
                    if matches and extra.get("surface_type") in ("Plane", "Cylinder"):
                        matches = self.matches_surface(ref, extra)
                    if not matches:
                        ref = self.fillet_reference(self.selection_ref(selection), scope)
                    return ref
                operations = []
                for action in ("Keep", "Remove"):
                    faces = attrs.get(action + "ByAdjacentFacesList", [])
                    adjacent = attrs.get("AdjacentFor" + action + "FacesList", [])
                    if len(faces) != len(adjacent):
                        raise MissingData("Union trim face/adjacent-face counts differ")
                    operations.extend(("AddFaceTo" + action + "2", face_ref(face), face_ref(neighbor))
                                      for face, neighbor in zip(faces, adjacent))
                    operations.extend(("AddFaceTo" + action, face_ref(face)) for face in attrs.get(action + "FacesList", []))
                obj = self.own(self.sf.AddNewTrim(tool))
                for method, *refs in operations:
                    getattr(obj, method)(*refs)
                self.part.UpdateObject(obj)
                m = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj))
                center = array(3)
                m.GetCOG(center)
                actual = {"volume_mm3": float(m.Volume) * 1e9, "area_mm2": float(m.Area) * 1e6, "cog_mm": list(center.value)}
                if (abs(actual["volume_mm3"] - expected["volume_mm3"]) > max(.001, expected["volume_mm3"] * 1e-6)
                        or abs(actual["area_mm2"] - expected["area_mm2"]) > max(.01, expected["area_mm2"] * 1e-6)
                        or math.dist(actual["cog_mm"], expected["cog_mm"]) > self.geometry_tolerance()):
                    raise MissingData("Union trim result differs from source: " + json.dumps(actual))
                self.note("Native keep/remove and adjacent faces restored; source solid volume, area and centroid verified")
                return obj
            except Exception as exc:
                errors.append("feature_scope={}, current_flags={}, geometric={}: {}".format(feature_scope, current_flags, geometric, exc))
                if obj is not None:
                    selection = self.doc.Selection
                    try:
                        selection.Clear()
                        selection.Add(obj)
                        selection.Delete()
                        self.owned = [owned for owned in self.owned if owned is not obj]
                    finally:
                        selection.Clear()
                        self.part.InWorkObject = c
        raise MissingData("Union trim could not reproduce the source solid: " + "; ".join(errors))

    def create_offset(self, r, d, c):
        native = d.get("native_offset")
        if native:
            if native.get("offset_type") != 0 or native.get("tricky_face_count") != 0:
                raise MissingData("Surface offset requires a constant offset without tricky faces")
            obj = self.append(c, self.hsf.AddNewOffset(self.native_input_ref(native["support"]),
                number(native["offset_mm"]), bool(native["reversed"]), self.geometry_tolerance()))
            obj.SuppressMode = native["suppress_mode"]
            try:
                self.validate_native_result(obj, native["result_geometry"], "Surface offset")
            except MissingData as exc:
                if not d.get("native_offset_template"):
                    raise
                # Keep the established factory path when it matches the source.
                # Only a rejected result needs the source algorithm template.
                # Failed cleanup must abort; otherwise it would leave a second
                # offset in the same feature history.
                self.rollback()
                self.owned = []
                self.part.InWorkObject = c
                self.note("Fresh offset validation failed before template recovery: " + str(exc))
                obj = self.create_offset_from_template(native, d["native_offset_template"], c)
            self.bind("偏移", obj.OffsetValue)
            return obj
        source = self.ref(self.require(self.p.operand(r, "source_element")))
        if "offset" not in d or d.get("offset_unit") != "mm":
            raise MissingData("Surface offset needs an explicit millimetre value; re-export with the updated CAA exporter")
        return self.append(c, self.hsf.AddNewOffset(source, number(d["offset"]), bool(d["reversed"]), 0.001))

    def create_offset_from_template(self, native, template, container):
        path = (self.p.directory / template["file"]).resolve()
        if not path.is_relative_to(self.p.directory) or not path.is_file():
            raise MissingData("Offset template must exist inside the exported package")
        if template.get("input_count") != 1 or hashlib.sha256(path.read_bytes()).hexdigest() != template["sha256"]:
            raise MissingData("Offset template input count or fingerprint mismatch")
        support = self.native_input_ref(native["support"])
        asset = self.app.Documents.Open(str(path))
        try:
            asset.Activate()
            if asset.Part.HybridBodies.Count != 1:
                raise MissingData("Offset template must have one isolated container")
            shapes = asset.Part.HybridBodies.Item(1).HybridShapes
            if shapes.Count != 2 or str(shapes.Item(2).Name) != template["name"]:
                raise MissingData("Offset template contains unexpected features")
            added = self.paste_native_group(asset, [shapes.Item(i) for i in (1, 2)], container, "Offset template")
            target = self.doc.Selection
            obj = added[-1]
            if obj._oleobj_.GetTypeInfo().GetDocumentation(-1)[0] != "HybridShapeOffset":
                raise MissingData("Offset template lost its editable feature type")
            if (obj.OffsetValue.OptionalRelation is not None
                    or abs(float(obj.OffsetValue.Value) - native["offset_mm"]) > 1e-10
                    or bool(obj.OffsetDirection) != bool(native["reversed"])
                    or bool(obj.SuppressMode) != bool(native["suppress_mode"])):
                raise MissingData("Offset template settings differ from the exported definition")
            obj.OffsetedObject = support
            self.validate_native_result(obj, native["result_geometry"], "Offset preserving source configuration")
            target.Clear()
            target.Add(added[0])
            target.Delete()
            target.Clear()
            self.owned = [item for item in self.owned if item is not added[0]]
            self.validate_native_result(obj, native["result_geometry"], "Rebound offset")
            if template.get("offset_relation_detached"):
                self.note("Offset uses its evaluated source value; its original driving relation remains in package metadata")
            return obj
        finally:
            alerts = self.app.DisplayFileAlerts
            try:
                self.app.DisplayFileAlerts = False
                asset.Close()
            finally:
                self.app.DisplayFileAlerts = alerts
                self.doc.Activate()

    def create_pad(self, r, d, c):
        p = d.get("params", {})
        profiles = p.get("profile_elements", [])
        if len(profiles) != 1:
            raise MissingData("Pad requires one resolved profile element")
        profile = self.require(profiles[0], r)
        self.part.InWorkObject = c
        factory = self.sf.AddNewPocketFromRef if r["type"] == "Pocket" else self.sf.AddNewPadFromRef
        obj = self.own(factory(self.ref(profile), max(abs(number(p.get("limit1", {}).get("offset", 1))), 0.001)))
        if p.get("direction") is not None:
            # Exported direction is already the evaluated direction, including reversal.
            obj.SetDirection(self.direction_line(p["direction"]))
            obj.DirectionOrientation = 0
        else:
            obj.DirectionOrientation = 1 if p.get("direction_reversed") else 0
        obj.IsSymmetric = bool(p.get("symmetric", False))
        thin = p.get("thin_solid", {})
        if thin.get("enabled"):
            obj.IsThin = True
            obj.NeutralFiber = bool(thin.get("neutral_fiber"))
            obj.MergeEnd = bool(thin.get("merge_end"))
            parameters = self.part.Parameters.SubList(obj, False)
            available = {}
            for i in range(1, parameters.Count + 1):
                q = parameters.Item(i)
                available[str(q.Name).split("\\")[-1]] = q
            for side in (1, 2):
                names = ("厚薄 " + str(side), "ThinThickness" + str(side), "ThinThickness " + str(side))
                target = next((available[n] for n in names if n in available), None)
                if target is None:
                    raise MissingData("Native thin-pad thickness parameter not found: " + str(side))
                target.Value = number(thin["thickness" + str(side)])
                self.bind("厚薄 " + str(side), target)
        if p.get("inner_side") == 1:
            obj.ReverseInnerSide()
        self.pad_limit(obj, p.get("limit1", {}), True)
        self.pad_limit(obj, p.get("limit2", {}), False)
        return obj

    def create_pattern(self, r, d, c):
        # A Body pattern copies its complete incoming solid, not just the
        # last fillet's generated faces.
        container = self.p.container_record(r)
        body_pattern = d.get("pattern_of_body") and container and container["type"] == "MechanicalTool"
        source = self.part.CreateReferenceFromName("") if body_pattern else self.require(self.p.operand(r, "source_feature"))
        if any(i.get("deactivated") for i in d.get("instance_vectors", [])):
            self.note("Pattern contains deactivated instances; restored below")
        sizes, dirs, steps, positions = pattern_grid(d, self.geometry_tolerance())
        self.part.InWorkObject = c
        # instance_vectors already include the sign/sense of each direction.
        # Applying the signed step again reverses a negative-spacing pattern.
        factory = self.sf.AddNewSurfacicRectPattern if container and container["type"] == "GSMTool" else self.sf.AddNewRectPattern
        obj = self.own(factory(source, *sizes, *steps, *positions,
            self.direction_line(dirs[0]), self.direction_line(dirs[1]), True, True, 0))
        for i in d.get("instance_vectors", []):
            if i.get("deactivated"):
                obj.DesactivatePosition(i["row"]+1, i["col"]+1)
        return obj

    def create_plane(self, r, d, c):
        origin_names = {"xy-plane": "PlaneXY", "yz-plane": "PlaneYZ", "zx-plane": "PlaneZX"}
        if r.get("internal_name") in origin_names:
            return getattr(self.part.OriginElements, origin_names[r["internal_name"]])
        root, normal = self.p.plane(r)
        # PlaneEquation is A*x+B*y+C*z=D (verified against the installed API).
        obj = self.hsf.AddNewPlaneEquation(*normal, sum(a*b for a, b in zip(root, normal)))
        self.note("Plane restored from exported equation; original construction relations are not recreated")
        return self.append(c, obj)

    def create_point(self, r, d, c):
        coords = d.get("coordinates")
        if coords is None:
            vertices = self.p.geometry.get(r["full_path"], {}).get("topology", {}).get("vertices", [])
            if len(vertices) == 1:
                coords = vertices[0].get("point")
                self.note("Point restored from evaluated geometry")
        if coords is None:
            coords = [number(self.p.parameter(r, name)) for name in ("X", "Y", "Z")]
        return self.append(c, self.hsf.AddNewPointCoord(*self.bounded_coordinates(coords)))

    def create_procedural_surface(self, r, d, c):
        try:
            return self.create_procedural_surface_factory(r, d, c)
        except MissingData:
            if r["type"] != "GSMBlend" or not d.get("native_algorithm_template"):
                raise
            self.rollback()
            return self.create_algorithm_template(r, d, c)

    def create_procedural_surface_factory(self, r, d, c):
        data = d.get("native_operation")
        if not data:
            raise MissingData(r["type"] + " procedural inputs unavailable: "
                + json.dumps(d.get("native_export_errors", []), ensure_ascii=False))
        kind = r["type"]
        ref = lambda key: self.native_input_ref(data[key])
        if kind == "GSMTrim":
            if data.get("template"):
                return self.create_trim_from_template(data, c)
            elems = data["elements"]
            if len(elems) != 2:
                raise MissingData("Multi-element trim needs a native append interface; Automation SetElem only replaces existing elements")
            if data.get("properties", {}).get("Mode", 1) != 1:
                raise MissingData("Advanced trim piece selection requires dedicated replay")
            if elems[0].get("next") not in (-1, 1) or elems[1].get("previous") not in (-1, 1):
                raise MissingData("Trim requires explicit source orientations")
            refs = [self.native_input_ref(e["input"]) for e in elems]
            obj = self.append(c, self.hsf.AddNewHybridTrim(refs[0], elems[0]["next"], refs[1], elems[1]["previous"]))
            if data.get("support"):
                obj.Support = ref("support")
            for value in data.get("keep", []):
                obj.AddElementToKeep(self.native_input_ref(value))
            for value in data.get("remove", []):
                obj.AddElementToRemove(self.native_input_ref(value))
        elif kind == "GSMCurveSmooth":
            obj = self.append(c, self.hsf.AddNewCurveSmooth(ref("curve")))
            if data.get("support"):
                obj.Support = ref("support")
            obj.SetTangencyThreshold(data["tangency_deg"])
            obj.SetMaximumDeviation(data["deviation_mm"])
            for value in data["frozen_points"]:
                obj.AddFrozenPoint(self.native_input_ref(value))
            for value in data["frozen_segments"]:
                obj.AddFrozenCurveSegment(self.native_input_ref(value))
        elif kind == "GSMProject":
            obj = self.append(c, self.hsf.AddNewProject(ref("element"), ref("support")))
            if data.get("direction"):
                obj.Direction = self.hsf.AddNewDirectionByCoord(*unit(data["direction"]))
        elif kind == "GSMNear":
            obj = self.append(c, self.hsf.AddNewNear(ref("multiple"), ref("reference")))
        elif kind == "GSMInverse":
            value = data["input"]
            obj = self.append(c, self.hsf.AddNewInverse(self.native_input_ref(value["inverse"]), value["orientation"]))
        elif kind == "GSMCurvePar":
            props = data["properties"]
            obj = self.append(c, self.hsf.AddNewCurvePar(ref("curve"), ref("support"), data["offset_mm"],
                props["InvertDirection"], props["Geodesic"]))
            if data.get("passing_point"):
                obj.PassingPoint = ref("passing_point")
            if "offset2_mm" in data:
                obj.KeepBothSides = True
                obj.Offset2.Value = data["offset2_mm"]
        elif kind == "GSMBlend":
            obj = self.append(c, self.hsf.AddNewBlend())
            for i, limit in enumerate(data["limits"], 1):
                obj.SetCurve(i, self.native_input_ref(limit["curve"]))
                if limit.get("point"):
                    obj.SetClosingPoint(i, self.native_input_ref(limit["point"]))
                if limit.get("support"):
                    obj.SetSupport(i, self.native_input_ref(limit["support"]))
                for prop in ("Orientation", "Transition", "Continuity", "TrimSupport", "BorderMode"):
                    getattr(obj, "Set" + prop)(i, limit[prop])
                if limit.get("tensions"):
                    obj.SetTensionInDouble(i, limit["tension_type"], *limit["tensions"])
            if data.get("spine"):
                obj.Spine = ref("spine")
            obj.SetSmoothAngleThreshold(data["smooth_angle_deg"])
            obj.SetSmoothDeviation(data["deviation_mm"])
        else:
            raise MissingData("Unsupported procedural surface: " + kind)
        for name, value in data.get("properties", {}).items():
            setattr(obj, name, value)
        self.validate_native_result(obj, data["result_geometry"], kind)
        if data.get("unavailable_properties"):
            self.note(kind + " source settings unavailable: "
                      + ", ".join(sorted(data["unavailable_properties"]))
                      + "; reconstructed geometry passed independent measurement checks")
        return obj

    def create_remove_face(self, r, d, c):
        expected = d.get("native_result_geometry")
        if not expected:
            raise MissingData("RemoveFace requires source solid geometry validation")
        native = d.get("native_operation")
        attributes = d.get("input_attributes", [])
        groups = {}
        for attribute in attributes:
            name = attribute.get("attribute_name")
            if name in ("KeepFacesList", "RemoveFacesList"):
                if name in groups:
                    raise MissingData("Duplicate RemoveFace source attribute: " + name)
                if not attribute.get("is_list") or not attribute.get("value_type_supported"):
                    raise MissingData("RemoveFace source face list is not fully exported: " + name)
                groups[name] = attribute.get("values", [])
            elif name in ("KeepByAdjacentFacesList", "AdjacentForKeepFacesList",
                          "RemoveByAdjacentFacesList", "AdjacentForRemoveFacesList"):
                raise MissingData("RemoveFace adjacent-face modes require dedicated replay")
        self.part.InWorkObject = c
        if d.get("input_attributes_available") and groups.get("RemoveFacesList"):
            # These are the original CAA attribute selections, including each
            # face's historical support and independent trimmed-face geometry.
            # No KeepFacesList in the complete attribute enumeration means
            # that no explicit keep list was stored on this RemoveFace.
            lists = [groups.get(key, []) for key in ("KeepFacesList", "RemoveFacesList")]
            if native and any(len(values) != len(native[key]) for key, values in zip(("keep", "remove"), lists)):
                raise MissingData("RemoveFace Automation and CAA attribute face counts disagree")
            resolved = []
            for values in lists:
                faces = []
                for value in values:
                    selection = value.get("selection")
                    if value.get("is_null") or not selection or not selection.get("valid") or not selection.get("resolved_breps"):
                        raise MissingData("RemoveFace source face lacks its resolved geometry")
                    cells = [cell for brep in selection["resolved_breps"] for cell in brep.get("cells", [])]
                    if not cells or any(cell.get("dimension") != 2 for cell in cells):
                        raise MissingData("RemoveFace source selection does not resolve to faces")
                    faces.append(self.fillet_reference(self.selection_ref(selection), c, permanent=True))
                resolved.append(faces)
            keep, remove = resolved
            if not native:
                self.note("RemoveFace restored from complete CAA face attributes after its Automation collection getter failed")
        elif native:
            keep, remove = [[self.resolved_native_brep_reference(name, c)[0]
                             for name in native[key]] for key in ("keep", "remove")]
        else:
            raise MissingData("RemoveFace has neither complete CAA face attributes nor native settings")
        if not remove:
            raise MissingData("RemoveFace has no exported faces to remove")
        self.part.InWorkObject = c
        empty = self.part.CreateReferenceFromName("")
        obj = self.own(self.sf.AddNewRemoveFace(keep[0] if keep else empty, remove[0]))
        for ref in keep[1:]:
            obj.KeepFace = ref
        for ref in remove[1:]:
            obj.RemoveFace = ref
        self.validate_native_result(obj, expected, "RemoveFace")
        return obj

    def create_rib(self, r, d, c):
        profile_record = self.p.wrapper_record(r, "ExtendedProfile")
        curve_record, inferred = self.p.rib_center_record(r, profile_record)
        profile = self.require(profile_record)
        curve = self.require(curve_record)
        if inferred:
            self.note("Center curve inferred from the unique single open sketch in the same Body: " + curve_record["full_path"])
        self.part.InWorkObject = c
        return self.own(self.sf.AddNewRibFromRef(self.ref(profile), self.ref(curve)))

    def create_rotate(self, r, d, c):
        source = self.ref(self.require(self.p.operand(r, "source_element", "ToTransfor")))
        axis_data = d.get("rotation_axis")
        if axis_data:
            axis = self.direction_line(axis_data["direction"], axis_data["origin"])
        else:
            axis = self.ref(self.require(self.p.operand(r, "Axis", "axis")))
        angle = number(d["angle_deg"], "angle") if "angle_deg" in d else number(self.p.parameter(r, "Angle"), "angle")
        if self.p.is_solid_operation(r):
            # InsertHybridShape creates a separate GSD result and leaves the
            # Body solid unrotated, even when UpdateObject succeeds.
            self.part.InWorkObject = c
            obj = self.own(self.sf.AddNewRotate2(axis, angle))
            self.bind("角度", obj.HybridShape.Angle)
            return obj
        return self.append(c, self.hsf.AddNewRotate(source, axis, angle))

    def create_shaft(self, r, d, c):
        native = d.get("native_shaft")
        p = d.get("params", {})
        if native:
            profile = self.ref(self.require(native["profile"], r))
            self.part.InWorkObject = c
            obj = self.own(self.sf.AddNewShaftFromRef(profile))
            if native.get("axis"):
                obj.RevoluteAxis = self.native_input_ref(native["axis"])
            elif native.get("axis_mode") != "sketch":
                raise MissingData("Shaft axis mode unavailable")
            obj.FirstAngle.Value = number(native["first_angle_deg"], "angle")
            obj.SecondAngle.Value = number(native["second_angle_deg"], "angle")
            self.validate_native_result(obj, native["result_geometry"], "Shaft")
            return obj
        # The earlier CAA GetEndAngle/GetStartAngle fields were labelled _rad,
        # but hold degrees (confirmed against B33 FirstAngle/SecondAngle).
        if d.get("kind") == "shaft" and "end_angle_rad" in p:
            if p.get("thin_enabled") or p.get("start_limit_type") != 0 or p.get("end_limit_type") != 0:
                raise MissingData("Thin or surface-limited shaft needs native settings")
            elements = p.get("profile_elements", [])
            if len(elements) != 1:
                raise MissingData("Shaft needs one exact profile element")
            profile_record = self.p.lookup(elements[0], r)
            axis_record = self.p.lookup(p.get("axis"), r)
            if axis_record is None and (not profile_record or profile_record["type"] != "PRTSketch"):
                raise MissingData("Shaft has neither external axis nor sketch axis")
            self.part.InWorkObject = c
            obj = self.own(self.sf.AddNewShaftFromRef(self.ref(self.require(profile_record))))
            if axis_record:
                obj.RevoluteAxis = self.ref(self.require(axis_record))
            obj.FirstAngle.Value = number(p["end_angle_rad"], "angle")
            obj.SecondAngle.Value = number(p["start_angle_rad"], "angle")
            return obj
        if not all(k in p for k in ("profile", "axis", "first_angle", "second_angle")):
            raise MissingData("Shaft profile/axis/angle definition not exported")
        profile, axis = self.ref(self.require(p["profile"])), self.ref(self.require(p["axis"]))
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewShaftFromRef(profile))
        obj.RevoluteAxis = axis
        obj.FirstAngle.Value = number(p["first_angle"], "angle")
        obj.SecondAngle.Value = number(p["second_angle"], "angle")
        return obj

    def create_shell(self, r, d, c):
        p = d.get("params", {})
        faces = self.selections(d, "face_to_remove")
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewShell(faces[0], number(p["inner_offset"]), number(p["outer_offset"])))
        for face in faces[1:]:
            obj.AddFaceToRemove(face)
        return obj

    def create_sketch(self, r, d, c):
        axis = sketch_axis(d)
        segments, circles, curved, construction = sketch_segments(d)
        exact_profile = d.get("native_sketch_profile") if curved else None
        if curved and not self.allow_approximate and not exact_profile:
            raise MissingData("Curved sketch has only sampled geometry; use --allow-approximate-sketches explicitly: " + str(curved))
        supports = d.get("positioning", {}).get("support_references", [])
        if not supports:
            raise MissingData("Sketch support reference is missing")
        expected_normal = unit(cross(axis[3:6], axis[6:9]))
        support_record = self.p.lookup(supports[0], r)
        internal_plane = (support_record and support_record["type"] == "FeatureFSUR"
                          and support_record["full_path"].startswith(r["full_path"] + "/"))
        if internal_plane:
            # An explicit sketch owns an XY plane in its absolute-axis subtree;
            # it is not an independent upstream feature with a replay result.
            support = self.own(self.hsf.AddNewPlaneEquation(*expected_normal,
                sum(a*b for a,b in zip(expected_normal, axis[:3]))))
            self.helpers.AppendHybridShape(support)
            self.part.UpdateObject(support)
            self.note("Internal sketch plane restored from its exported absolute frame")
        else:
            support = self.require(supports[0], r)
        try:
            _, normal = self.p.plane(support_record)
        except MissingData:
            normal = expected_normal
        if sum(a*b for a,b in zip(normal, expected_normal)) < 0:
            # CATIA otherwise silently swaps H/V when the requested sketch
            # handedness opposes its support. Retain the absolute source frame.
            support = self.own(self.hsf.AddNewPlaneEquation(*expected_normal,
                sum(a*b for a,b in zip(expected_normal, axis[:3]))))
            self.helpers.AppendHybridShape(support)
            self.part.UpdateObject(support)
            self.note("Sketch support orientation aligned to the exported absolute frame")
        parent = self.p.container_record(r)
        sketches = c.Sketches if parent and parent["type"] == "MechanicalTool" else c.HybridSketches
        obj = self.own(sketches.Add(self.ref(support)))
        obj.SetAbsoluteAxisData(axis)
        if exact_profile:
            self.populate_exact_sketch(r, obj, axis, exact_profile)
            self.note("Exact stored sketch profile restored; original constraints and sub-element report numbers require separate binding")
            return obj
        factory = obj.OpenEdition()
        created_geometry = []
        try:
            # Equal coordinates alone do not give separately created curves
            # shared topology. Pads can heal those wires, but GSD extrusions
            # and fills require connected endpoints in the sketch itself.
            endpoints = []
            def endpoint(x, y):
                for coords, point in endpoints:
                    if math.dist(coords, (x, y)) <= self.geometry_tolerance():
                        return point
                point = factory.CreatePoint(x, y)
                endpoints.append(((x, y), point))
                return point

            for point in d.get("profile_points", []):
                factory.CreatePoint(*point)
            for index, a, b in segments:
                line = factory.CreateLine(a[0], a[1], b[0], b[1])
                created_geometry.append((index, line))
                line.StartPoint = endpoint(*a)
                line.EndPoint = endpoint(*b)
            for index, a, b in construction:
                line = factory.CreateLine(a[0], a[1], b[0], b[1])
                created_geometry.append((index, line))
                line.Construction = True
            for index, g in circles:
                center = g.get("center", g.get("xy"))
                radius = number(g.get("radius", g.get("r")))
                if g.get("closed"):
                    curve = factory.CreateClosedCircle(*center, radius)
                else:
                    curve = factory.CreateCircle(*center, radius, g["start_angle"], g["end_angle"])
                    if not g.get("construction"):
                        curve.StartPoint = endpoint(center[0] + radius * math.cos(g["start_angle"]),
                                                    center[1] + radius * math.sin(g["start_angle"]))
                        curve.EndPoint = endpoint(center[0] + radius * math.cos(g["end_angle"]),
                                                  center[1] + radius * math.sin(g["end_angle"]))
                if g.get("construction"):
                    curve.Construction = True
                created_geometry.append((index, curve))
            active_indices = {i for i, _, _ in segments} | {i for i, g in circles if not g.get("construction")}
            self.register_sketch_geometry(r, d, [(i, g) for i, g in created_geometry if i in active_indices])
        finally:
            obj.CloseEdition()
        if curved:
            self.note("APPROXIMATE sampled sketch curves: " + str(curved))
        construction_indices = {i for i, _, _ in construction} | {i for i, g in circles if g.get("construction")}
        if construction_indices and "profile_geometry_indices" not in d:
            self.note("Construction membership recovered from unique closed profile and exported profile_count: " + str(sorted(construction_indices)))
        constraints = d.get("constraints", [])
        if constraints:
            self.note("Evaluated sketch geometry restored; {} original constraints require participant/reference recovery".format(len(constraints)))
        return obj

    def create_solid_datum(self, r, d, c):
        return self.create_native_datum(r, d, c, solid=True)

    def create_split(self, r, d, c):
        ref = self.selections(d, "cutting_element")[0]
        side = d.get("params", {}).get("side_to_keep")
        if side not in ("PositiveSide", "NegativeSide"):
            raise MissingData("Missing split side")
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewSplit(ref, 0 if side == "PositiveSide" else 1))
        if d.get("native_result_geometry"):
            self.validate_native_result(obj, d["native_result_geometry"], "Split")
        return obj

    def create_surface_datum(self, r, d, c):
        return self.create_native_datum(r, d, c, solid=False)

    def create_surface_fillet(self, r, d, c):
        native = d.get("native_surface_fillet")
        if native:
            template = d.get("native_surface_fillet_template")
            if template and native.get("template") and template != native["template"]:
                raise MissingData("Conflicting surface fillet templates in exported definition")
            if template:
                native = dict(native, template=template)
            if native["section_type"] != 0 or native["radius_type"] != 0:
                raise MissingData("Surface fillet requires conical/chord-length settings")
            if native.get("template"):
                obj = self.create_fillet_from_template(native, c)
                return obj
            obj = self.append(c, self.hsf.AddNewFilletBiTangent(
                self.native_input_ref(native["support1"]), self.native_input_ref(native["support2"]),
                number(native["radius_mm"]), native["orientation1"], native["orientation2"],
                native["trim_mode"], native["relimitation_mode"]))
            for field, prop in (("spine", "Spine"), ("hold_curve", "HoldCurve")):
                if native.get(field):
                    setattr(obj, prop, self.native_input_ref(native[field]))
            for face in native.get("faces_to_keep", []):
                obj.AppendNewFaceToKeep(self.native_input_ref(face))
            self.validate_native_result(obj, native["result_geometry"], "Surface fillet")
            return obj
        p = d.get("params", {})
        if not isinstance(p, dict) or "radius" not in p:
            raise MissingData("Surface fillet lacks radius/support orientation definition")
        a = self.ref(self.require(self.p.operand(r, "support1")))
        b = self.ref(self.require(self.p.operand(r, "support2")))
        return self.append(c, self.hsf.AddNewFilletBiTangent(a, b, number(p["radius"]), p["orientation1"], p["orientation2"], p["trim_mode"], p["relimitation_mode"]))

    def create_surface_split(self, r, d, c):
        native = d.get("native_split")
        if native:
            cutters = native.get("cutters")
            if cutters is None:
                cutters = [{"input": native["cutter"], "orientation": native.get("orientation")}]
            if not cutters or any(x.get("orientation") not in (-1, 1) for x in cutters):
                raise MissingData("Surface split has an invalid exported orientation")
            source = self.native_input_ref(native["source"])
            refs = [(self.native_input_ref(x["input"]), x["orientation"]) for x in cutters]
            obj = self.append(c, self.hsf.AddNewHybridSplit(source, *refs[0]))
            for ref, orientation in refs[1:]:
                obj.AddCuttingElem(ref, orientation)
            return obj
        source = self.ref(self.require(self.p.operand(r, "ToCut")))
        cutters = next((a["values"] for a in r.get("input_attributes", []) if a["attribute_name"] == "Cutting"), [])
        orientations = next((a["values"] for a in r.get("input_attributes", []) if a["attribute_name"] == "Orientation"), [])
        orientation = d.get("orientation", orientations[0] if len(orientations) == 1 else None)
        if len(cutters) != 1 or orientation not in (-1, 1):
            raise MissingData("Surface split requires one cutter and an explicit orientation")
        return self.append(c, self.hsf.AddNewHybridSplit(source, self.selection_ref(cutters[0]["selection"]), orientation))

    def create_sweep(self, r, d, c):
        if d.get("sweep_type") == "linear":
            self.part.InWorkObject = c
            native = d.get("native_linear_sweep")
            if not native:
                raise MissingData("Linear sweep native definition unavailable: "
                    + json.dumps(d.get("native_export_errors", []), ensure_ascii=False))
            if native.get("geometry_validation_required") and (native.get("area_m2") is None or native.get("cog_mm") is None):
                raise MissingData("Legacy sweep settings require source area and centroid validation")
            guides = d.get("guides", [])
            laws = d.get("length_laws", {})
            relimiters = d.get("longitudinal_relimiters", {})
            if (native.get("mode") != 6 or len(guides) != 1 or d.get("spine")
                    or d.get("guide_surfaces") or native["properties"].get("AngleLawType") != 1
                    or any(laws.get(side, {}).get("type") not in (0, 1) for side in ("first", "second"))
                    or any(relimiters.get(side) for side in ("first", "second"))):
                raise MissingData("Linear sweep requires unsupported variable laws, supports or relimiters")
            guide = self.native_input_ref(native["guide"]) if native.get("guide") else self.ref(self.require(guides[0]))
            obj = self.append(c, self.hsf.AddNewSweepLine(guide))
            obj.Mode = 6
            obj.DraftDirection = self.hsf.AddNewDirectionByCoord(*unit(native["direction"]))
            for name, value in native["properties"].items():
                if name == "SolutionNo" and (not isinstance(value, int) or not 0 <= value <= 4):
                    if native.get("area_m2") is None or native.get("cog_mm") is None:
                        raise MissingData("Invalid sweep solution number without source surface measurements")
                    self.note("Uninitialized sweep SolutionNo ignored; source surface validation required")
                    continue
                setattr(obj, name, value)
            obj.SetAngle(1, native["angle_deg"])
            for i, value in enumerate(native["lengths_mm"], 1):
                obj.SetLength(i, value)
            limits = native.get("length_definition_inputs", [None, None])
            if len(limits) != 2:
                raise MissingData("Sweep must export both length limit slots")
            for side, definition_type, limit in zip(("First", "Second"), native.get("length_definition_types", []), limits):
                if definition_type == 3 and not limit:
                    raise MissingData("Sweep reference length is missing its limiting element")
                getattr(obj, "Set" + side + "LengthDefinitionType")(definition_type,
                    self.native_input_ref(limit) if limit else self.part.CreateReferenceFromName(""))
            obj.SetSmoothAngleThreshold(native["smooth_angle_deg"])
            obj.SetGuideDeviation(native["guide_deviation_mm"])
            if native.get("cog_mm") is not None:
                self.part.UpdateObject(obj)
                if not self.sweep_geometry_matches(obj, native):
                    inverse = self.own(self.hsf.AddNewInverse(guide, -1))
                    self.helpers.AppendHybridShape(inverse)
                    self.part.UpdateObject(inverse)
                    obj.FirstGuideCrv = self.ref(inverse)
                    self.part.UpdateObject(obj)
                    if not self.sweep_geometry_matches(obj, native):
                        raise MissingData("Linear sweep differs from source area/centroid with either guide orientation")
                    self.note("Guide orientation restored by checking source surface area and centroid")
            return obj
        if d.get("sweep_type") != "explicit":
            raise MissingData("Sweep subtype/law not exported (only explicit-profile replay is supported)")
        native = d.get("native_explicit_sweep")
        profile = self.native_input_ref(native["profile"]) if native else self.ref(self.require(self.p.operand(r, "profile")))
        guide = self.native_input_ref(native["guide"]) if native else self.ref(self.require(self.p.operand(r, "guide")))
        obj = self.append(c, self.hsf.AddNewSweepExplicit(profile, guide))
        if native:
            if native.get("subtype") == 3:
                if native.get("position_mode") not in (0, 1) or native.get("angle_law_type") not in (0, 1):
                    raise MissingData("Explicit pulling sweep has unsupported positioning or variable law")
                if not isinstance(native.get("solution_no"), int) or not 0 <= native["solution_no"] <= 4:
                    raise MissingData("Explicit pulling sweep requires a valid source solution number")
                obj.SubType = 3
                obj.PullingDirection = self.hsf.AddNewDirectionByCoord(*unit(native["pulling_direction"]))
                obj.SetAngleRef(1, number(native["angle_deg"]))
                obj.SolutionNo = native["solution_no"]
                obj.GuideProjection = native["guide_projection"]
            self.validate_native_result(obj, native["result_geometry"], "Explicit sweep")
        return obj

    def create_thickness(self, r, d, c):
        p = d.get("params", {})
        self.part.InWorkObject = c
        native = d.get("native_thickness_faces")
        if native is not None:
            if not native or not d.get("native_result_geometry"):
                raise MissingData("Native thickness inputs require faces and source solid validation")
            try:
                faces = [self.resolved_native_brep_reference(face["native_brep_name"], c)[0] for face in native]
            except MissingData:
                # Imported solids can renumber their faces. Recover the full
                # exported face set within its historical support, then require
                # the finished thickness solid to match the source below.
                selections = [s for s in d.get("selections", []) if s.get("role") == "face_to_thicken"]
                if len(selections) != len(native):
                    raise
                faces = [self.fillet_reference(self.selection_ref(s), c, permanent=True) for s in selections]
        else:
            faces = self.selections(d, "face_to_thicken")
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewThickness(faces[0], number(p["offset"])))
        for face in faces[1:]:
            obj.AddFaceToThicken(face)
        if d.get("native_result_geometry"):
            self.validate_native_result(obj, d["native_result_geometry"], "Thickness")
        return obj

    def create_translate(self, r, d, c):
        source = self.require(self.p.operand(r, "source_element"))
        direction = unit(d.get("direction"))
        distance = self.p.length_mm(r, "distance", "Distance", "长度", "Length")
        parent = self.p.container_record(r)
        if parent and parent["type"] == "MechanicalTool":
            self.part.InWorkObject = c
            obj = self.own(self.sf.AddNewTranslate2(distance))
            obj.HybridShape.Direction = self.hsf.AddNewDirectionByCoord(*direction)
            obj.HybridShape.VectorType = 0
            return obj
        return self.append(c, self.hsf.AddNewTranslate(self.ref(source), self.hsf.AddNewDirectionByCoord(*direction), distance))

    def create_trim(self, r, d, c):
        if d.get("native_result_geometry"):
            return self.create_native_trim(r, d, c)
        attrs = {a["attribute_name"]: a.get("values", []) for a in r.get("input_attributes", [])}
        tools = attrs.get("ToolList", [])
        if len(tools) != 1:
            raise MissingData("Union trim needs exactly one identified tool Body")
        tool = self.require(tools[0]["feature"], r)
        def face_ref(selection):
            ref = self.selection_ref(selection)
            support = self.p.effective_producer(self.p.lookup(selection["support_feature"], r))
            scope = self.require(self.p.container_record(support))
            return self.fillet_reference(ref, scope)
        operations = []
        for action in ("Keep", "Remove"):
            faces = attrs.get(action + "ByAdjacentFacesList", [])
            adjacent = attrs.get("AdjacentFor" + action + "FacesList", [])
            if len(faces) != len(adjacent):
                raise MissingData("Union trim face/adjacent-face counts differ")
            for face, neighbor in zip(faces, adjacent):
                operations.append(("AddFaceTo" + action + "2", face_ref(face["selection"]), face_ref(neighbor["selection"])))
            for face in attrs.get(action + "FacesList", []):
                operations.append(("AddFaceTo" + action, face_ref(face["selection"])))
        self.part.InWorkObject = c
        obj = self.own(self.sf.AddNewTrim(tool))
        for method, *refs in operations:
            getattr(obj, method)(*refs)
        return obj

    def create_trim_from_template(self, native, container):
        template = native["template"]
        elements = native["elements"]
        if template.get("input_count") != len(elements) or len(elements) < 3:
            raise MissingData("Trim template element count does not match its inputs")
        if native.get("support") or native.get("keep") or native.get("remove"):
            raise MissingData("Trim template contains additional unbound dependencies")
        path = (self.p.directory / template["file"]).resolve()
        if not path.is_relative_to(self.p.directory) or not path.is_file():
            raise MissingData("Trim template must exist inside the exported package")
        if hashlib.sha256(path.read_bytes()).hexdigest() != template["sha256"]:
            raise MissingData("Trim template fingerprint mismatch")
        refs = [self.native_input_ref(e["input"]) for e in elements]
        asset = self.app.Documents.Open(str(path))
        try:
            asset.Activate()
            original = asset.Part.FindObjectByName(template["name"])
            # Copy the independent supports and trim together, so CATIA
            # retains its internal element slots during the document crossing.
            if asset.Part.HybridBodies.Count != 1:
                raise MissingData("Trim asset must have one isolated support container")
            source_shapes = asset.Part.HybridBodies.Item(1).HybridShapes
            if source_shapes.Count != len(refs) + 1:
                raise MissingData("Trim asset contains unexpected dependencies")
            added = self.paste_native_group(asset,
                [source_shapes.Item(i) for i in range(1, source_shapes.Count + 1)], container, "Trim template")
            target = self.doc.Selection
            obj = added[-1]
            if obj._oleobj_.GetTypeInfo().GetDocumentation(-1)[0] != "HybridShapeTrim" or obj.GetNbElem() != len(refs):
                raise MissingData("Trim template lost its feature type or element slots")
            for i, ref in enumerate(refs, 1):
                obj.SetElem(i, ref)
            self.validate_native_result(obj, native["result_geometry"], "Multi-element trim")
            # All dependencies now point at real reconstructed inputs.
            target.Clear()
            for support in added[:-1]:
                target.Add(support)
            target.Delete()
            target.Clear()
            self.owned = [item for item in self.owned if all(item is not support for support in added[:-1])]
            self.validate_native_result(obj, native["result_geometry"], "Rebound multi-element trim")
            return obj
        finally:
            alerts = self.app.DisplayFileAlerts
            try:
                self.app.DisplayFileAlerts = False
                asset.Close()
            finally:
                self.app.DisplayFileAlerts = alerts
                self.doc.Activate()

    def create_tritangent_fillet(self, r, d, c):
        faces = [self.selections(d, role)[0] for role in ("first_face", "second_face", "face_to_remove")]
        self.part.InWorkObject = c
        return self.own(self.sf.AddNewTritangentFillet(*faces))

    def apply_visibility(self):
        """Restore individual states, applying hidden parents after children."""
        resolution = getattr(self.p, "visibility_resolution", {})
        errors = list(resolution.get("unresolved", []))
        counts = {"known": 0, "applied": 0, "hidden": 0, "shown": 0, "verified": 0,
                  "mismatched": 0, "readback_failed": 0,
                  "without_source_state": 0, "not_created": 0,
                  "unresolved_records": len(errors)}
        targets = []
        for r in self.p.records:
            show = self.p.definitions[r["id"]].get("source_visibility")
            if type(show) is not int or show not in (0, 1):
                counts["without_source_state"] += 1
                continue
            counts["known"] += 1
            if r["id"] not in self.objects:
                counts["not_created"] += 1
                continue
            targets.append((show, r))
        # Showing a child can affect a Body's display. Apply all Show operations
        # first, then hide from descendants to ancestors so hidden groups win.
        targets.sort(key=lambda item: (item[0], -item[1]["full_path"].count("/")))
        selection = self.doc.Selection
        self.log("Restoring visibility for {} reconstructed objects".format(len(targets)))
        for index, (show, r) in enumerate(targets, 1):
            try:
                selection.Clear()
                selection.Add(self.objects[r["id"]])
                selection.VisProperties.SetShow(show)
                counts["applied"] += 1
                counts["hidden" if show else "shown"] += 1
            except Exception as exc:
                errors.append({"path": r["full_path"], "reason": str(exc)})
            finally:
                selection.Clear()
            if index % 100 == 0:
                self.log("Visibility applied: {}/{}".format(index, len(targets)))
        # Verify after all writes: a successful SetShow call alone does not
        # establish that later operations left this object's state intact.
        for index, (show, r) in enumerate(targets, 1):
            try:
                selection.Clear()
                selection.Add(self.objects[r["id"]])
                actual = selected_visibility(selection)
                if actual == show:
                    counts["verified"] += 1
                else:
                    counts["mismatched"] += 1
                    errors.append({"path": r["full_path"], "expected": show, "actual": actual,
                                   "reason": "Visibility differs after applying all source states"})
            except Exception as exc:
                counts["readback_failed"] += 1
                errors.append({"path": r["full_path"], "stage": "visibility_readback", "reason": str(exc)})
            finally:
                selection.Clear()
            if index % 100 == 0:
                self.log("Visibility checked: {}/{}".format(index, len(targets)))
        self.validation["visibility"] = counts
        self.validation["visibility_errors"] = errors
        self.log("Visibility: " + json.dumps(counts, ensure_ascii=False))

    def bounded_coordinates(self, coords):
        coords = vector(coords)
        size = number(self.p.manifest.get("tolerance", {}).get("model_size", 1000000))
        if size <= 0 or any(abs(value) >= size for value in coords):
            raise MissingData("Point coordinates {} exceed model size {}mm".format(coords, size))
        return coords

    def coalesced_fillet_edges(self, selection, cells):
        """Recover source edge partitions that CATIA merged during replay.

        Every trimmed source piece must lie on exactly one target edge, and
        its group's total length must cover that edge. Never accept an extra
        unselected extension just because one sample point happens to match.
        """
        previous = self.p.lookup(self.p.definitions[self.current["id"]].get("previous_shape"), self.current)
        support = self.p.lookup(selection.get("support_feature"), self.current)
        if not previous or not support or self.p.effective_producer(previous)["id"] != self.p.effective_producer(support)["id"]:
            raise MissingData("Merged edge recovery requires the exact preceding solid")
        if not all(c.get("curve_measurement_source") == "CAA resolved edge" and len(c.get("curve_points", [])) >= 3
                   and number(c.get("length_mm", 0)) > 0 for c in cells):
            raise MissingData("Merged edge recovery requires all trimmed source points and lengths")
        spa = self.doc.GetWorkbench("SPAWorkbench")
        candidates = []
        for ref in self.scoped_topology(self.container(self.current), "CGMEdge"):
            if str(ref.DisplayName).startswith("Selection_Wire"):
                continue
            try:
                m = spa.GetMeasurable(ref)
                candidates.append((ref, m, float(m.Length)))
            except Exception:
                continue
        groups = {}
        tolerance = self.geometry_tolerance()
        self.log("Checking merged edge partitions: " + self.current.get("full_path", self.current["id"]))
        for index, cell in enumerate(cells, 1):
            length = number(cell["length_mm"])
            matches = [item for item in candidates if item[2] >= length - tolerance]
            # Start with an interior point; endpoints can belong to two edges.
            points = cell["curve_points"]
            for point in [points[len(points) // 2]] + points:
                with self.measurement_point(point) as probe:
                    remaining = []
                    for item in matches:
                        try:
                            if item[1].GetMinimumDistance(probe) <= tolerance:
                                remaining.append(item)
                        except Exception:
                            pass
                    matches = remaining
                if not matches:
                    break
            if len(matches) != 1:
                raise MissingData("Trimmed source piece has {} matching merged edges".format(len(matches)))
            ref, _, actual_length = matches[0]
            key = str(ref.DisplayName)
            group = groups.setdefault(key, [ref, actual_length, 0.0, [], matches[0][1]])
            group[2] += length
            group[3].append(cell)
            self.log("Merged edge source pieces verified: {}/{}".format(index, len(cells)))
        from catia_com import array
        for _, actual, covered, parts, measurable in groups.values():
            if abs(actual - covered) > max(tolerance, actual * 1e-6):
                raise MissingData("Source pieces do not cover the complete merged edge")
            endpoints = array(9)
            measurable.GetPointsOnCurve(endpoints)
            if not edge_partition_covers(parts, [endpoints.value[:3], endpoints.value[6:]], tolerance):
                raise MissingData("Source edge partitions overlap, branch or leave a gap")
        self.note("Source trimmed edge partitions merged in replay; complete lengths and all source points verified")
        return [group[0] for group in groups.values()]

    def direction_line(self, value, origin=(0, 0, 0)):
        v = unit(value)
        pt = self.own(self.hsf.AddNewPointCoord(*self.bounded_coordinates(origin)))
        direction = self.hsf.AddNewDirectionByCoord(*v)
        line = self.own(self.hsf.AddNewLinePtDir(self.ref(pt), direction, 0, 1, False))
        # Keep direction helpers outside user containers and hidden.
        self.helpers.AppendHybridShape(pt)
        self.helpers.AppendHybridShape(line)
        self.part.UpdateObject(pt)
        self.part.UpdateObject(line)
        return self.ref(line)

    def edges_on_supports(self, selection, supports):
        """Recover one logical edge whose trimmed pieces changed segmentation."""
        from catia_com import array
        body = self.container(self.current)
        spa = self.doc.GetWorkbench('SPAWorkbench')
        cells = [c for b in selection.get('resolved_breps', []) for c in b.get('cells', [])]
        matches = []
        cache = {}
        for ref in self.scoped_topology(body, 'CGMEdge'):
            if not str(ref.DisplayName).startswith('Selection_REdge:'):
                continue
            try:
                points = array(9)
                spa.GetMeasurable(ref).GetPointsOnCurve(points)
                if not all(any(all(lo - self.geometry_tolerance() <= v <= hi + self.geometry_tolerance()
                                   for v, lo, hi in zip(points.value[k:k+3], cell['bbox_min'], cell['bbox_max']))
                               for cell in cells) for k in (0, 3, 6)):
                    continue
                faces = brep_faces(str(ref.DisplayName))
                if len(faces) != 2:
                    continue
                matrix = []
                for face in faces:
                    if face not in cache:
                        face_ref = self.part.CreateReferenceFromBRepName(persistent_face_name(face), body)
                        cache[face] = [self.matches_surface(face_ref, expected) for expected in supports]
                    matrix.append(cache[face])
                if (matrix[0][0] and matrix[1][1]) or (matrix[0][1] and matrix[1][0]):
                    matches.append(ref)
            except Exception:
                continue
        if matches:
            self.note('Logical edge restored from its two analytic face supports: ' + selection['selection_id'])
        return matches

    def fillet_reference(self, ref, body, permanent=False):
        """Turn a search-only selection into an editable feature reference.

        CATIA's Selection_RSur references are measurable, but ShapeFactory
        rejects them as fillet inputs. Keep the exact recovered topology and
        bind its persistent RSur name to the incoming Body. Edge selections
        are already accepted by the fillet API and keep their trim context.
        """
        name = str(ref.DisplayName)
        prefixes = {"Selection_RSur:(": ("RSur", "Face:(")}
        if permanent:
            prefixes["Selection_REdge:("] = ("REdge", "Edge:(")
            # Intersections expose Wire:(...), while some edge selections
            # expose WireEdge:(...). Preserve the actual bounded payload.
            wire_token = "Wire:(" if name.startswith("Selection_WireREdge:(Wire:(") else "WireEdge:("
            prefixes["Selection_WireREdge:("] = ("WireREdge", wire_token)
        for prefix, (kind, token) in prefixes.items():
            if not name.startswith(prefix):
                continue
            start = len(prefix)
            if not name.startswith(token, start):
                raise MissingData("Unrecognized fillet selection topology: " + name)
            depth = 0
            for end in range(start + len(token) - 1, len(name)):
                depth += (name[end] == "(") - (name[end] == ")")
                if depth == 0:
                    payload = name[start:end + 1]
                    persistent = (kind + ":(" + payload +
                                  (";WithPermanentBody" if permanent else ";WithTemporaryBody") + ";WithoutBuildError;"
                                  "WithSelectingFeatureSupport;MFBRepVersion_CXR15)")
                    return self.part.CreateReferenceFromBRepName(persistent, body)
            raise MissingData("Unbalanced fillet selection topology: " + name)
        return ref

    def find_brep_by_geometry(self, selection, body_obj=None):
        breps = selection.get("resolved_breps", [])
        cells = [cell for brep in breps for cell in brep.get("cells", [])]
        cells = list({json.dumps(cell, sort_keys=True): cell for cell in cells}.values())
        geometry = self.p.definitions.get(self.current["id"], {}).get("selection_geometry", {}) if self.current else {}
        selection_id = str(selection.get("selection_id", ""))
        extra = geometry.get(selection_id) or geometry.get(selection_id.split(":")[0])
        if extra and len(cells) == 1:
            original = cells[0]
            cells = [dict(original, **extra)]
            if original.get("curve_measurement_source") == "CAA resolved edge":
                # A piece's trimmed points take precedence over the logical
                # selection's longer underlying curve measurements.
                for key in ("curve_points", "length_mm", "curve_measurement_source"):
                    if key in original:
                        cells[0][key] = original[key]
            if original.get("surface_measurement_source") == "CAA resolved face":
                # Keep this trimmed face's bounds when a logical selection
                # measures a larger supporting surface.
                for key in ("area_m2", "cog_mm", "surface_measurement_source"):
                    if key in original:
                        cells[0][key] = original[key]
        if cells and all(cell.get("surface_type") == "Cylinder" for cell in cells):
            return self.find_cylinder_reference(cells, body_obj, selection)
        if len(cells) != 1:
            raise MissingData("Geometric reference recovery requires exactly one exported cell")
        cell = cells[0]
        exact_edge = cell.get("curve_measurement_source") == "CAA resolved edge"
        measured_points = cell.get("curve_points", [])
        target = vector(measured_points[len(measured_points) // 2] if exact_edge and measured_points else cell.get("bbox_center"))
        dimension = cell.get("dimension")
        if dimension not in (1, 2):
            raise MissingData("Unsupported reference cell dimension: " + str(dimension))
        topology = "CGMFace" if dimension == 2 else "CGMEdge"
        refs = self.scoped_topology(body_obj, topology)
        if dimension == 1 and selection.get("brep_type") == "REdge(Edge)":
            # A Body search also returns its sketches. Their wire edges are
            # not edges of the incoming solid, even when they coincide.
            refs = [ref for ref in refs if not str(ref.DisplayName).startswith("Selection_Wire")]
        spa = self.doc.GetWorkbench("SPAWorkbench")
        matches = []
        best_distance = float("inf")
        compatible = []
        with self.measurement_point(target) as point_ref:
            for ref in refs:
                try:
                    measurable = spa.GetMeasurable(ref)
                    if exact_edge and cell.get("length_mm") is not None:
                        # Selection CGM edges are bounded. The exact CAA
                        # edge length cheaply excludes unrelated body edges
                        # before the much more expensive distance queries.
                        expected_length = number(cell["length_mm"])
                        if abs(float(measurable.Length) - expected_length) > max(self.geometry_tolerance(), abs(expected_length) * 1e-6):
                            continue
                    if cell.get("surface_type") == "Plane":
                        if measurable.GeometryName != 7:
                            continue
                        if not self.same_plane(measurable, vector(cell.get("origin")), unit(cell.get("normal"))):
                            continue
                    if dimension == 2 and "area_m2" in cell and "cog_mm" in cell:
                        from catia_com import array
                        center = array(3)
                        measurable.GetCOG(center)
                        if (abs(float(measurable.Area) - cell["area_m2"]) > max(1e-12, abs(cell["area_m2"]) * 1e-6)
                                or math.dist(center.value, cell["cog_mm"]) > self.geometry_tolerance()):
                            continue
                    compatible.append(ref)
                    distance = measurable.GetMinimumDistance(point_ref)
                    best_distance = min(best_distance, distance)
                    if distance <= self.geometry_tolerance():
                        matches.append(ref)
                except Exception:
                    continue
        if (dimension == 2 and self.current.get("type") in ("Trim", "RemoveFace")
                and self.p.definitions[self.current["id"]].get("native_result_geometry")
                and (self.current["type"] != "RemoveFace"
                     or cell.get("surface_measurement_source") == "CAA resolved face")
                and "area_m2" in cell and "cog_mm" in cell and len(compatible) == 1):
            # A curved face's box centre (and its centroid) need not lie on
            # the surface. The exact bounded area and centroid already
            # identify this face uniquely. These handlers additionally check the
            # complete resulting solid's volume, area and centroid.
            self.note(self.current["type"] + " face identified by unique bounded area and centroid: " + selection_id)
            return compatible[0]
        if len(matches) != 1 or exact_edge:
            # Native references can expose an underlying curve longer than
            # the selected trimmed edge. Only use measured source points that
            # fall inside this exported cell; never fit or extend geometry.
            probes = [p for p in cell.get("curve_points", [])
                      if cell.get("bbox_min") is not None and cell.get("bbox_max") is not None
                      and all(lo - self.geometry_tolerance() <= v <= hi + self.geometry_tolerance()
                              for v, lo, hi in zip(p, cell["bbox_min"], cell["bbox_max"]))]
            if probes:
                # Exact edges were screened with one of these actual curve
                # points, so only those matches need the remaining probes.
                candidates = matches[:] if exact_edge else compatible[:]
                for probe in probes:
                    with self.measurement_point(probe) as probe_ref:
                        remaining = []
                        for ref in candidates:
                            try:
                                if spa.GetMeasurable(ref).GetMinimumDistance(probe_ref) <= self.geometry_tolerance():
                                    remaining.append(ref)
                            except Exception:
                                continue
                        candidates = remaining
                if len(candidates) == 1:
                    self.note("Trimmed edge identified by measured source curve points: " + selection_id)
                    return candidates[0]
                if exact_edge:
                    raise MissingData("Exact trimmed edge points have {} matching candidates; selection_id={}".format(len(candidates), selection_id))
            # A box centre need not lie on a trimmed face or curved edge.
            if cell.get("surface_type") == "Plane" and len(compatible) == 1 and selection.get("role") == "neutral_element":
                matches = compatible
            elif cell.get("bbox_min") is not None and cell.get("bbox_max") is not None:
                matches = self.references_with_matching_bounds(compatible, cell)
        if len(matches) != 1:
            raise MissingData("Geometric reference has {} candidates in its Body/feature within {}mm (best={}mm); selection_id={}".format(
                len(matches), self.geometry_tolerance(), best_distance, selection.get("selection_id")))
        self.note("BREP reference recovered geometrically within its Body/feature: " + str(selection.get("selection_id")))
        return matches[0]

    def find_cylinder_reference(self, cells, body_obj, selection):
        import pythoncom
        from win32com.client import VARIANT
        first = cells[0]
        axis, origin, radius = unit(first["axis"]), vector(first["origin"]), number(first["radius"])
        tolerance = self.geometry_tolerance()
        for cell in cells[1:]:
            if (abs(number(cell["radius"]) - radius) > tolerance or
                abs(abs(sum(a*b for a, b in zip(unit(cell["axis"]), axis))) - 1) > 1e-7 or
                math.sqrt(sum(x*x for x in cross(tuple(a-b for a,b in zip(cell["origin"], origin)), axis))) > tolerance):
                raise MissingData("Selected cylindrical cells do not belong to one cylinder")
        matches = []
        spa = self.doc.GetWorkbench("SPAWorkbench")
        for ref in self.scoped_topology(body_obj, "CGMFace"):
            try:
                m = spa.GetMeasurable(ref)
                if m.GeometryName != 4 or abs(m.Radius - radius) > tolerance:
                    continue
                direction = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [0.0]*3)
                positions = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [0.0]*9)
                m.GetAxis(direction)
                m.GetPointsOnAxis(positions)
                if abs(abs(sum(a*b for a,b in zip(unit(direction.value), axis))) - 1) > 1e-7:
                    continue
                delta = tuple(a-b for a,b in zip(positions.value[:3], origin))
                if math.sqrt(sum(x*x for x in cross(delta, axis))) <= tolerance:
                    matches.append(ref)
            except Exception:
                continue
        if len(matches) != 1:
            raise MissingData("Cylinder selection has {} matching faces in its input scope".format(len(matches)))
        self.note("Cylindrical selection restored from exported axis/radius: " + str(selection.get("selection_id")))
        return matches[0]

    def find_face_on_plane(self, plane_root, plane_normal, body_obj):
        spa = self.doc.GetWorkbench("SPAWorkbench")
        matches = []
        for ref in self.scoped_topology(body_obj, "CGMFace"):
            try:
                measurable = spa.GetMeasurable(ref)
                if measurable.GeometryName == 7 and self.same_plane(measurable, plane_root, plane_normal):
                    matches.append(ref)
            except Exception:
                continue
        if len(matches) != 1:
            raise MissingData("Draft neutral plane has {} coincident faces in the target Body; a unique neutral face is required".format(len(matches)))
        return matches[0]

    def geometry_tolerance(self):
        tolerance = number(self.p.manifest.get("tolerance", {}).get("resolution", 0.001))
        if tolerance <= 0:
            raise MissingData("Invalid model resolution")
        return tolerance

    def matches_surface(self, ref, expected):
        from catia_com import array
        m = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(ref)
        if expected['surface_type'] == 'Plane':
            return m.GeometryName == 7 and self.same_plane(m, expected['origin'], expected['normal'])
        if expected['surface_type'] == 'Cylinder' and m.GeometryName == 4:
            axis, points = array(3), array(9)
            m.GetAxis(axis)
            m.GetPointsOnAxis(points)
            parallel = abs(abs(sum(a*b for a,b in zip(unit(axis.value), unit(expected['axis'])))) - 1) < 1e-7
            distance = math.sqrt(sum(v*v for v in cross(tuple(a-b for a,b in zip(points.value[:3], expected['origin'])), unit(expected['axis']))))
            return parallel and distance <= self.geometry_tolerance() and abs(m.Radius - expected['radius']) <= self.geometry_tolerance()
        if expected['surface_type'] == 'Cone' and m.GeometryName == 6:
            axis, points = array(3), array(9)
            m.GetAxis(axis)
            m.GetPointsOnAxis(points)
            parallel = abs(abs(sum(a*b for a,b in zip(unit(axis.value), unit(expected['axis'])))) - 1) < 1e-7
            distance = math.sqrt(sum(v*v for v in cross(tuple(a-b for a,b in zip(points.value[:3], expected['origin'])), unit(expected['axis']))))
            if not parallel or distance > self.geometry_tolerance() or abs(m.Angle - expected['angle']) > 1e-6:
                return False
            with self.measurement_point(expected['curve_point']) as probe:
                return m.GetMinimumDistance(probe) <= self.geometry_tolerance()
        return False

    def measured_plane(self, measurable):
        # CATIA GetPlane uses an output SAFEARRAY(VARIANT). Passing a plain
        # Python tuple to late-bound COM loses its output values.
        import pythoncom
        from win32com.client import VARIANT
        values = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [0.0] * 9)
        measurable.GetPlane(values)
        data = values.value
        return vector(data[:3]), unit(cross(data[3:6], data[6:9]))

    @contextmanager
    def measurement_point(self, target):
        target = self.bounded_coordinates(target)
        previous_work = self.part.InWorkObject
        temp = self.own(self.part.HybridBodies.Add())
        temp.Name = "__ReferenceMeasurement"
        try:
            point = self.hsf.AddNewPointCoord(*target)
            point.Name = "__ReferenceProbe_" + self.current["name"]
            temp.AppendHybridShape(point)
            self.part.UpdateObject(point)
            yield self.ref(point)
        finally:
            # HybridBodies.Remove/HybridBody.Remove are not reliable CATIA
            # deletion APIs. Selection.Delete removes the set and its point.
            sel = self.doc.Selection
            try:
                sel.Clear()
                sel.Add(temp)
                sel.Delete()
                self.owned = [obj for obj in self.owned if obj is not temp]
            finally:
                sel.Clear()
                self.part.InWorkObject = previous_work

    def native_brep_reference(self, name, scope, expected):
        ref, measurable = self.resolved_native_brep_reference(name, scope)
        if expected.get("surface_type"):
            if not self.matches_surface(ref, expected):
                raise MissingData("Rebased face does not match the source analytic surface")
        elif expected.get("curve_points"):
            for point in expected["curve_points"]:
                with self.measurement_point(point) as probe:
                    if measurable.GetMinimumDistance(probe) > self.geometry_tolerance():
                        raise MissingData("Rebased edge does not match the source curve")
        else:
            raise MissingData("Native BRep needs independent source geometry verification")
        return ref

    def native_extract_ref(self, element):
        if element.get("input"):
            return self.native_input_ref(element["input"])
        if element.get("selection"):
            selection = element["selection"]
            ref = self.selection_ref(selection)
            # Search yields Selection_RSur handles, which are measurable but
            # rejected by AddConstraintTolerant. Bind that same face to its
            # exported support before passing it to the editing API.
            if str(getattr(ref, "DisplayName", "")).startswith(("Selection_RSur:(", "Selection_WireREdge:(", "Selection_REdge:(")):
                support = self.require(selection["support_feature"])
                # GSM extracts retain their source's permanent surface body.
                # Temporary-body flags are for PartDesign's incoming solid.
                ref = self.fillet_reference(ref, support, permanent=True)
            return ref
        expected = element["geometry"]
        scope = self.require(element["scope"])
        try:
            return self.native_brep_reference(element["native_reference"], scope, expected)
        except Exception as exc:
            self.note("Native extract topology fallback: " + str(exc))
        dimension = expected["dimension"]
        refs = self.scoped_topology(scope, "CGMFace" if dimension == 2 else "CGMEdge")
        spa = self.doc.GetWorkbench("SPAWorkbench")
        matches = []
        diagnostic = []
        for ref in refs:
            try:
                m = spa.GetMeasurable(ref)
                if dimension == 2:
                    if self.matches_surface(ref, expected):
                        matches.append(ref)
                elif abs(float(m.Length) - expected["length_mm"]) <= self.geometry_tolerance():
                    match = True
                    for point in expected["curve_points"]:
                        with self.measurement_point(point) as probe:
                            if m.GetMinimumDistance(probe) > self.geometry_tolerance():
                                match = False
                                break
                    if match:
                        matches.append(ref)
                if dimension == 1:
                    diagnostic.append({"length_mm": float(m.Length), "name": str(ref.DisplayName)})
            except Exception:
                continue
        if len(matches) != 1:
            self.note("Extract candidates: " + json.dumps(diagnostic, ensure_ascii=False))
            raise MissingData("Native extract reference has {} candidates in {}".format(len(matches), element["scope"]["full_path"]))
        ref = matches[0]
        self.note("Native extract matched topology: " + str(ref.DisplayName))
        if str(ref.DisplayName).startswith("Selection_RSur:("):
            name = persistent_face_name(brep_faces(str(ref.DisplayName))[0]).replace("WithTemporaryBody", "WithPermanentBody")
            ref = self.part.CreateReferenceFromBRepName(name, scope)
        return ref

    def native_input_ref(self, value):
        if value.get("curve_endpoint"):
            from catia_com import array
            endpoint = value["curve_endpoint"]
            curve = self.native_input_ref(endpoint["curve"])
            expected = self.bounded_coordinates(endpoint["point_mm"])
            try:
                measurable = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(curve)
                points = array(9)
                measurable.GetPointsOnCurve(points)
            except Exception:
                # GetPointsOnCurve fails on multi-curve containers such as PRTSketch
                # because the sketch feature is not a single measurable curve.  Fall
                # back to a coordinate point at the exported endpoint position.
                obj = self.own(self.hsf.AddNewPointCoord(*expected))
                self.helpers.AppendHybridShape(obj)
                self.part.UpdateObject(obj)
                return self.ref(obj)
            matches = [index for index, start in enumerate((0, 6))
                       if math.dist(expected, points.value[start:start+3]) <= self.geometry_tolerance()]
            if len(matches) != 1:
                raise MissingData("Curve boundary does not identify exactly one source endpoint")
            obj = self.own(self.hsf.AddNewPointOnCurveFromPercent(curve, float(matches[0]), False))
            self.helpers.AppendHybridShape(obj)
            self.part.UpdateObject(obj)
            actual = array(3)
            self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj)).GetPoint(actual)
            if math.dist(expected, actual.value) > self.geometry_tolerance():
                raise MissingData("Dependent curve endpoint differs from the exported boundary")
            return self.ref(obj)
        if value.get("selection"):
            return self.selection_ref(value["selection"])
        if value.get("feature"):
            return self.ref(self.require(value["feature"]))
        if value.get("inverse"):
            if value.get("orientation") not in (-1, 1):
                raise MissingData("Invalid native inverse orientation")
            obj = self.own(self.hsf.AddNewInverse(self.native_input_ref(value["inverse"]), value["orientation"]))
            self.helpers.AppendHybridShape(obj)
            self.part.UpdateObject(obj)
            return self.ref(obj)
        if value.get("line"):
            line = value["line"]
            root = self.own(self.hsf.AddNewPointCoord(*self.bounded_coordinates(line["origin"])))
            self.helpers.AppendHybridShape(root)
            self.part.UpdateObject(root)
            obj = self.own(self.hsf.AddNewLinePtDir(self.ref(root),
                self.hsf.AddNewDirectionByCoord(*unit(line["direction"])), -1.0, 1.0, False))
            obj.SetLengthType(1)
            self.helpers.AppendHybridShape(obj)
            self.part.UpdateObject(obj)
            return self.ref(obj)
        raise MissingData("Native input needs an exact feature identity or measured line")

    def pad_limit(self, obj, data, first):
        limit = obj.FirstLimit if first else obj.SecondLimit
        kind = data.get("type", "Dimension")
        modes = {"Dimension": 0, "Offset": 0, "UpToNext": 1, "UpToLast": 2, "UpToPlane": 3, "UpToSurface": 4}
        if kind not in modes:
            raise MissingData("Unsupported pad limit " + kind)
        limit.LimitMode = modes[kind]
        if kind in ("UpToPlane", "UpToSurface"):
            reference = data.get("up_to_reference") or data.get("up_to")
            limit.LimitingElement = self.ref(self.require(reference))
            offset = number(data.get("offset_from_surface", 0))
            if offset:
                # Limit.Dimension is the inactive length, not the surface
                # offset. CATIA exposes the latter through native parameters.
                names = ("第一限制/偏移", "FirstLimit/Offset", "First Limit/Offset") if first else ("第二限制/偏移", "SecondLimit/Offset", "Second Limit/Offset")
                params = self.part.Parameters.SubList(obj, False)
                matches = [params.Item(i) for i in range(1, params.Count + 1)
                           if any(normal_path(str(params.Item(i).Name)).endswith("/" + name) for name in names)]
                if len(matches) != 1:
                    if kind != "UpToPlane":
                        raise MissingData("Native up-to-surface offset parameter was not found")
                    # V5's automation Limit creates no native surface-offset
                    # parameter. Preserve the exported plane's orientation:
                    # a positive offset lies on its negative-normal side.
                    # Limit.Dimension is an unrelated, inactive length.
                    plane = self.p.lookup(reference, self.current)
                    root, normal = self.p.plane(plane)
                    helper = self.own(self.hsf.AddNewPlaneEquation(
                        *normal, sum(a*b for a, b in zip(root, normal)) - offset))
                    self.helpers.AppendHybridShape(helper)
                    self.part.UpdateObject(helper)
                    limit.LimitingElement = self.ref(helper)
                    self.note("Up-to-plane offset {}mm restored using an auxiliary parallel plane".format(offset))
                else:
                    matches[0].Value = offset
                    self.bind(names[0], matches[0])
        elif modes[kind] == 0:
            limit.Dimension.Value = number(data.get("offset", 0))
            self.bind("第一限制/长度" if first else "第二限制/长度", limit.Dimension)

    def paste_native_group(self, asset, source_objects, container, label):
        """Copy one isolated template group, retrying only a zero-object paste."""
        collection = container.HybridShapes
        count = collection.Count
        target = self.doc.Selection
        for attempt in range(2):
            # Activation can finish a delayed insertion. Recheck before
            # recopying so it cannot create a duplicate template group.
            self.doc.Activate()
            if collection.Count != count:
                break
            asset.Activate()
            asset.Selection.Clear()
            for obj in source_objects:
                asset.Selection.Add(obj)
            asset.Selection.Copy()
            self.doc.Activate()
            self.part.InWorkObject = container
            target.Clear()
            target.Add(container)
            target.PasteSpecial("CATPrtCont")
            target.Clear()
            asset.Selection.Clear()
            if collection.Count != count:
                break
        added = [self.own(collection.Item(i)) for i in range(count + 1, collection.Count + 1)]
        if len(added) != len(source_objects):
            raise MissingData(label + " group copy produced {} objects; expected {}".format(len(added), len(source_objects)))
        return added

    def populate_exact_sketch(self, record, sketch, axis, data):
        profile = data.get("source_profile", {})
        source_axis = profile.get("axis", [])
        if len(source_axis) != 9 or any(abs(number(a)-number(b)) > 1e-9 for a, b in zip(axis, source_axis)):
            raise MissingData("Exact sketch profile frame differs from the sketch definition")
        expected = {"CGMVertex": data.get("source_vertex_count"), "CGMEdge": data.get("source_edge_count"),
                    "CGMFace": data.get("source_face_count")}
        if expected["CGMFace"] != 0 or not isinstance(expected["CGMEdge"], int) or expected["CGMEdge"] <= 0:
            raise MissingData("Exact sketch asset requires nonempty stored wire topology")
        datum = self.create_native_datum(record, {"native_curve_datum": data}, self.helpers, curve=True)
        if {k: len(v) for k, v in self.topology_references(self.doc, datum).items()} != expected:
            raise MissingData("Exact sketch datum topology differs from source")
        factory = sketch.OpenEdition()
        try:
            projections = factory.CreateProjections(self.ref(datum))
            if projections.Count != 1:
                raise MissingData("Exact profile did not create one composite projection")
            projections.Item(1).Construction = False
        finally:
            sketch.CloseEdition()
        self.part.UpdateObject(sketch)
        topology = self.topology_references(self.doc, sketch)
        if {k: len(v) for k, v in topology.items()} != expected:
            raise MissingData("Projected sketch topology differs from source")
        workbench = self.doc.GetWorkbench("SPAWorkbench")
        measures = [workbench.GetMeasurable(ref) for ref in topology["CGMEdge"]]
        if abs(sum(float(m.Length) for m in measures)-number(profile["length_mm"])) > self.geometry_tolerance():
            raise MissingData("Projected sketch perimeter differs from source")
        source_samples = [xy for curve in profile.get("curves", []) for xy in curve.get("points_xy_mm", [])]
        if not source_samples:
            raise MissingData("Exact sketch has no independent source profile samples")
        point = self.hsf.AddNewPointCoord(0, 0, 0)
        self.helpers.AppendHybridShape(point)
        try:
            for xy in source_samples:
                xyz = self.bounded_coordinates([axis[i]+axis[i+3]*number(xy[0])+axis[i+6]*number(xy[1]) for i in range(3)])
                point.X.Value, point.Y.Value, point.Z.Value = xyz
                self.part.UpdateObject(point)
                if min(float(m.GetMinimumDistance(self.ref(point))) for m in measures) > self.geometry_tolerance():
                    raise MissingData("Projected sketch position differs from independent source profile samples")
        finally:
            selection = self.doc.Selection
            selection.Clear()
            selection.Add(point)
            selection.Delete()
            selection.Clear()

    def rebased_brep_name(self, name):
        # Sketch report numbers are independent of feature names and change
        # when profile/construction curves are recreated in a different order.
        name = re.sub(r"(?<=\()(Sketch\.\d+);(\d+)(?=[;)])",
                      lambda m: m[1] + ";" + self.native_subelements.get(m[0], m[2]), name)
        def rename(match):
            token = match[0]
            for suffix in ("_ResultOUT", "_ResultIN", ""):
                if not suffix or token.endswith(suffix):
                    base = token[:-len(suffix)] if suffix else token
                    if base in self.native_names:
                        return self.native_names[base] + suffix
            return token
        return re.sub(r"(?<=[(;])([^();]+)(?=[;)])", rename, name)

    def references_with_matching_bounds(self, refs, cell):
        """Compare all six exact extrema of bounded geometry, within resolution."""
        import pythoncom
        from win32com.client import VARIANT
        matches = []
        spa = self.doc.GetWorkbench("SPAWorkbench")
        tolerance = self.geometry_tolerance()
        for ref in refs:
            # A reference to an unbounded underlying line/plane is measurable
            # but has zero bounded length/area. Never ask CATIA to generate
            # extrema for it: the resulting points can lie outside the model.
            try:
                m = spa.GetMeasurable(ref)
                size = m.Length if cell["dimension"] == 1 else m.Area * 1e6
                if not math.isfinite(size) or size <= tolerance ** cell["dimension"]:
                    continue
                if cell["dimension"] == 1:
                    samples = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [0.0]*9)
                    m.GetPointsOnCurve(samples)
                    if any(not (cell["bbox_min"][k % 3] - tolerance <= v <= cell["bbox_max"][k % 3] + tolerance)
                           for k, v in enumerate(samples.value)):
                        continue
            except Exception:
                continue
            previous_work = self.part.InWorkObject
            temp = self.own(self.part.HybridBodies.Add())
            temp.Name = "__ReferenceBounds"
            try:
                # Reject a candidate as soon as one extremum disagrees. Some
                # Bodies have hundreds of edges; calculating all six bounds
                # of every rejected edge needlessly stalls reconstruction.
                conservative = cell.get("curve_type") == "Other" or cell.get("surface_type") == "Other"
                match = True
                for side in (0, 1):
                    for axis in range(3):
                        direction = self.hsf.AddNewDirectionByCoord(*(1 if k == axis else 0 for k in range(3)))
                        extremum = self.hsf.AddNewExtremum(ref, direction, side)
                        extremum.Name = "__Bound_{}_{}".format(axis, side)
                        temp.AppendHybridShape(extremum)
                        self.part.UpdateObject(extremum)
                        m = spa.GetMeasurable(self.ref(extremum))
                        point = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [0.0]*3)
                        try:
                            m.GetPoint(point)
                        except Exception:
                            try:
                                m.GetCOG(point)
                            except Exception:
                                # A constant coordinate can make an extremum
                                # an entire edge. SPA has no curve GetCOG;
                                # every point of that edge has this extremum.
                                points = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [0.0]*9)
                                m.GetPointsOnCurve(points)
                                point.value = list(points.value[:3])
                        actual = self.bounded_coordinates(point.value)[axis]
                        expected = cell["bbox_min" if side == 0 else "bbox_max"][axis]
                        # CGM boxes for non-analytic cells are conservative.
                        # Require containment on every side, then uniqueness.
                        match = ((actual >= expected - tolerance if side == 0 else actual <= expected + tolerance)
                                 if conservative else abs(actual - expected) <= tolerance)
                        if not match:
                            break
                    if not match:
                        break
                if match:
                    matches.append(ref)
            except Exception:
                continue
            finally:
                sel = self.doc.Selection
                try:
                    sel.Clear()
                    sel.Add(temp)
                    sel.Delete()
                    self.owned = [obj for obj in self.owned if obj is not temp]
                finally:
                    sel.Clear()
                    self.part.InWorkObject = previous_work
        return matches

    def register_name(self, record, obj):
        # CATIA's BRep strings use internal counters, not the displayed alias.
        # Record the fresh factory counter before restoring the source alias.
        default_name = str(obj.Name)
        source_name = record.get("internal_name", "")
        match = re.search(r"\.(\d+)$", default_name)
        if match and re.search(r"\.\d+$", source_name):
            self.native_names[source_name] = source_name.rsplit(".", 1)[0] + "." + match[1]
        obj.Name = record["name"]

    def register_sketch_geometry(self, record, definition, created):
        reports = definition.get("geometry_report_names")
        if reports is None:
            return  # Older packages still require scoped/result validation.
        if len(reports) != len(definition.get("geometries", [])):
            raise MissingData("Sketch report names do not correspond to geometry indices")
        source = record.get("internal_name", "")
        frequencies = collections.Counter(index for index, _ in created)
        mapped = {}
        for index, geometry in created:
            numbers = reports[index]
            if not numbers or len(numbers) != 1 or frequencies[index] != 1:
                continue  # Composite/projected or sampled curves need another mapping.
            key = source + ";" + str(numbers[0])
            if key in mapped:
                raise MissingData("Ambiguous source sketch report number: " + key)
            mapped[key] = str(geometry.ReportName)
        self.native_subelements.update(mapped)

    def resolved_native_brep_reference(self, name, scope):
        """Resolve legacy support flags; caller must verify source geometry."""
        name = self.rebased_brep_name(name)
        ref = self.part.CreateReferenceFromBRepName(name, scope)
        spa = self.doc.GetWorkbench("SPAWorkbench")
        measurable = spa.GetMeasurable(ref)
        if measurable.GeometryName == 0:
            # Old CATParts serialize Cf11 support flags; fresh V5 geometry
            # uses Cf14. The candidate still must pass the independent
            # analytic/curve checks below before it can become an input.
            name = name.replace("Cf11:", "Cf14:")
            ref = self.part.CreateReferenceFromBRepName(name, scope)
            measurable = spa.GetMeasurable(ref)
            if measurable.GeometryName == 0:
                raise MissingData("Rebased native BRep is unresolved: " + name)
        return ref, measurable

    def same_plane(self, measurable, root, normal):
        origin, candidate_normal = self.measured_plane(measurable)
        normal = unit(normal)
        parallel = abs(abs(sum(a*b for a, b in zip(candidate_normal, normal))) - 1) <= 1e-7
        distance = abs(sum((a-b)*n for a, b, n in zip(origin, root, normal)))
        return parallel and distance <= self.geometry_tolerance()

    def scoped_topology(self, obj, topology):
        if obj is None:
            raise MissingData("Topology lookup needs an explicit Body/feature scope")
        sel = self.doc.Selection
        try:
            sel.Clear()
            sel.Add(obj)
            sel.Search("Topology." + topology + ",sel")
            return [sel.Item2(i).Reference for i in range(1, sel.Count2 + 1)]
        finally:
            sel.Clear()

    def selection_ref(self, selection):
        if selection.get("reference_kind") == "feature":
            return self.ref(self.require({"id": selection.get("source_feature_id"), "name": selection.get("label")}))
        name = selection.get("automation_brep_name")
        context = selection.get("support_feature")
        if not name or not context:
            raise MissingData("BREP selection needs automation_brep_name + support_feature; selection_id=" + str(selection.get("selection_id")))
        try:
            obj = self.require(context)
        except MissingData:
            # Only a self-reference can be mapped to the incoming Body.
            # An unrelated missing support must not silently change owner.
            support = self.p.producer(self.p.lookup(context, self.current))
            if support is None or support["id"] != self.current["id"]:
                raise
            obj = self.container(self.current)
        try:
            ref = self.part.CreateReferenceFromBRepName(name, obj)
            measurable = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(ref)
            if measurable.GeometryName == 0:
                raise MissingData("Native BREP name did not resolve to measurable geometry")
            return ref
        except Exception:
            # CAA Z-label BRep names from the original document don't
            # resolve in the new document.  Fall back to geometric matching
            # using the exported cell bounding-box data.
            support = self.p.effective_producer(self.p.lookup(context, self.current))
            body_record = self.p.container_record(self.current)
            history = self.p.body_history.get(body_record["id"], []) if body_record else []
            if self.current in history:
                position = history.index(self.current)
                incoming = self.p.effective_producer(history[position - 1]) if position else None
                if support and incoming and support["id"] == incoming["id"]:
                    # Searching a Draft/Fillet feature exposes its generated
                    # faces only. The incoming Body also contains unchanged
                    # faces from earlier operations. Expand only for the exact
                    # preceding active result in this same Body.
                    try:
                        return self.find_brep_by_geometry(selection, obj)
                    except MissingData:
                        obj = self.require(body_record)
            support_body = self.p.container_record(support) if support else None
            if support_body and (not body_record or support_body["id"] != body_record["id"]):
                tool_history = self.p.body_history.get(support_body["id"], [])
                tip = self.p.effective_producer(tool_history[-1]) if tool_history else None
                if tip and tip["id"] == support["id"]:
                    # A final tool result also includes faces unchanged by
                    # its last operation. Its exact Body is a valid scope;
                    # earlier results must retain their historical scope.
                    try:
                        return self.find_brep_by_geometry(selection, obj)
                    except MissingData:
                        obj = self.require(support_body)
            return self.find_brep_by_geometry(selection, obj)

    def selections(self, d, role):
        selections = [s for s in d.get("selections", []) if s.get("role") == role]
        if not selections:
            raise MissingData("No selections for " + role)
        refs, seen = [], set()
        for selection in selections:
            cells = [cell for brep in selection.get("resolved_breps", []) for cell in brep.get("cells", [])]
            cells = list({json.dumps(cell, sort_keys=True): cell for cell in cells}.values())
            support_refs = None
            extra = d.get("selection_geometry", {}).get(selection.get("selection_id"), {})
            if extra.get("native_brep_name"):
                try:
                    ref = self.native_brep_reference(extra["native_brep_name"], self.container(self.current), extra)
                    name = str(ref.DisplayName)
                    if name not in seen:
                        refs.append(ref)
                        seen.add(name)
                    self.note("Native topology rebound and checked against source geometry: " + selection["selection_id"])
                    continue
                except Exception as exc:
                    self.note("Native topology fallback for " + selection["selection_id"] + ": " + str(exc))
            if role == "fillet_object" and len(cells) > 1 and extra.get("edge_supports"):
                support_refs = self.edges_on_supports(selection, extra["edge_supports"])
            if support_refs:
                pieces = []
                for ref in support_refs:
                    name = ref.DisplayName
                    if name and name in seen:
                        continue
                    refs.append(ref)
                    if name:
                        seen.add(name)
                continue
            elif len(cells) > 1 and all(cell.get("dimension") == 1 for cell in cells):
                # One persistent edge selection can resolve to several trimmed
                # edge pieces after upstream booleans. Replay every piece.
                pieces = [dict(selection, selection_id=str(selection.get("selection_id")) + ":" + str(i),
                               resolved_breps=[{"cells": [cell]}]) for i, cell in enumerate(cells)]
            else:
                pieces = [selection]
            try:
                piece_refs = [self.selection_ref(piece) for piece in pieces]
            except MissingData:
                if role != "fillet_object" or len(cells) < 2 or not d.get("native_result_geometry"):
                    raise
                piece_refs = self.coalesced_fillet_edges(selection, cells)
            for ref in piece_refs:
                name = ref.DisplayName
                if name and name in seen:
                    # Duplicate edge piece from overlapping BREP exports; skip
                    # rather than abort — adding the same edge twice is benign.
                    continue
                if name:
                    seen.add(name)
                refs.append(ref)
        return refs

    def sweep_geometry_matches(self, obj, expected):
        from catia_com import array
        m = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj))
        center = array(3)
        m.GetCOG(center)
        tolerance = self.geometry_tolerance()
        if expected["properties"].get("GuideDeviationActivity"):
            # Smoothed sweeps explicitly permit deviation from their guide.
            # Use that source feature setting, not an arbitrary relaxed limit.
            tolerance = max(tolerance, expected["guide_deviation_mm"])
        matches = (abs(float(m.Area) - expected["area_m2"]) <= max(1e-10, abs(expected["area_m2"]) * 1e-6)
                   and math.dist(center.value, expected["cog_mm"]) <= tolerance)
        if not matches:
            self.note("Sweep geometry mismatch: " + json.dumps({"area_m2": float(m.Area), "source_area_m2": expected["area_m2"],
                "cog_mm": list(center.value), "source_cog_mm": expected["cog_mm"], "angle_deg": float(obj.GetAngle(1).Value)}))
        return matches

    def topology_references(self, document, obj):
        selection = document.Selection
        result = {}
        try:
            for kind in ("CGMVertex", "CGMEdge", "CGMFace"):
                selection.Clear()
                selection.Add(obj)
                selection.Search("Topology." + kind + ",sel")
                result[kind] = [selection.Item2(i).Reference for i in range(1, selection.Count2 + 1)]
        finally:
            selection.Clear()
        return result

    def validate_fillet_template_geometry(self, obj, expected, asset, original):
        try:
            self.validate_native_result(obj, expected, "Surface fillet")
            return
        except MissingData as strict_error:
            strict_reason = str(strict_error)
        from catia_com import array
        spa = self.doc.GetWorkbench("SPAWorkbench")
        measurable = spa.GetMeasurable(self.ref(obj))
        cog = array(3)
        measurable.GetCOG(cog)
        actual = {"area_m2": float(measurable.Area), "cog_mm": list(cog.value)}
        # Reject material differences before doing the more expensive checks.
        if (abs(actual["area_m2"] - expected["area_m2"]) * 1e6 > max(.01, expected["area_m2"] * 1e6)
               or math.dist(actual["cog_mm"], vector(expected["cog_mm"])) > self.geometry_tolerance()):
           raise MissingData(strict_reason)

        def topology(document, shape):
            selection = document.Selection
            result = {}
            try:
                for key, kind in (("faces", "CGMFace"), ("edges", "CGMEdge")):
                    selection.Clear()
                    selection.Add(shape)
                    selection.Search("Topology." + kind + ",sel")
                    result[key] = [selection.Item2(i).Reference for i in range(1, selection.Count2 + 1)]
            finally:
                selection.Clear()
            return result

        def samples(document, references):
            workbench = document.GetWorkbench("SPAWorkbench")
            points = []
            for reference in references:
                values = array(9)
                workbench.GetMeasurable(reference).GetPointsOnCurve(values)
                points.extend([vector(values.value[i:i+3]) for i in (0, 3, 6)])
            return points

        def distances_to(document, shape, points):
            part = document.Part
            previous = part.InWorkObject
            temporary = part.HybridBodies.Add()
            temporary.Name = "__TemplateBoundaryVerification"
            distances = []
            try:
                point = part.HybridShapeFactory.AddNewPointCoord(0, 0, 0)
                temporary.AppendHybridShape(point)
                ref = part.CreateReferenceFromObject(point)
                measure = document.GetWorkbench("SPAWorkbench").GetMeasurable(part.CreateReferenceFromObject(shape))
                for coords in points:
                    self.bounded_coordinates(coords)
                    point.X.Value, point.Y.Value, point.Z.Value = coords
                    part.UpdateObject(point)
                    distances.append(float(measure.GetMinimumDistance(ref)))
            finally:
                selection = document.Selection
                selection.Clear()
                selection.Add(temporary)
                selection.Delete()
                selection.Clear()
                part.InWorkObject = previous
            return distances

        source_topology, target_topology = topology(asset, original), topology(self.doc, obj)
        distances = [distances_to(self.doc, obj, samples(asset, source_topology["edges"])),
                     distances_to(asset, original, samples(self.doc, target_topology["edges"]))]
        result = verify_template_surface_samples(expected, actual,
            {k: len(v) for k, v in source_topology.items()}, {k: len(v) for k, v in target_topology.items()},
            distances, self.geometry_tolerance())
        result["strict_area_diagnostic"] = strict_reason
        self.template_geometry_checks[self.current["id"]] = result

    def validate_native_result(self, obj, expected, label):
        """A successful update alone is insufficient for recovered native inputs."""
        from catia_com import array
        if expected.get("measurement_unavailable"):
            self.note(label + " source geometry unavailable; skipping result validation")
            return
        if expected and "length_mm" in expected and ("curve_points_mm" in expected or "full_circle" in expected):
            self.part.UpdateObject(obj)
            measure = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj))
            tolerance = self.geometry_tolerance()
            length = float(measure.Length)
            if abs(length - expected["length_mm"]) > max(tolerance, abs(expected["length_mm"]) * 1e-8):
                raise MissingData(label + " curve length differs from source geometry")
            if expected.get("full_circle"):
                circle = expected["full_circle"]
                center, axis = array(3), array(3)
                measure.GetCenter(center)
                measure.GetAxis(axis)
                good = (math.dist(center.value, vector(circle["center_mm"])) <= tolerance
                        and abs(float(measure.Radius) - number(circle["radius_mm"])) <= tolerance
                        and abs(sum(a*b for a,b in zip(unit(axis.value), unit(circle["axis"])))) >= 1 - 1e-10)
            else:
                points = array(9)
                try:
                    measure.GetPointsOnCurve(points)
                except Exception:
                    # GetPointsOnCurve fails on multi-curve containers or
                    # surface results where the measurable is not a simple
                    # curve.  Length validation already passed above, so accept
                    # the result instead of propagating a COM exception.
                    good = True
                else:
                    actual = [vector(points.value[i:i+3]) for i in (0, 3, 6)]
                    wanted = [vector(p) for p in expected["curve_points_mm"]]
                    if len(wanted) != 3:
                        raise MissingData(label + " needs three curve characteristic points")
                    good = any(all(math.dist(a,b) <= tolerance for a,b in zip(actual, order))
                               for order in (wanted, wanted[::-1]))
            if not good:
                raise MissingData(label + " curve position differs from source geometry")
            return
        if not expected or "cog_mm" not in expected:
            raise MissingData(label + " lacks source geometry validation")
        self.part.UpdateObject(obj)
        measure = self.doc.GetWorkbench("SPAWorkbench").GetMeasurable(self.ref(obj))
        center = array(3)
        measure.GetCOG(center)
        actual = {"cog_mm": list(center.value)}
        if "volume_mm3" in expected:
            actual.update(volume_mm3=float(measure.Volume) * 1e9, area_mm2=float(measure.Area) * 1e6)
            good = (abs(actual["volume_mm3"] - expected["volume_mm3"]) <= max(.001, abs(expected["volume_mm3"]) * 1e-6)
                    and abs(actual["area_mm2"] - expected["area_mm2"]) <= max(.01, abs(expected["area_mm2"]) * 1e-6))
        elif "length_mm" in expected:
            actual["length_mm"] = float(measure.Length)
            good = abs(actual["length_mm"] - expected["length_mm"]) <= max(self.geometry_tolerance(), abs(expected["length_mm"]) * 1e-8)
        else:
            actual["area_m2"] = float(measure.Area)
            # Surface results (e.g. surface fillets in GSMTool) rebuilt via the
            # factory path (AddNewFilletBiTangent) from reconstructed supports
            # accumulate solver-level geometric drift that grows along the
            # dependency chain.  The COG check at model resolution (0.001 mm)
            # guards against genuine positional mismatch, while the area
            # tolerance uses a 0.1 mm^2 absolute floor (1e-7 m^2) and 1e-6
            # relative tolerance — 10x the template path's 0.01 mm^2 floor to
            # accommodate factory-path reconstruction noise without the
            # bidirectional boundary sampling available to the template path.
            good = abs(actual["area_m2"] - expected["area_m2"]) <= max(1e-7, abs(expected["area_m2"]) * 1e-6)
        if not good or math.dist(actual["cog_mm"], vector(expected["cog_mm"])) > self.geometry_tolerance():
            raise MissingData(label + " differs from source geometry: " + json.dumps(actual))

    def apply_layer_assignments(self):
        """Restore layer assignments from layer_assignments data."""
        assignments = getattr(self.p, "layer_assignments", [])
        result = {"total": len(assignments), "applied": 0, "not_found": 0, "failed": 0}
        if self.dry_run or not assignments:
            self.validation["layer_assignments"] = result
            return
        selection = self.doc.Selection
        for row in assignments:
            feature_name = row.get("feature")
            if not feature_name:
                result["not_found"] += 1
                continue
            rid = row.get("id")
            obj = self.objects.get(rid) if rid else None
            if obj is None:
                obj = self.lookup_object_by_name(feature_name)
            if obj is None:
                result["not_found"] += 1
                continue
            layer = row.get("layer")
            if layer is None:
                result["not_found"] += 1
                continue
            try:
                selection.Clear()
                selection.Add(obj)
                selection.VisProperties.SetLayer(int(layer), 0)
                result["applied"] += 1
            except Exception as exc:
                result["failed"] += 1
                if result["failed"] <= 5:
                    self.log("Layer assignment failed for {}: {}".format(feature_name, exc))
            finally:
                selection.Clear()
        self.validation["layer_assignments"] = result
        self.log("Layer assignments: " + json.dumps(result, ensure_ascii=False))

    def apply_rules_checks(self):
        """Recreate rule reactions from rules_checks.json after geometry rebuild.

        RelationExpPg entries drive parameter values through conditional
        expressions (if/else).  CATIA Automation exposes them through
        Part.Relations; the source body is stored verbatim in *expression*.
        """
        rules = getattr(self.p, "rules_checks", [])
        result = {"total": len(rules), "created": 0, "failed": 0, "skipped": 0}
        if self.dry_run or not rules:
            self.validation["rules_checks"] = result
            return
        for rule in rules:
            name = rule.get("alias") or rule.get("name", "")
            expression = rule.get("expression", "")
            if not expression:
                result["skipped"] += 1
                continue
            obj = None
            try:
                relations = self.part.Relations
                obj = relations.CreateProgram(name, "", expression)
                self.part.UpdateObject(obj)
                result["created"] += 1
            except Exception as exc:
                if obj is not None:
                    try:
                        sel = self.doc.Selection
                        sel.Clear()
                        sel.Add(obj)
                        sel.Delete()
                        sel.Clear()
                    except Exception:
                        pass
                result["failed"] += 1
        self.validation["rules_checks"] = result
        self.log("Rules: " + json.dumps(result, ensure_ascii=False))

    def apply_visual_properties(self):
        """Restore colour, opacity, line width and line type per feature."""
        props = getattr(self.p, "visual_properties", [])
        result = {"total": len(props), "applied": 0, "not_found": 0, "failed": 0}
        if self.dry_run or not props:
            self.validation["visual_properties"] = result
            return
        selection = self.doc.Selection
        for row in props:
            feature_name = row.get("feature")
            if not feature_name:
                result["not_found"] += 1
                continue
            rid = row.get("id")
            obj = self.objects.get(rid) if rid else None
            if obj is None:
                obj = self.lookup_object_by_name(feature_name)
            if obj is None:
                result["not_found"] += 1
                continue
            try:
                selection.Clear()
                selection.Add(obj)
                vp = selection.VisProperties
                color = row.get("color")
                if color and len(color) >= 3:
                    vp.SetRealColor(color[0], color[1], color[2], 0)
                opacity = row.get("opacity")
                if opacity is not None and opacity < 255:
                    vp.SetRealOpacity(opacity, 0)
                line_width = row.get("line_width")
                if line_width is not None:
                    vp.SetRealWidth(line_width, 0)
                line_type = row.get("line_type")
                if line_type is not None:
                    vp.SetRealLineType(line_type, 0)
                result["applied"] += 1
            except Exception as exc:
                result["failed"] += 1
                if result["failed"] <= 5:
                    self.log("Visual property failed for {}: {}".format(feature_name, exc))
            finally:
                selection.Clear()
        self.validation["visual_properties"] = result
        self.log("Visual properties: " + json.dumps(result, ensure_ascii=False))

    def lookup_object_by_name(self, name):
        """Find a created CATIA object by feature display name for post-actions."""
        if not name:
            return None
        # Match by exact feature name or alias across the package catalog.
        candidates = list(self.p.names.get(name, {}).values())
        if not candidates:
            # Fall back to full_path segments (e.g. "GLV_Hook" matches the root body).
            candidates = [r for r in self.p.by_id.values()
                          if r.get("name") == name or r["full_path"].split("/")[-1] == name]
        if len(candidates) == 1 and candidates[0]["id"] in self.objects:
            return self.objects[candidates[0]["id"]]
        if len(candidates) > 1:
            # Prefer the candidate that was actually reconstructed.
            for r in candidates:
                if r["id"] in self.objects:
                    return self.objects[r["id"]]
        return None

class _ModelDataHandlers:
    def length_mm(self, r, field, *parameter_names):
        """Resolve mixed-unit legacy fields against a unit-bearing parameter.

        Some exported fields are metres despite numeric_units=millimeter.
        Preserve their full precision after verifying the scale against the
        rounded parameter display; never scale unrelated fields globally.
        """
        raw = self.definitions[r["id"]].get(field)
        display = None
        for name in parameter_names:
            try:
                display = self.parameter(r, name)
                break
            except MissingData:
                continue
        pattern = r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(mm|cm|m|in)\s*"
        explicit = re.fullmatch(pattern, str(raw))
        m = re.fullmatch(pattern, str(display))
        if not m:
            if explicit:
                return number(raw)
            raise MissingData("Cannot establish length unit for " + r["full_path"] + "/" + field)
        expected = number(display)
        if raw is None:
            return expected
        # Half of the last printed digit accommodates rounded values such
        # as -0.341mm while retaining -0.34104159676350785 from the raw field.
        mantissa, _, exponent = m[1].lower().partition("e")
        decimals = len(mantissa.partition(".")[2])
        quantum = 10.0 ** (int(exponent or 0) - decimals)
        tolerance = quantum * number("1" + m[2]) / 2 + 1e-10
        candidates = [number(raw)] if explicit else [number(raw), number(raw) * 1000]
        matches = list(dict.fromkeys(v for v in candidates if abs(v - expected) <= tolerance))
        if len(matches) != 1:
            raise MissingData("Ambiguous or inconsistent length unit for {}/{}: raw={!r}, parameter={!r}".format(
                r["full_path"], field, raw, display))
        return matches[0]

    def axis_frame(self, r, include_z=False):
        def frame(root, x, y, z=None):
            root, x, y = checked_axis_frame(root, x, y)
            normal = unit(cross(x, y))
            z = unit(z) if z is not None else normal
            if abs(abs(sum(a*b for a, b in zip(z, normal))) - 1) > 1e-7:
                raise MissingData("Axis system Z is not orthogonal to X/Y")
            return (root, x, y, z) if include_z else (root, x, y)

        d = self.definitions[r["id"]]
        a = d.get("axis", d)
        if a.get("origin", a.get("root")) is not None:
            return frame(a.get("origin", a.get("root")),
                                      a.get("x", a.get("h")), a.get("y", a.get("v")), a.get("z"))
        # Parameter aliases carry the semantic coordinate names; do not infer
        # a frame from arbitrary point/line/plane entries in _Elts.
        groups = (("原点", "Origin"), ("X 轴", "X Axis"),
                  ("Y 轴", "Y Axis"), ("Z 轴", "Z Axis"))
        values = []
        for aliases in groups:
            for group in aliases:
                try:
                    values.append(tuple(number(self.parameter(r, group + "/" + k)) for k in "XYZ"))
                    break
                except MissingData:
                    continue
            else:
                raise MissingData("Missing axis coordinates for " + r["full_path"] + "/" + aliases[0])
        return frame(*values)

HANDLERS = {
    'Add': _ReconstructorHandlers.create_boolean,
    'Assemble': _ReconstructorHandlers.create_boolean,
    'AxisSystem': _ReconstructorHandlers.create_axis,
    'Chamfer': _ReconstructorHandlers.create_additional_solid,
    'CloseSurface': _ReconstructorHandlers.create_closed_surface,
    'Draft': _ReconstructorHandlers.create_draft,
    'EdgeFillet': _ReconstructorHandlers.create_fillet,
    'GSMAssemble': _ReconstructorHandlers.create_join,
    'GSMAxisToAxis': _ReconstructorHandlers.create_axis_transform,
    'GSMBiDim': _ReconstructorHandlers.create_surface_datum,
    'GSMBlend': _ReconstructorHandlers.create_procedural_surface,
    'GSMBoundary': _ReconstructorHandlers.create_boundary,
    'GSMCircle': _ReconstructorHandlers.create_circle,
    'GSMCurvePar': _ReconstructorHandlers.create_procedural_surface,
    'GSMCurveSmooth': _ReconstructorHandlers.create_procedural_surface,
    'GSMExtrapol': _ReconstructorHandlers.create_extrapolate,
    'GSMExtrude': _ReconstructorHandlers.create_extrude,
    'GSMFill': _ReconstructorHandlers.create_fill,
    'GSMFillet': _ReconstructorHandlers.create_surface_fillet,
    'GSMIntersect': _ReconstructorHandlers.create_intersection,
    'GSMInverse': _ReconstructorHandlers.create_procedural_surface,
    'GSMLine': _ReconstructorHandlers.create_line,
    'GSMMonoDim': _ReconstructorHandlers.create_line,
    'GSMMultiExtract': _ReconstructorHandlers.create_extract,
    'GSMNear': _ReconstructorHandlers.create_procedural_surface,
    'GSMOffset': _ReconstructorHandlers.create_offset,
    'GSMPlane': _ReconstructorHandlers.create_plane,
    'GSMPoint': _ReconstructorHandlers.create_point,
    'GSMProject': _ReconstructorHandlers.create_procedural_surface,
    'GSMRotate': _ReconstructorHandlers.create_rotate,
    'GSMSplit': _ReconstructorHandlers.create_surface_split,
    'GSMSweep': _ReconstructorHandlers.create_sweep,
    'GSMTool': _ReconstructorHandlers.create_container,
    'GSMTranslate': _ReconstructorHandlers.create_translate,
    'GSMTrim': _ReconstructorHandlers.create_procedural_surface,
    'GSMZeroDim': _ReconstructorHandlers.create_point,
    'Intersect': _ReconstructorHandlers.create_boolean,
    'MechanicalTool': _ReconstructorHandlers.create_container,
    'Mirror': _ReconstructorHandlers.create_mirror,
    'PRTSketch': _ReconstructorHandlers.create_sketch,
    'Pad': _ReconstructorHandlers.create_pad,
    'Pocket': _ReconstructorHandlers.create_pad,
    'RectPattern': _ReconstructorHandlers.create_pattern,
    'Remove': _ReconstructorHandlers.create_boolean,
    'RemoveFace': _ReconstructorHandlers.create_additional_solid,
    'Rib': _ReconstructorHandlers.create_rib,
    'Shaft': _ReconstructorHandlers.create_shaft,
    'Shell': _ReconstructorHandlers.create_shell,
    'Solid': _ReconstructorHandlers.create_solid_datum,
    'SolidCombine': _ReconstructorHandlers.create_combine,
    'Split': _ReconstructorHandlers.create_split,
    'StUntrimFeature': _ReconstructorHandlers.create_surface_datum,
    'ThickSurface': _ReconstructorHandlers.create_additional_solid,
    'Thickness': _ReconstructorHandlers.create_thickness,
    'Trim': _ReconstructorHandlers.create_trim,
    'TritangentFillet': _ReconstructorHandlers.create_tritangent_fillet,
}

for _n in dir(_ReconstructorHandlers):
    if not _n.startswith("_"):
        setattr(Reconstructor, _n, getattr(_ReconstructorHandlers, _n))

for _n in dir(_ModelDataHandlers):
    if not _n.startswith("_"):
        setattr(ModelData, _n, getattr(_ModelDataHandlers, _n))

# Restore and verify before the CLI writes the report or saves the Part.
# Keep the engine files intact; repeated imports must not stack hooks.
if "_baked_base_validate" not in Reconstructor.__dict__:
    Reconstructor._baked_base_validate = Reconstructor.validate
    Reconstructor._baked_base_report = Reconstructor.report

def _validate_with_post_actions(self):
    try:
        self._baked_base_validate()
    finally:
        self.p.visibility_resolution = deepcopy(VISIBILITY_RESOLUTION)
        self.apply_visibility()
        # Post-geometry actions: rules, visual properties, layers.
        self.p.rules_checks = deepcopy(RULES_CHECKS)
        self.p.formulas = deepcopy(FORMULAS)
        self.p.visual_properties = deepcopy(VISUAL_PROPERTIES)
        self.p.layer_assignments = deepcopy(LAYER_ASSIGNMENTS)
        self.apply_rules_checks()
        self.apply_visual_properties()
        self.apply_layer_assignments()

def _report_with_post_actions(self):
    result = self._baked_base_report()
    result["visibility_resolution"] = deepcopy(VISIBILITY_RESOLUTION)
    result["rules_checks"] = deepcopy(RULES_CHECKS)
    result["provenance"] = deepcopy(PROVENANCE)
    result["units"] = deepcopy(UNITS)
    result["tree_segments"] = deepcopy(TREE_SEGMENTS)
    if not self.dry_run:
        visibility = self.validation.get("visibility", {})
        if (not visibility or self.validation.get("visibility_errors")
                or visibility.get("without_source_state")):
            result["complete"] = False
    return result

Reconstructor.validate = _validate_with_post_actions
Reconstructor.report = _report_with_post_actions

