"""
Shared SD helpers: application objects, package/graph/node lookup,
value conversion, parameter setting, output usages and material model.
"""

import os
import sd
from .common import (
    ColorRGBA,
    DEFAULT_MATERIAL_MODEL_SD16,
    OPENPBR_ALIAS,
    OPENPBR_USAGES,
    OUTPUT_USAGES,
    SDError,
    SDPropertyCategory,
    SDPropertyInheritanceMethod,
    SDTypeUsage,
    SDUsage,
    SDValueArray,
    SDValueBool,
    SDValueColorRGBA,
    SDValueFloat,
    SDValueFloat2,
    SDValueFloat3,
    SDValueFloat4,
    SDValueInt,
    SDValueInt2,
    SDValueInt3,
    SDValueInt4,
    SDValueString,
    SDValueUsage,
    _SYSTEM_PARAMS,
    _coerce_type,
    _infer_type,
    _log,
    _sanitize_identifier,
    _sd_major,
    _usage_key,
    float2,
    float3,
    float4,
    int2,
    int3,
    int4,
)


class SDContextMixin(object):
    """Mixed into CommandHandler."""

    def _app(self):
        return sd.getContext().getSDApplication()

    def _pkg_mgr(self):
        return self._app().getPackageMgr()

    def _ui_mgr(self):
        return self._app().getUIMgr()

    def _get_sd_version(self):
        try:
            return self._app().getVersion()
        except SDError:
            return "unknown"

    def _usages_supported(self):
        # SDUsage.sNew() was reported to hang SD 15.0.3; verified OK on 16.0.5.
        if SDUsage is None:
            return False
        if os.environ.get("SD_MCP_FORCE_USAGES") == "1":
            return True
        return _sd_major() >= 16

    @staticmethod
    def _graph_material_model(graph):
        try:
            v = graph.getAnnotationPropertyValueFromId("material_model")
            return v.get() if v is not None else ""
        except SDError:
            return ""

    @staticmethod
    def _unique_output_identifier(graph, ident, node):
        taken = set()
        try:
            for n in graph.getNodes():
                if n.getIdentifier() == node.getIdentifier():
                    continue
                if n.getDefinition().getId() == "sbs::compositing::output":
                    v = n.getAnnotationPropertyValueFromId("identifier")
                    if v is not None:
                        taken.add(v.get())
        except SDError:
            pass
        if ident not in taken:
            return ident
        i = 1
        while "{}_{}".format(ident, i) in taken:
            i += 1
        return "{}_{}".format(ident, i)

    def _apply_output_usage(self, node, usage, graph=None):
        """Set the output node's usage(s) and identifier so the 3D view and the
        graph's material model pick it up. With an OpenPBR graph the output gets
        the OpenPBR identifier and usages (+ legacy alias), exactly like SD 16's
        OpenPBR template; otherwise the legacy metallic/roughness usage.
        Returns the list of usage names that were set, or None."""
        if not usage or not self._usages_supported():
            return None
        key = _usage_key(usage)
        model = self._graph_material_model(graph) if graph is not None else ""
        if model.startswith("openpbr") and key in OPENPBR_ALIAS:
            ident = OPENPBR_ALIAS[key]
            names = OPENPBR_USAGES[ident]
        elif key in OUTPUT_USAGES:
            ident, name = OUTPUT_USAGES[key]
            names = [name]
        else:
            ident, names = _sanitize_identifier(usage).lower(), [usage]
        try:
            arr = SDValueArray.sNew(SDTypeUsage.sNew(), 0)
            for name in names:
                arr.pushBack(SDValueUsage.sNew(SDUsage.sNew(name, "RGBA", "")))
            node.setAnnotationPropertyValueFromId("usages", arr)
        except SDError as e:
            _log("Warning: could not set usage '{}': {}".format(usage, e))
            return None
        try:
            if graph is not None:
                ident = self._unique_output_identifier(graph, ident, node)
            node.setAnnotationPropertyValueFromId("identifier", SDValueString.sNew(ident))
        except SDError:
            pass
        return names

    def _new_output_node(self, graph, usage=None, label=None):
        node = graph.newNode("sbs::compositing::output")
        if not node:
            return None
        try:
            node.setAnnotationPropertyValueFromId(
                "label", SDValueString.sNew(label or usage or "output"))
        except SDError:
            pass
        self._apply_output_usage(node, usage, graph)
        return node

    def _apply_material_model(self, graph, material_model=None):
        """material_model: None = SD default for this version ('openpbr_v1_1' on
        SD 16+), '' = leave Undefined, or an identifier from list_material_models."""
        if _sd_major() < 16:
            return None
        if material_model is None:
            material_model = DEFAULT_MATERIAL_MODEL_SD16
        if not material_model:
            return ""
        try:
            graph.setAnnotationPropertyValueFromId(
                "material_model", SDValueString.sNew(material_model))
            return material_model
        except SDError as e:
            _log("Warning: could not set material model '{}': {}".format(material_model, e))
            return None

    def list_material_models(self):
        """SD 16+: material models available for graphs (OpenPBR, ASM, USD...)."""
        try:
            from sd.api.sdmaterialmodeldescription import SDMaterialModelDescription
        except SDError:
            return {"supported": False, "sd_version": self._get_sd_version(),
                    "models": []}
        models = []
        for m in SDMaterialModelDescription.sGetAllMaterialModelDescriptions():
            try:
                models.append({"identifier": m.getIdentifier().get(),
                               "label": m.getLabel().get()})
            except SDError:
                pass
        return {"supported": True, "default": DEFAULT_MATERIAL_MODEL_SD16,
                "models": models}

    def _resolve_package(self, package_index=0, package_path=None):
        pkgs = list(self._pkg_mgr().getUserPackages())
        if package_path:
            for pkg in pkgs:
                if pkg.getFilePath() == package_path:
                    return pkg
            raise ValueError("Package '{}' not found.".format(package_path))
        if not pkgs:
            raise ValueError("No user packages loaded. Open a .sbs file first.")
        if package_index < 0:
            raise ValueError("package_index must be >= 0 (got {}).".format(package_index))
        if package_index >= len(pkgs):
            raise ValueError("Package index {} out of range (have {}).".format(
                package_index, len(pkgs)))
        return pkgs[package_index]

    def _resolve_graph(self, graph_identifier=None):
        if graph_identifier:
            for pkg in list(self._pkg_mgr().getUserPackages()):
                for res in list(pkg.getChildrenResources(False)):
                    try:
                        if res.getIdentifier() == graph_identifier:
                            return res
                    except SDError:
                        continue
            raise ValueError("Graph '{}' not found.".format(graph_identifier))

        try:
            g = self._ui_mgr().getCurrentGraph()
            if g is not None:
                return g
        except SDError:
            pass

        for pkg in list(self._pkg_mgr().getUserPackages()):
            for res in list(pkg.getChildrenResources(False)):
                try:
                    if "SDSBSCompGraph" in res.getClassName():
                        return res
                except SDError:
                    continue
        raise ValueError(
            "No graph available. Open a package/graph in SD, or pass graph_identifier.")

    def _find_node(self, graph, node_id):
        try:
            n = graph.getNodeFromId(node_id)
            if n is not None:
                return n
        except SDError:
            pass
        for node in list(graph.getNodes()):
            if node.getIdentifier() == node_id:
                return node
        raise ValueError("Node '{}' not found in graph '{}'.".format(
            node_id, graph.getIdentifier()))

    def _get_node_def_id(self, node):
        try:
            defn = node.getDefinition()
            if defn is not None:
                return defn.getId()
        except SDError:
            pass
        return "unknown"

    def _is_instance_node(self, node):
        defn_id = self._get_node_def_id(node)
        return (defn_id == "unknown" or
                defn_id.startswith("pkg://") or
                "?dependency=" in defn_id)

    def _get_node_pos(self, node):
        try:
            p = node.getPosition()
            return [p.x, p.y]
        except SDError:
            return [0.0, 0.0]

    def _make_sd_value(self, value_type, value):
        t = value_type.lower()
        if t == "float":
            return SDValueFloat.sNew(float(value))
        if t == "int":
            return SDValueInt.sNew(int(value))
        if t == "bool":
            return SDValueBool.sNew(bool(value))
        if t == "string":
            return SDValueString.sNew(str(value))
        if t == "float2":
            v = value if isinstance(value, (list, tuple)) else [value, value]
            return SDValueFloat2.sNew(float2(float(v[0]), float(v[1])))
        if t == "float3":
            v = value if isinstance(value, (list, tuple)) else [value] * 3
            return SDValueFloat3.sNew(float3(float(v[0]), float(v[1]), float(v[2])))
        if t == "float4":
            v = value if isinstance(value, (list, tuple)) else [value] * 4
            return SDValueFloat4.sNew(float4(
                float(v[0]), float(v[1]), float(v[2]), float(v[3])))
        if t in ("color", "colorrgba"):
            v = value if isinstance(value, (list, tuple)) else [value] * 3 + [1.0]
            a = float(v[3]) if len(v) > 3 else 1.0
            return SDValueColorRGBA.sNew(ColorRGBA(
                float(v[0]), float(v[1]), float(v[2]), a))
        if t == "int2":
            v = value if isinstance(value, (list, tuple)) else [value, value]
            return SDValueInt2.sNew(int2(int(v[0]), int(v[1])))
        if t == "int3":
            v = value if isinstance(value, (list, tuple)) else [value] * 3
            return SDValueInt3.sNew(int3(int(v[0]), int(v[1]), int(v[2])))
        if t == "int4":
            v = value if isinstance(value, (list, tuple)) else [value] * 4
            return SDValueInt4.sNew(int4(int(v[0]), int(v[1]), int(v[2]), int(v[3])))
        raise ValueError(
            "Unknown value_type '{}'. Valid: float, int, bool, string, "
            "float2, float3, float4, color, int2, int3, int4".format(value_type))

    def _serialize_sd_value(self, val):
        if val is None:
            return None
        try:
            raw = val.get()
        except SDError:
            return str(val)
        if hasattr(raw, 'x') and hasattr(raw, 'y'):
            d = {"x": raw.x, "y": raw.y}
            if hasattr(raw, 'z'):
                d["z"] = raw.z
            if hasattr(raw, 'w'):
                d["w"] = raw.w
            return d
        if hasattr(raw, 'r') and hasattr(raw, 'g'):
            return {"r": raw.r, "g": raw.g, "b": raw.b, "a": raw.a}
        if hasattr(raw, 'getSize') and hasattr(raw, 'getItem'):
            items = []
            try:
                for i in range(raw.getSize()):
                    item = raw.getItem(i)
                    items.append(str(item.get()) if hasattr(item, 'get') else str(item))
            except SDError:
                return str(raw)
            return items
        return str(raw)

    def _set_node_params(self, node, params):
        """Apply parameter dict to a node. Type-safe: reads actual SD property type
        and coerces before setting to prevent SD 15 silent crashes."""
        if not params:
            return {}
        results = {}

        # Build property type maps: id -> SDType id string
        input_type_map  = {}   # param_id -> sd_type_id
        annot_type_map  = {}
        try:
            for p in list(node.getProperties(SDPropertyCategory.Input)):
                pid = p.getId()
                try:
                    t = p.getType()
                    input_type_map[pid] = t.getId() if t else ""
                except SDError:
                    input_type_map[pid] = ""
        except SDError:
            pass
        try:
            for p in list(node.getProperties(SDPropertyCategory.Annotation)):
                pid = p.getId()
                try:
                    t = p.getType()
                    annot_type_map[pid] = t.getId() if t else ""
                except SDError:
                    annot_type_map[pid] = ""
        except SDError:
            pass

        for param_id, param_spec in params.items():
            # System params ($outputsize, $format, $randomseed...): switch the
            # inheritance to Absolute first, otherwise the value is ignored
            # (or read as "relative to parent", see _set_absolute_output_size).
            is_system = param_id.startswith("$")
            if is_system and param_id in input_type_map and SDPropertyInheritanceMethod is not None:
                try:
                    prop = node.getPropertyFromId(param_id, SDPropertyCategory.Input)
                    node.setPropertyInheritanceMethod(prop, SDPropertyInheritanceMethod.Absolute)
                except SDError as e:
                    results[param_id] = "set_failed: inheritance: {}".format(e)
                    continue
            try:
                if isinstance(param_spec, dict) and "value" in param_spec:
                    pval  = param_spec["value"]
                    ptype = param_spec.get("type", _infer_type(pval))
                else:
                    pval  = param_spec
                    ptype = _infer_type(pval)

                # Coerce ptype to match actual SD property type (prevents silent crash)
                sd_type_id = (input_type_map.get(param_id)
                              or annot_type_map.get(param_id) or "")
                ptype = _coerce_type(ptype, pval, sd_type_id)

                if param_id not in input_type_map and param_id not in annot_type_map:
                    results[param_id] = "unknown_parameter"
                    continue
                sd_val = self._make_sd_value(ptype, pval)
                set_ok, last_err = False, None
                if param_id in input_type_map:
                    try:
                        node.setInputPropertyValueFromId(param_id, sd_val)
                        set_ok = True
                    except SDError as e:
                        last_err = e
                if not set_ok and param_id in annot_type_map:
                    try:
                        node.setAnnotationPropertyValueFromId(param_id, sd_val)
                        set_ok = True
                    except SDError as e:
                        last_err = e
                results[param_id] = "ok" if set_ok else "set_failed: {}".format(last_err)
            except SDError as e:
                results[param_id] = "error: {}".format(e)
        return results

    @staticmethod
    def _param_issues(alias, node, results):
        """Non-'ok' parameter results as a list of issues; unknown parameters
        include the node's real parameter ids so the caller can fix the name."""
        issues = []
        for pid, status in (results or {}).items():
            if status == "ok":
                continue
            item = {"alias": alias, "parameter": pid, "status": status}
            if status == "unknown_parameter":
                try:
                    item["available"] = sorted(
                        p.getId() for p in node.getProperties(SDPropertyCategory.Input)
                        if not p.isConnectable() and not p.getId().startswith("$"))[:60]
                except SDError:
                    pass
            issues.append(item)
        return issues

    def _safe_connect(self, graph, from_node, from_out, to_node, to_in):
        """Connect nodes with port validation. Returns True on success."""
        out_ids = set()
        in_ids  = set()
        try:
            for p in list(from_node.getProperties(SDPropertyCategory.Output)):
                out_ids.add(p.getId())
        except SDError:
            pass
        try:
            for p in list(to_node.getProperties(SDPropertyCategory.Input)):
                pid = p.getId()
                if pid not in _SYSTEM_PARAMS:
                    in_ids.add(pid)
        except SDError:
            pass

        if out_ids and from_out not in out_ids:
            raise ValueError(
                "Output port '{}' not found on node '{}'. "
                "Available: {}".format(from_out, from_node.getIdentifier(), sorted(out_ids)))
        if in_ids and to_in not in in_ids:
            raise ValueError(
                "Input port '{}' not found on node '{}'. "
                "Available: {}".format(to_in, to_node.getIdentifier(), sorted(in_ids)))

        conn = from_node.newPropertyConnectionFromId(from_out, to_node, to_in)
        if conn is None:
            raise RuntimeError(
                "Connection failed: {}.{} -> {}.{}".format(
                    from_node.getIdentifier(), from_out,
                    to_node.getIdentifier(), to_in))
        return True

    def _set_absolute_output_size(self, graph, width_log2, height_log2):
        """Set $outputsize as an ABSOLUTE size. New graphs default to
        'Relative to parent', where (11, 11) means parent size x 2^11 and SD
        clamps to 8192x8192 — so the inheritance method must be switched."""
        prop = graph.getPropertyFromId("$outputsize", SDPropertyCategory.Input)
        if SDPropertyInheritanceMethod is not None and prop is not None:
            try:
                graph.setPropertyInheritanceMethod(prop, SDPropertyInheritanceMethod.Absolute)
            except SDError as e:
                _log("Warning: could not set $outputsize to Absolute: {}".format(e))
        graph.setInputPropertyValueFromId(
            "$outputsize", SDValueInt2.sNew(int2(int(width_log2), int(height_log2))))
