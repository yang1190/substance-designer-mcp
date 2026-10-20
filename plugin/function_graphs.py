"""
Function-graph tooling for the SD MCP plugin (Substance 3D Designer 16+).

Covers every place SD 16 expects a *function graph on a node parameter*:
  - 3D viewer           : sdf_scene / intersect_scene / camera_function / custom_output
  - Shape splatter v2   : pattern_sdf_function (shape_type = SDF Function),
                          position_function (position_distribution_mode = Custom Function),
                          pattern_custom_function
  - Shape splatter v2 mapper : custom_function (projection_mode = Custom function)
  - Pixel processor     : perpixel
  - Value processor     : function

Facts confirmed on SD 16.0.5:
  - SDF primitives/operators/transforms/materials are SDSBSFunctionGraph resources in
    <SD>/resources/packages/3d_functions.sbs, stored in folders
    (pkg:///3d_sdf_primitives/3d_sdf_sphere) -> resolve by identifier, not URL.
  - Inputs of function *instance* nodes and of polymorphic atomic nodes (add, mul...)
    are connection-only: getPropertyValue() returns None and setting a value aborts
    the call. Values must come from const_* nodes (or get_* variable nodes).
  - const_* / get_* / swizzle / sample nodes carry their value in '__constant__'.
  - SDF space is Z-up; P (world position) is implicit when 'p_input' is unconnected.
  - Shape splatter v2 exposes per-shape variables such as 'shape.id' (get_float1).
"""

import os
import re

from sd.api.sdproperty import SDPropertyCategory
from sd.api.sdbasetypes import float2
from sd.api.sdvaluestring import SDValueString

from .common import SDError, _log

try:
    from sd.api.sbs.sdsbsfunctiongraph import SDSBSFunctionGraph
except Exception:  # pragma: no cover
    SDSBSFunctionGraph = None



# ── type helpers ──────────────────────────────────────────────────────────────
_CONST_FOR_TYPE = {
    "float": "const_float1", "float1": "const_float1", "float2": "const_float2",
    "float3": "const_float3", "float4": "const_float4",
    "int": "const_int1", "int1": "const_int1", "int2": "const_int2",
    "int3": "const_int3", "int4": "const_int4",
    "bool": "const_bool", "string": "const_string",
}
_GETTER_FOR_TYPE = {
    "float": "get_float1", "float1": "get_float1", "float2": "get_float2",
    "float3": "get_float3", "float4": "get_float4",
    "int": "get_integer1", "int1": "get_integer1", "int2": "get_integer2",
    "int3": "get_integer3", "int4": "get_integer4",
    "bool": "get_bool", "string": "get_string",
}
# value type expected by _make_sd_value for each const node
_VALUE_TYPE_FOR_CONST = {
    "const_float1": "float", "const_float2": "float2", "const_float3": "float3",
    "const_float4": "float4", "const_int1": "int", "const_int2": "int2",
    "const_int3": "int3", "const_int4": "int4", "const_bool": "bool",
    "const_string": "string",
}

# 3D viewer "Output" enum (SD 16.0.5)
VIEWER_OUTPUTS = {
    "beauty": 0, "normal_ws": 1, "normal_ts": 2, "position": 3, "distance": 4,
    "depth": 5, "color": 6, "material_id": 9, "sphere_tracing_steps": 98, "custom": 99,
}

# short names -> library identifiers
_SDF_PREFIXES = ("3d_sdf_", "3d_sdf_op_", "3d_sdf_transform_")
_FN_ALIASES = {"set_material_id": "set_id", "material_id": "set_id"}


def _infer_value_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        n = len(value)
        if n == 1:
            return "float"
        if 2 <= n <= 4:
            return "float{}".format(n)  # floats by default; ask explicitly for intN
    raise ValueError("Cannot infer a function value type from {!r}".format(value))


def _norm_type(type_id):
    """SD property type id -> our short type name (float, float3, int2, bool...)."""
    t = (type_id or "").lower()
    if t in _CONST_FOR_TYPE:
        return t
    return None


