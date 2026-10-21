"""
Scene / package / graph tools and diagnostics.
"""

import os
import sys
from .common import (
    PLUGIN_VERSION,
    SDError,
    SDPropertyCategory,
    SDSBSCompGraph,
    _sanitize_identifier,
    _sd_major,
)
from .transport import (
    _Invoker,
    _QT_BINDING_USED,
    _pyside_path,
)


class SceneToolsMixin(object):
    """Mixed into CommandHandler."""

    def get_scene_info(self):
        pkg_mgr = self._pkg_mgr()
        try:
            current_graph = self._ui_mgr().getCurrentGraph()
            current_graph_id = current_graph.getIdentifier() if current_graph else None
        except SDError:
            current_graph = None
            current_graph_id = None

        pkg_list = []
        for pkg in list(pkg_mgr.getUserPackages()):
            try:
                graphs = []
                for res in list(pkg.getChildrenResources(False)):
                    try:
                        cname = res.getClassName()
                        rid   = res.getIdentifier()
                        nc    = 0
                        if "CompGraph" in cname or "SDGraph" in cname:
                            try:
                                nc = len(list(res.getNodes()))
                            except SDError:
                                pass
                        graphs.append({"identifier": rid, "type": cname, "node_count": nc})
                    except SDError:
                        pass
                pkg_list.append({"file_path": pkg.getFilePath(), "graphs": graphs})
            except SDError as e:
                pkg_list.append({"error": str(e)})

        current_nc = 0
        if current_graph is not None:
            try:
                current_nc = len(list(current_graph.getNodes()))
            except SDError:
                pass

        return {
            "packages": pkg_list,
            "package_count": len(pkg_list),
            "current_graph": current_graph_id,
            "current_graph_node_count": current_nc,
            "sd_version": self._get_sd_version(),
            "plugin_version": ".".join(map(str, PLUGIN_VERSION)),
        }

    def create_package(self, file_path=None):
        pkg = self._pkg_mgr().newUserPackage()
        pkgs = list(self._pkg_mgr().getUserPackages())
        idx = next((i for i, p in enumerate(pkgs)
                    if p.getUID() == pkg.getUID()), len(pkgs) - 1) if hasattr(pkg, "getUID") \
            else len(pkgs) - 1
        return {
            "package_index": idx,
            "file_path": pkg.getFilePath(),
            "message": "New package created. Use save_package to save it.",
        }

    def create_graph(self, package_index=0, graph_name="MCP_Graph", package_path=None,
                     material_model=None, output_size_log2=11):
        safe_name = _sanitize_identifier(graph_name)
        pkg = self._resolve_package(package_index, package_path)
        new_graph = SDSBSCompGraph.sNew(pkg)
        new_graph.setIdentifier(safe_name)
        actual_id = new_graph.getIdentifier()
        mm = self._apply_material_model(new_graph, material_model)
        # SD creates graphs at 256x256 (relative to parent). Flood Fill /
        # distance-based library nodes misbehave at that size, so default to an
        # absolute 2048x2048 like the builders do. 0 / None keeps SD's default.
        size = None
        if output_size_log2:
            self._set_absolute_output_size(new_graph, output_size_log2, output_size_log2)
            size = "{0}x{0}".format(2 ** int(output_size_log2))
        return {
            "output_size": size or "SD default (256x256, relative to parent)",
            "material_model": mm,
            "identifier": actual_id,
            "requested_name": graph_name,
            "sanitized_name": safe_name,
            "type": new_graph.getClassName(),
            "package": pkg.getFilePath(),
        }

    def delete_graph(self, graph_identifier, package_index=0):
        pkg = self._resolve_package(package_index)
        for res in list(pkg.getChildrenResources(False)):
            try:
                if res.getIdentifier() == graph_identifier:
                    res.delete()
                    return {"deleted": graph_identifier}
            except SDError:
                pass
        raise ValueError("Graph '{}' not found.".format(graph_identifier))

    def open_graph(self, graph_identifier):
        graph = self._resolve_graph(graph_identifier)
        try:
            self._ui_mgr().openResourceInEditor(graph)
            return {"opened": graph_identifier, "success": True}
        except SDError as e:
            return {"opened": graph_identifier, "warning": str(e)}

    def get_graph_info(self, graph_identifier=None, node_limit=100, include_connections=True):
        graph = self._resolve_graph(graph_identifier)
        all_nodes = list(graph.getNodes())
        total = len(all_nodes)
        to_detail = all_nodes[:node_limit] if node_limit > 0 else []

        node_list = []
        for node in to_detail:
            try:
                info = {
                    "identifier": node.getIdentifier(),
                    "definition":  self._get_node_def_id(node),
                    "position":    self._get_node_pos(node),
                    "connections": [],
                }
                if include_connections:
                    try:
                        for prop in list(node.getProperties(SDPropertyCategory.Input)):
                            pid   = prop.getId()
                            conns = node.getPropertyConnections(prop)
                            if conns is None:
                                continue
                            for conn in list(conns):
                                try:
                                    sn = conn.getInputPropertyNode()
                                    sp = conn.getInputProperty()
                                    if sn and sp:
                                        info["connections"].append({
                                            "input":       pid,
                                            "from_node":   sn.getIdentifier(),
                                            "from_output": sp.getId(),
                                        })
                                except SDError:
                                    pass
                    except SDError:
                        pass
                node_list.append(info)
            except SDError:
                pass

        return {
            "identifier":  graph.getIdentifier(),
            "node_count":  total,
            "nodes":       node_list,
            "truncated":   total > node_limit,
            "node_limit":  node_limit,
        }

    def save_package(self, package_index=0, file_path=None, package_path=None):
        pkg_mgr = self._pkg_mgr()
        pkg = self._resolve_package(package_index, package_path)
        if file_path:
            target_dir = os.path.dirname(os.path.abspath(file_path))
            if not os.path.exists(target_dir):
                try:
                    os.makedirs(target_dir, exist_ok=True)
                except SDError as e:
                    raise ValueError("Cannot create directory '{}': {}".format(target_dir, e))
            pkg_mgr.savePackageAs(pkg, file_path)
            return {"saved_to": file_path}
        else:
            current_path = pkg.getFilePath()
            if not current_path:
                raise ValueError(
                    "Package has no file path. Use file_path parameter to specify.")
            pkg_mgr.savePackage(pkg)
            return {"saved_to": current_path}

    def graph_snapshot(self, graph_identifier=None):
        """Export full graph structure as JSON snapshot (nodes + connections)."""
        graph = self._resolve_graph(graph_identifier)
        all_nodes = list(graph.getNodes())
        snapshot = {
            "graph_identifier": graph.getIdentifier(),
            "node_count": len(all_nodes),
            "nodes": [],
            "connections": [],
        }
        for node in all_nodes:
            nid  = node.getIdentifier()
            defn = self._get_node_def_id(node)
            pos  = self._get_node_pos(node)
            snapshot["nodes"].append({
                "id": nid, "definition": defn, "position": pos,
                "is_library": self._is_instance_node(node),
            })
            try:
                for prop in list(node.getProperties(SDPropertyCategory.Input)):
                    pid   = prop.getId()
                    conns = node.getPropertyConnections(prop)
                    if conns is None:
                        continue
                    for conn in list(conns):
                        try:
                            sn = conn.getInputPropertyNode()
                            sp = conn.getInputProperty()
                            if sn and sp:
                                snapshot["connections"].append({
                                    "from_node": sn.getIdentifier(),
                                    "from_output": sp.getId(),
                                    "to_node": nid,
                                    "to_input": pid,
                                })
                        except SDError:
                            pass
            except SDError:
                pass
        return snapshot

    def diagnostic(self):
        """Full health check of SD environment."""
        results = {}
        # SD running?
        try:
            ver = self._get_sd_version()
            results["sd_running"] = True
            results["sd_version"] = ver
        except SDError as e:
            results["sd_running"] = False
            results["sd_version_error"] = str(e)

        results["python_version"] = sys.version.split()[0]
        results["sd_major"] = _sd_major()
        results["output_usages_enabled"] = self._usages_supported()
        # Qt binding
        results["qt_binding"] = _QT_BINDING_USED or "NONE"
        results["pyside_path"] = _pyside_path or "native (no injection needed)"

        # Invoker
        inv = _Invoker.instance()
        results["qt_invoker_ok"] = inv is not None

        # Packages
        try:
            pkgs = list(self._pkg_mgr().getUserPackages())
            results["user_packages"] = len(pkgs)
            results["package_files"] = [p.getFilePath() for p in pkgs]
        except SDError as e:
            results["packages_error"] = str(e)

        # Library cache
        results["library_cache_entries"] = len(self._lib_url_cache)
        try:
            results["library_index_graphs"] = len(self._lib_index())
            results["library_dirs"] = [
                {"path": r["path"], "source": r["source"], "graphs": r.get("graphs")}
                for r in self.list_library_paths()["roots"] if r.get("enabled")]
        except SDError as e:
            results["library_index_error"] = str(e)

        # Current graph
        try:
            g = self._ui_mgr().getCurrentGraph()
            if g:
                results["current_graph"] = g.getIdentifier()
                results["current_graph_nodes"] = len(list(g.getNodes()))
            else:
                results["current_graph"] = None
        except SDError as e:
            results["current_graph_error"] = str(e)

        return results
