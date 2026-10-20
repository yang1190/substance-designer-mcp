"""
Node, connection and parameter tools.
"""

from .common import (
    ATOMIC_PORTS,
    SDError,
    SDPropertyCategory,
    SDPropertyInheritanceMethod,
    SDSBSCompGraph,
    SDValueString,
    _SYSTEM_PARAMS,
    _coerce_type,
    _log,
    float2,
)


class NodeToolsMixin(object):
    """Mixed into CommandHandler."""

    def list_node_definitions(self, filter_text="", graph_identifier=None, limit=500):
        temp_pkg = None
        try:
            if graph_identifier:
                graph = self._resolve_graph(graph_identifier)
            else:
                graph = None
                try:
                    graph = self._ui_mgr().getCurrentGraph()
                except SDError:
                    pass
                if not graph:
                    pkgs = list(self._pkg_mgr().getUserPackages())
                    if pkgs:
                        rs = list(pkgs[0].getChildrenResources(False))
                        for r in rs:
                            try:
                                if "SDSBSCompGraph" in r.getClassName():
                                    graph = r
                                    break
                            except SDError:
                                pass
                if not graph:
                    temp_pkg = self._pkg_mgr().newUserPackage()
                    graph = SDSBSCompGraph.sNew(temp_pkg)
                    graph.setIdentifier("_TempDefQuery")

            definitions = graph.getNodeDefinitions()
            result = []
            for defn in list(definitions):
                try:
                    did = defn.getId()
                    if filter_text and filter_text.lower() not in did.lower():
                        continue
                    result.append(did)
                    if len(result) >= limit:
                        break
                except SDError:
                    pass

            return {
                "count":       len(result),
                "definitions": result,
                "truncated":   len(result) >= limit,
                "filter":      filter_text,
            }
        finally:
            if temp_pkg is not None:
                try:
                    self._pkg_mgr().unloadUserPackage(temp_pkg)
                except SDError:
                    pass

    def create_node(self, definition_id, graph_identifier=None, position=None):
        graph = self._resolve_graph(graph_identifier)
        # Validate before calling newNode — unknown defs HANG SD 15
        try:
            known = {d.getId() for d in list(graph.getNodeDefinitions())}
            if definition_id not in known:
                raise ValueError(
                    "Unknown definition '{}'. "
                    "Library nodes require create_instance_node with pkg:// URL.".format(
                        definition_id))
        except ValueError:
            raise
        except SDError:
            pass

        node = graph.newNode(definition_id)
        if not node:
            raise RuntimeError("newNode('{}') returned None.".format(definition_id))
        if position and len(position) >= 2:
            node.setPosition(float2(float(position[0]), float(position[1])))
        return {
            "node_id":    node.getIdentifier(),
            "definition": self._get_node_def_id(node),
            "position":   list(position) if position else [0.0, 0.0],
        }

    def create_instance_node(self, resource_url, graph_identifier=None, position=None):
        graph = self._resolve_graph(graph_identifier)
        node = self._new_library_node(graph, resource_url, position)
        url = resource_url
        try:
            url = node.getReferencedResource().getUrl()
        except SDError:
            pass
        return {
            "node_id":      node.getIdentifier(),
            "resource_url": url,
            "position":     list(position) if position else [0.0, 0.0],
            "note":         "Call get_node_info to find exact port IDs before connecting.",
        }

    def create_output_node(self, usage="baseColor", label=None,
                           graph_identifier=None, position=None):
        if label is None:
            label = usage
        graph = self._resolve_graph(graph_identifier)
        node = graph.newNode('sbs::compositing::output')
        if not node:
            raise RuntimeError("Failed to create output node.")
        if position and len(position) >= 2:
            node.setPosition(float2(float(position[0]), float(position[1])))
        label_set = False
        try:
            node.setAnnotationPropertyValueFromId("label", SDValueString.sNew(label))
            label_set = True
        except SDError as e:
            _log("Warning: label set failed: {}".format(e))
        usage_set = self._apply_output_usage(node, usage, graph)
        return {
            "usage_set":  usage_set,
            "node_id":    node.getIdentifier(),
            "definition": "sbs::compositing::output",
            "usage":      usage,
            "label":      label,
            "label_set":  label_set,
        }

    def delete_node(self, node_id, graph_identifier=None):
        graph = self._resolve_graph(graph_identifier)
        node  = self._find_node(graph, node_id)
        graph.deleteNode(node)
        return {"deleted": node_id}

    def move_node(self, node_id, position, graph_identifier=None):
        graph = self._resolve_graph(graph_identifier)
        node  = self._find_node(graph, node_id)
        node.setPosition(float2(float(position[0]), float(position[1])))
        return {"node_id": node_id, "position": position}

    def duplicate_node(self, node_id, offset=None, graph_identifier=None):
        graph = self._resolve_graph(graph_identifier)
        node  = self._find_node(graph, node_id)
        if self._is_instance_node(node):
            raise ValueError(
                "Cannot duplicate library node '{}' via duplicate_node. "
                "Use create_instance_node with the same resource_url.".format(node_id))
        defn_id = self._get_node_def_id(node)
        pos     = self._get_node_pos(node)
        off     = offset or [100, 0]
        new_node = graph.newNode(defn_id)
        if not new_node:
            raise RuntimeError("Failed to duplicate node '{}'.".format(node_id))
        new_pos = [pos[0] + off[0], pos[1] + off[1]]
        new_node.setPosition(float2(float(new_pos[0]), float(new_pos[1])))
        return {
            "original_node_id": node_id,
            "new_node_id":      new_node.getIdentifier(),
            "definition":       defn_id,
            "position":         new_pos,
        }

    def get_node_info(self, node_id, graph_identifier=None):
        graph = self._resolve_graph(graph_identifier)
        node  = self._find_node(graph, node_id)

        inputs = []
        try:
            for prop in list(node.getProperties(SDPropertyCategory.Input)):
                pid = prop.getId()
                if pid in _SYSTEM_PARAMS:
                    continue
                info = {"id": pid}
                try:
                    val_obj = node.getPropertyValue(prop)
                    if val_obj is not None:
                        info["value"] = self._serialize_sd_value(val_obj)
                except SDError:
                    pass
                try:
                    conns = node.getPropertyConnections(prop)
                    if conns is not None:
                        cl = list(conns)
                        if cl:
                            info["connected_from"] = []
                            for conn in cl:
                                try:
                                    sn = conn.getInputPropertyNode()
                                    sp = conn.getInputProperty()
                                    if sn and sp:
                                        info["connected_from"].append(
                                            "{}.{}".format(sn.getIdentifier(), sp.getId()))
                                except SDError:
                                    pass
                except SDError:
                    pass
                inputs.append(info)
        except SDError:
            pass

        outputs = []
        try:
            for prop in list(node.getProperties(SDPropertyCategory.Output)):
                outputs.append({"id": prop.getId()})
        except SDError:
            pass

        annotations = []
        try:
            for prop in list(node.getProperties(SDPropertyCategory.Annotation)):
                pid = prop.getId()
                info = {"id": pid}
                try:
                    val_obj = node.getPropertyValue(prop)
                    if val_obj is not None:
                        info["value"] = self._serialize_sd_value(val_obj)
                except SDError:
                    pass
                annotations.append(info)
        except SDError:
            pass

        is_lib = self._is_instance_node(node)
        return {
            "node_id":        node_id,
            "definition":     self._get_node_def_id(node),
            "is_library_node": is_lib,
            "position":       self._get_node_pos(node),
            "inputs":         inputs,
            "outputs":        outputs,
            "annotations":    annotations,
            "note": (
                "Library node: use output IDs listed above, NOT 'unique_filter_output'"
                if is_lib else ""
            ),
        }

    def connect_nodes(self, from_node_id, to_node_id,
                      from_output="unique_filter_output",
                      to_input="input1",
                      graph_identifier=None):
        graph     = self._resolve_graph(graph_identifier)
        from_node = self._find_node(graph, from_node_id)
        to_node   = self._find_node(graph, to_node_id)
        self._safe_connect(graph, from_node, from_output, to_node, to_input)
        return {
            "from_node":   from_node_id,
            "from_output": from_output,
            "to_node":     to_node_id,
            "to_input":    to_input,
            "success":     True,
        }

    def disconnect_nodes(self, node_id, input_id, graph_identifier=None):
        graph = self._resolve_graph(graph_identifier)
        node  = self._find_node(graph, node_id)
        prop  = node.getPropertyFromId(input_id, SDPropertyCategory.Input)
        if not prop:
            raise ValueError(
                "Property '{}' not found on node '{}'.".format(input_id, node_id))
        node.deletePropertyConnections(prop)
        return {"disconnected": "{}:{}".format(node_id, input_id)}

    def smart_connect(self, from_node_id, to_node_id,
                      from_output=None, to_input=None,
                      graph_identifier=None):
        """
        Auto-detect port names if not specified.
        Uses ATOMIC_PORTS registry for known node types.
        Falls back to get_node_info for library nodes.
        """
        graph     = self._resolve_graph(graph_identifier)
        from_node = self._find_node(graph, from_node_id)
        to_node   = self._find_node(graph, to_node_id)

        from_defn = self._get_node_def_id(from_node)
        to_defn   = self._get_node_def_id(to_node)

        # Determine from_output
        if not from_output:
            if from_defn in ATOMIC_PORTS:
                outs = ATOMIC_PORTS[from_defn]["outputs"]
                from_output = outs[0] if outs else "unique_filter_output"
            else:
                # Library node — query
                try:
                    outs = [p.getId() for p in
                            list(from_node.getProperties(SDPropertyCategory.Output))]
                    from_output = outs[0] if outs else "unique_filter_output"
                except SDError:
                    from_output = "unique_filter_output"

        # Determine to_input
        if not to_input:
            if to_defn in ATOMIC_PORTS:
                ins = ATOMIC_PORTS[to_defn]["inputs"]
                to_input = ins[0] if ins else "input1"
            else:
                try:
                    ins = [p.getId() for p in
                           list(to_node.getProperties(SDPropertyCategory.Input))
                           if p.getId() not in _SYSTEM_PARAMS]
                    to_input = ins[0] if ins else "input1"
                except SDError:
                    to_input = "input1"

        self._safe_connect(graph, from_node, from_output, to_node, to_input)
        return {
            "from_node":   from_node_id,
            "from_output": from_output,
            "to_node":     to_node_id,
            "to_input":    to_input,
            "success":     True,
        }

    def set_parameter(self, node_id, parameter_id, value, value_type="float",
                      graph_identifier=None):
        graph = self._resolve_graph(graph_identifier)
        node  = self._find_node(graph, node_id)
        # Coerce to the property's real type (a float value on an enum/int
        # property crashes SD silently) — same rule as _set_node_params.
        sd_type_id = ""
        try:
            prop = node.getPropertyFromId(parameter_id, SDPropertyCategory.Input) or \
                node.getPropertyFromId(parameter_id, SDPropertyCategory.Annotation)
            if prop is not None:
                sd_type_id = prop.getType().getId()
                if parameter_id.startswith("$") and SDPropertyInheritanceMethod is not None:
                    node.setPropertyInheritanceMethod(prop, SDPropertyInheritanceMethod.Absolute)
        except SDError:
            pass
        requested_type = value_type
        value_type = _coerce_type(value_type, value, sd_type_id)
        sd_value = self._make_sd_value(value_type, value)

        input_ids  = set()
        annot_ids  = set()
        try:
            for p in list(node.getProperties(SDPropertyCategory.Input)):
                input_ids.add(p.getId())
        except SDError:
            pass
        try:
            for p in list(node.getProperties(SDPropertyCategory.Annotation)):
                annot_ids.add(p.getId())
        except SDError:
            pass

        if (input_ids or annot_ids) and \
           parameter_id not in input_ids and parameter_id not in annot_ids:
            all_ids = sorted(input_ids | annot_ids)
            raise ValueError(
                "Property '{}' not found on node '{}'. Available: {}".format(
                    parameter_id, node_id, all_ids))

        set_ok = False
        last_err = None
        for setter in [node.setInputPropertyValueFromId,
                       node.setAnnotationPropertyValueFromId]:
            try:
                setter(parameter_id, sd_value)
                set_ok = True
                break
            except SDError as e:
                last_err = e

        if not set_ok:
            raise RuntimeError("Failed to set '{}' on node '{}': {}".format(
                parameter_id, node_id, last_err))

        return {
            "node_id":      node_id,
            "parameter_id": parameter_id,
            "value":        value,
            "value_type":   value_type,
            "requested_type": requested_type,
            "property_type": sd_type_id,
        }

    def set_graph_output_size(self, width_log2=11, height_log2=11, graph_identifier=None):
        graph = self._resolve_graph(graph_identifier)
        self._set_absolute_output_size(graph, width_log2, height_log2)
        return {
            "graph":       graph.getIdentifier(),
            "width_log2":  width_log2,
            "height_log2": height_log2,
            "size":        "{}x{}".format(2 ** width_log2, 2 ** height_log2),
        }

    def arrange_nodes(self, graph_identifier=None, start_x=-1000, start_y=0,
                      node_spacing_x=200, node_spacing_y=150):
        """Lay the graph out left-to-right by data flow: each node's column is
        its longest distance from a source node, outputs end up on the right.
        Only positions change — connections are untouched (verified on SD
        16.0.5: 50 connections before/after on pro_granite, identical outputs;
        the old "destroys all connections" note was never true for this code).
        """
        graph = self._resolve_graph(graph_identifier)
        nodes = list(graph.getNodes())
        if not nodes:
            return {"graph": graph.getIdentifier(), "arranged_nodes": 0,
                    "warning": "No nodes to arrange."}
        by_id = {n.getIdentifier(): n for n in nodes}
        inputs = {nid: set() for nid in by_id}          # nid -> upstream ids
        n_conn = 0
        for n in nodes:
            try:
                for p in n.getProperties(SDPropertyCategory.Input):
                    for c in (n.getPropertyConnections(p) or []):
                        src = c.getInputPropertyNode().getIdentifier()
                        if src in by_id:
                            inputs[n.getIdentifier()].add(src)
                            n_conn += 1
            except SDError:
                pass
        depth = {}

        def _depth(nid, stack=()):
            if nid in depth:
                return depth[nid]
            if nid in stack:          # cycle guard (should not happen in SD graphs)
                return 0
            d = 0
            for up in inputs[nid]:
                d = max(d, _depth(up, stack + (nid,)) + 1)
            depth[nid] = d
            return d

        for nid in by_id:
            _depth(nid)
        # all graph outputs in the right-most column
        last = max(depth.values() or [0])
        for nid, n in by_id.items():
            try:
                if n.getDefinition().getId() == "sbs::compositing::output":
                    depth[nid] = last
            except SDError:
                pass
        columns = {}
        for nid in sorted(by_id, key=lambda i: (depth[i], by_id[i].getPosition().y)):
            columns.setdefault(depth[nid], []).append(nid)
        for d, ids in columns.items():
            y0 = float(start_y) - (len(ids) - 1) * node_spacing_y / 2.0
            for row, nid in enumerate(ids):
                try:
                    by_id[nid].setPosition(float2(float(start_x) + d * node_spacing_x,
                                                  y0 + row * node_spacing_y))
                except SDError:
                    pass
        return {"graph": graph.getIdentifier(), "arranged_nodes": len(nodes),
                "columns": len(columns), "connections_kept": n_conn}