class FunctionGraphMixin(object):
    """Mixed into CommandHandler. Relies on: _app, _pkg_mgr, _resolve_graph,
    _find_node, _make_sd_value, _lib_packages_dirs, _new_library_node,
    _set_node_params, _new_output_node, create_graph."""

    _FN_RE = re.compile(rb'<function>\s*<identifier v="([^"]+)"')

    # ── function library index ────────────────────────────────────────────
    def _fn_index(self):
        """identifier -> [paths] for every <function> in resources/packages."""
        if getattr(self, "_fn_file_index", None) is not None:
            return self._fn_file_index
        index, hidden = {}, set()
        for d in self._lib_packages_dirs():
            for fn in os.listdir(d):
                if not fn.lower().endswith(".sbs"):
                    continue
                fp = os.path.join(d, fn).replace("\\", "/")
                try:
                    with open(fp, "rb") as fh:
                        data = fh.read()
                except SDError:
                    continue
                ms = list(self._FN_RE.finditer(data))
                for i, m in enumerate(ms):
                    ident = m.group(1).decode("utf-8", "ignore")
                    end = ms[i + 1].start() if i + 1 < len(ms) else len(data)
                    a_end = data.find(b"</attributes>", m.end(), end)
                    if a_end >= 0 and data.find(b'<hideInLibrary v="1"/>', m.end(), a_end) >= 0:
                        hidden.add((ident, fp))
                    index.setdefault(ident, []).append(fp)
        self._fn_file_index, self._fn_hidden = index, hidden
        _log("Function library index: {} functions".format(len(index)))
        return index

    def _rank_fn_file(self, ident, path):
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        return ((ident, path) in self._fn_hidden,
                0 if stem in ("3d_functions", "functions") else 1, len(stem))

    @staticmethod
    def _find_function_in_package(pkg, ident):
        try:
            for r in pkg.getChildrenResources(True):
                if r.getIdentifier() == ident and "SDSBSFunctionGraph" in r.getClassName():
                    return r
        except SDError:
            pass
        return None

    def _resolve_fn_identifier(self, name):
        name = _FN_ALIASES.get(name, name)
        index = self._fn_index()
        if name in index:
            return name
        for pre in _SDF_PREFIXES:
            if pre + name in index:
                return pre + name
        low = {k.lower(): k for k in index}
        if name.lower() in low:
            return low[name.lower()]
        return None

    def _get_function_resource(self, ident):
        """Return (resource, temp_pkg) for a library function identifier."""
        pm = self._pkg_mgr()
        files = sorted(self._fn_index().get(ident, []),
                       key=lambda f: self._rank_fn_file(ident, f))
        best = files[0].lower() if files else None
        for p in list(pm.getPackages()):
            fp = (p.getFilePath() or "").replace("\\", "/").lower()
            if best and fp != best:
                continue
            r = self._find_function_in_package(p, ident)
            if r is not None:
                return r, None
        user_paths = {(u.getFilePath() or "").replace("\\", "/").lower()
                      for u in pm.getUserPackages()}
        for fp in files:
            was_user = fp.lower() in user_paths
            pkg = pm.loadUserPackage(fp)
            if pkg is None:
                continue
            r = self._find_function_in_package(pkg, ident)
            if r is not None:
                return r, (None if was_user else pkg)
            if not was_user:
                self._release_temp_lib_package(pkg)
        return None, None

    def _atomic_function_defs(self, fg=None):
        if getattr(self, "_fn_atomic_defs", None):
            return self._fn_atomic_defs
        tmp = None
        try:
            if fg is None:
                tmp = self._pkg_mgr().newUserPackage()
                fg = SDSBSFunctionGraph.sNew(tmp)
            self._fn_atomic_defs = sorted(d.getId() for d in fg.getNodeDefinitions())
        finally:
            if tmp is not None:
                self._pkg_mgr().unloadUserPackage(tmp)
        return self._fn_atomic_defs

    # ── locating a parameter's function graph ─────────────────────────────
    def _param_function_graph(self, graph_identifier, node_id, param_id,
                              create=False, replace=False):
        graph = self._resolve_graph(graph_identifier)
        node = self._find_node(graph, node_id)
        prop = node.getPropertyFromId(param_id, SDPropertyCategory.Input)
        if prop is None:
            ids = [p.getId() for p in node.getProperties(SDPropertyCategory.Input)
                   if not p.isConnectable() and not p.getId().startswith("$")]
            raise ValueError("Parameter '{}' not found on node {}. Parameters: {}".format(
                param_id, node_id, ids))
        fg = node.getPropertyGraph(prop)
        if fg is not None and replace:
            node.deletePropertyGraph(prop)
            fg = None
        if fg is None and create:
            fg = node.newPropertyGraph(prop, "SDSBSFunctionGraph")
        return graph, node, prop, fg

    # ── node creation inside a function graph ─────────────────────────────
    def _new_function_node(self, fg, type_name):
        """type_name: 'sbs::function::add', 'add', 'const_float3', a library
        function identifier ('3d_sdf_sphere', 'hash11') or SDF short name
        ('sphere', 'union_smooth', 'rotate', 'set_color')."""
        atomic = self._atomic_function_defs(fg)
        if type_name.startswith("sbs::function::"):
            node = fg.newNode(type_name)
            if node is None:
                raise ValueError("Unknown function node '{}'".format(type_name))
            return node, type_name
        if "sbs::function::" + type_name in atomic:
            return fg.newNode("sbs::function::" + type_name), "sbs::function::" + type_name
        ident = self._resolve_fn_identifier(type_name)
        if not ident:
            raise ValueError(
                "Function '{}' not found. Use list_function_nodes / list_sdf_functions."
                .format(type_name))
        res, temp = self._get_function_resource(ident)
        if res is None:
            raise ValueError("Library function '{}' could not be loaded.".format(ident))
        try:
            node = fg.newInstanceNode(res)
        finally:
            self._release_temp_lib_package(temp)
        if node is None:
            raise RuntimeError("newInstanceNode failed for '{}'".format(ident))
        return node, ident

    def _set_constant(self, node, value, value_type):
        node.setInputPropertyValueFromId("__constant__", self._make_sd_value(value_type, value))

    def _function_input_type(self, node, port):
        p = node.getPropertyFromId(port, SDPropertyCategory.Input)
        if p is None:
            ids = [q.getId() for q in node.getProperties(SDPropertyCategory.Input)]
            raise ValueError("Input '{}' not found. Inputs: {}".format(port, ids))
        return _norm_type(p.getType().getId())

    @staticmethod
    def _is_instance(node):
        try:
            return node.getReferencedResource() is not None
        except SDError:
            return False

    def _feed_input(self, fg, node, port, spec, alias_map, created):
        """Connect a value/variable/reference to node.port."""
        ref, out_port = None, "unique_filter_output"
        if isinstance(spec, str) and spec.startswith("@"):
            ref = spec[1:]
        elif isinstance(spec, dict) and ("from" in spec or "ref" in spec):
            ref = spec.get("from") or spec.get("ref")
            out_port = spec.get("output", out_port)
        if ref is not None:
            if ref not in alias_map:
                raise ValueError("Unknown alias '@{}'".format(ref))
            alias_map[ref].newPropertyConnectionFromId(out_port, node, port)
            return
        declared = self._function_input_type(node, port)
        # variable getter: "$pos" or {"var": "shape.id", "type": "float"}
        var, vtype = None, None
        if isinstance(spec, str) and spec.startswith("$"):
            var = spec
        elif isinstance(spec, dict) and "var" in spec:
            var, vtype = spec["var"], spec.get("type")
        if var is not None:
            vtype = vtype or declared or "float"
            getter = fg.newNode("sbs::function::" + _GETTER_FOR_TYPE[vtype])
            getter.setInputPropertyValueFromId("__constant__", SDValueString.sNew(var))
            getter.newPropertyConnectionFromId("unique_filter_output", node, port)
            created.append(getter)
            return
        # constant value
        if isinstance(spec, dict) and "value" in spec:
            value, vtype = spec["value"], spec.get("type")
        else:
            value, vtype = spec, None
        if vtype is None:
            # instance nodes have reliable declared types; atomic ones are polymorphic
            vtype = declared if (declared and self._is_instance(node)) else _infer_value_type(value)
        const_def = _CONST_FOR_TYPE[vtype]
        k = fg.newNode("sbs::function::" + const_def)
        self._set_constant(k, value, _VALUE_TYPE_FOR_CONST[const_def])
        k.newPropertyConnectionFromId("unique_filter_output", node, port)
        created.append(k)

    @staticmethod
    def _layout_function_graph(fg, output_node):
        """Simple right-to-left layout by distance from the output node."""
        depth = {}
        if output_node is None:
            return
        frontier = [(output_node, 0)]
        while frontier:
            n, d = frontier.pop()
            nid = n.getIdentifier()
            if depth.get(nid, -1) >= d:
                continue
            depth[nid] = d
            for p in n.getProperties(SDPropertyCategory.Input):
                for c in (n.getPropertyConnections(p) or []):
                    frontier.append((c.getInputPropertyNode(), d + 1))
        rows = {}
        for n in fg.getNodes():
            d = depth.get(n.getIdentifier(), max(depth.values() or [0]) + 1)
            r = rows.get(d, 0)
            rows[d] = r + 1
            try:
                n.setPosition(float2(-180.0 * d, 110.0 * r))
            except SDError:
                pass

    # ── public commands ───────────────────────────────────────────────────
    def build_function_graph(self, node_id, param_id, nodes, output,
                             graph_identifier=None, replace=True):
        """Create (or replace) the function graph of a node parameter from a
        descriptor and set its output.

        nodes: [{"alias": "s", "type": "sphere",
                 "inputs": {"radius": 0.3, "center_position": [0, 0, 0.3]}},
                {"alias": "u", "type": "union_smooth",
                 "inputs": {"sdf_1": "@s", "sdf_2": "@c", "smoothness": 0.1}},
                {"alias": "uv", "type": "get_float2", "value": "$pos"},
                {"alias": "k", "type": "const_float3", "value": [1, 0, 0]}]
        input values: "@alias" | {"from": alias, "output": port} | number/list/bool
                      (auto const node) | {"value": v, "type": "int2"} |
                      "$var" / {"var": "shape.id", "type": "float"} (getter node)
        output: alias of the node whose result is the function output
        """
        if SDSBSFunctionGraph is None:
            raise RuntimeError("Function graphs are not available in this SD build.")
        graph, node, prop, fg = self._param_function_graph(
            graph_identifier, node_id, param_id, create=True, replace=replace)
        alias_map, created, errors, summary = {}, [], [], []
        for spec in nodes or []:
            alias = spec.get("alias") or spec.get("id_alias")
            try:
                n, resolved = self._new_function_node(fg, spec["type"])
                if "value" in spec:
                    if resolved.split("::")[-1].startswith("get_"):
                        n.setInputPropertyValueFromId("__constant__",
                                                      SDValueString.sNew(str(spec["value"])))
                    else:
                        c_def = resolved.split("::")[-1]
                        vt = spec.get("value_type") or _VALUE_TYPE_FOR_CONST.get(c_def) \
                            or _infer_value_type(spec["value"])
                        self._set_constant(n, spec["value"], vt)
                alias_map[alias] = n
                created.append(n)
                summary.append({"alias": alias, "node_id": n.getIdentifier(), "type": resolved})
            except SDError as e:
                errors.append({"alias": alias, "error": str(e)})
        connections = 0
        for spec in nodes or []:
            alias = spec.get("alias") or spec.get("id_alias")
            n = alias_map.get(alias)
            if n is None:
                continue
            for port, val in (spec.get("inputs") or {}).items():
                try:
                    self._feed_input(fg, n, port, val, alias_map, created)
                    connections += 1
                except SDError as e:
                    errors.append({"alias": alias, "input": port, "error": str(e)})
        out_node = alias_map.get(output)
        if out_node is None:
            errors.append({"output": output, "error": "output alias not created"})
        else:
            fg.setOutputNode(out_node, True)
        self._layout_function_graph(fg, out_node)
        return {
            "graph": graph.getIdentifier(), "node_id": node_id, "param_id": param_id,
            "function_nodes": len(list(fg.getNodes())), "inputs_fed": connections,
            "nodes": summary, "output": output if out_node is not None else None,
            "errors": errors,
        }

    def get_function_graph_info(self, node_id, param_id, graph_identifier=None):
        graph, node, prop, fg = self._param_function_graph(
            graph_identifier, node_id, param_id)
        if fg is None:
            return {"node_id": node_id, "param_id": param_id, "has_function": False}
        outs = {o.getIdentifier() for o in fg.getOutputNodes()}
        items = []
        for n in fg.getNodes():
            r = n.getReferencedResource()
            entry = {"id": n.getIdentifier(),
                     "type": r.getIdentifier() if r else n.getDefinition().getId().split("::")[-1],
                     "is_output": n.getIdentifier() in outs, "inputs": {}}
            for p in n.getProperties(SDPropertyCategory.Input):
                pid = p.getId()
                conns = list(n.getPropertyConnections(p) or [])
                if conns:
                    entry["inputs"][pid] = "@" + conns[0].getInputPropertyNode().getIdentifier()
                elif pid == "__constant__":
                    try:
                        v = n.getPropertyValue(p).get()
                        if hasattr(v, "x"):
                            v = [getattr(v, a) for a in ("x", "y", "z", "w") if hasattr(v, a)]
                        entry["value"] = v
                    except SDError:
                        pass
                else:
                    entry["inputs"][pid] = "(unconnected {})".format(p.getType().getId())
            items.append(entry)
        return {"node_id": node_id, "param_id": param_id, "has_function": True,
                "node_count": len(items), "nodes": items}

    def list_function_nodes(self, filter_text="", include_atomic=True,
                            include_library=True, limit=300):
        ft = (filter_text or "").lower()
        out = {}
        if include_atomic:
            out["atomic"] = [d.split("::")[-1] for d in self._atomic_function_defs()
                             if not ft or ft in d.lower()]
        if include_library:
            idx = self._fn_index()
            lib = sorted(k for k in idx
                         if any((k, f) not in self._fn_hidden for f in idx[k])
                         and (not ft or ft in k.lower()))
            out["library"] = lib[:limit]
            out["library_truncated"] = len(lib) > limit
        out["notes"] = ("Use names directly as 'type' in build_function_graph. "
                        "Values: const_* nodes; variables: get_* nodes ('$pos', 'shape.id').")
        return out

    def list_sdf_functions(self, category="", filter_text=""):
        """The SD 16 SDF function library with input ports and types."""
        if getattr(self, "_sdf_cache", None) is None:
            pm = self._pkg_mgr()
            files = [f for f in self._fn_index().get("3d_sdf_sphere", [])]
            if not files:
                raise RuntimeError("3d_functions.sbs not found (SD 16+ required).")
            fp = files[0]
            was_user = any((u.getFilePath() or "").replace("\\", "/").lower() == fp.lower()
                           for u in pm.getUserPackages())
            pkg = pm.loadUserPackage(fp)
            items = []
            try:
                for r in pkg.getChildrenResources(True):
                    if "SDSBSFunctionGraph" not in r.getClassName():
                        continue
                    try:
                        shown = r.getAnnotationPropertyValueFromId("show_in_library").get()
                    except SDError:
                        shown = True
                    if not shown:
                        continue
                    url = r.getUrl() or ""
                    folder = url[len("pkg:///"):].split("/")[0] if "/" in url[len("pkg:///"):] else ""
                    lab = r.getAnnotationPropertyValueFromId("label")
                    ident = r.getIdentifier()
                    short = ident
                    for pre in ("3d_sdf_op_", "3d_sdf_transform_", "3d_sdf_"):
                        if ident.startswith(pre):
                            short = ident[len(pre):]
                            break
                    items.append({
                        "identifier": ident, "short_name": short,
                        "label": lab.get() if lab else "",
                        "category": {"3d_sdf_primitives": "primitive",
                                     "3d_sdf_operators": "operator",
                                     "3d_sdf_transform": "transform",
                                     "materials": "material"}.get(folder, folder or "other"),
                        "inputs": [(p.getId(), p.getType().getId())
                                   for p in r.getProperties(SDPropertyCategory.Input)],
                    })
            finally:
                if not was_user:
                    pm.unloadUserPackage(pkg)
            self._sdf_cache = items
        cat, ft = (category or "").lower(), (filter_text or "").lower()
        res = [i for i in self._sdf_cache
               if (not cat or i["category"] == cat)
               and (not ft or ft in i["identifier"].lower() or ft in i["label"].lower())]
        return {"count": len(res), "functions": res, "conventions": [
            "Every SDF node outputs one float: signed distance (<0 inside, 0 surface, >0 outside)",
            "Inputs are connection-only; build_function_graph turns plain values into const nodes",
            "Z is up. Leave p_input unconnected to use world position P",
            "Transforms move space (P): connect several shapes' p_input to one 'rotate_p'/'offset_p'",
            "set_id (Set material ID) needs an integer: {'value': 1, 'type': 'int'}",
            "In Shape splatter v2, 'shape.id' (get_float1) gives a per-shape id for variation",
        ]}

    def build_sdf_scene(self, nodes, output, graph_identifier=None, graph_name=None,
                        package_index=0, outputs=None, viewer_params=None,
                        output_usages=None, output_size_log2=10, position=None,
                        material_model=None):
        """Render an SDF scene with 3D viewer node(s): one viewer per requested
        AOV (beauty, normal_ws, normal_ts, position, distance, depth, color,
        material_id), each feeding an output node."""
        if graph_name:
            info = self.create_graph(package_index=package_index, graph_name=graph_name,
                                     material_model=material_model)
            graph_identifier = info["identifier"]
            graph = self._resolve_graph(graph_identifier)
            try:
                self._set_absolute_output_size(graph, output_size_log2, output_size_log2)
            except SDError:
                pass
        graph = self._resolve_graph(graph_identifier)
        outputs = outputs or ["beauty"]
        output_usages = output_usages or {}
        x0, y0 = (position or [0, 0])[:2]
        results = []
        for i, aov in enumerate(outputs):
            if aov not in VIEWER_OUTPUTS:
                raise ValueError("Unknown output '{}'. Valid: {}".format(aov, sorted(VIEWER_OUTPUTS)))
            viewer = self._new_library_node(graph, "3d_viewer", [x0, y0 + 200 * i])
            params = {"scene_type": {"value": 0, "type": "int"},
                      "output": {"value": VIEWER_OUTPUTS[aov], "type": "int"}}
            params.update(viewer_params or {})
            self._set_node_params(viewer, params)
            fg_res = self.build_function_graph(viewer.getIdentifier(), "sdf_scene", nodes, output,
                                               graph_identifier=graph.getIdentifier())
            out = self._new_output_node(graph, output_usages.get(aov), "SDF " + aov)
            out.setPosition(float2(float(x0 + 250), float(y0 + 200 * i)))
            viewer.newPropertyConnectionFromId("output", out, "inputNodeOutput")
            results.append({"output": aov, "viewer_node": viewer.getIdentifier(),
                            "output_node": out.getIdentifier(),
                            "function_nodes": fg_res["function_nodes"],
                            "errors": fg_res["errors"]})
        return {"graph": graph.getIdentifier(), "viewers": results}

    def set_shape_splatter_sdf(self, node_id, nodes, output, graph_identifier=None,
                               bounding_frame_size=None):
        """Switch a Shape splatter v2 node to 'SDF Function' shapes and build its
        pattern_sdf_function. bounding_frame_size: [x, y, z] (sample uses [0.6, 0.6, 1])."""
        graph = self._resolve_graph(graph_identifier)
        node = self._find_node(graph, node_id)
        params = {"shape_type": {"value": 1, "type": "int"}}
        if bounding_frame_size is not None:
            params["sdf_bounding_frame_size"] = {"value": list(bounding_frame_size), "type": "float3"}
        set_res = self._set_node_params(node, params)
        fg_res = self.build_function_graph(node_id, "pattern_sdf_function", nodes, output,
                                           graph_identifier=graph.getIdentifier())
        fg_res["parameters"] = set_res
        return fg_res
