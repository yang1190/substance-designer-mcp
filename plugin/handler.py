"""
CommandHandler: the command table exposed over TCP, composed from the
feature mixins.
"""

import io
import sd
import traceback
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from .common import (
    SDError,
)

from .core import SDContextMixin
from .library import LibraryMixin
from .scene_tools import SceneToolsMixin
from .node_tools import NodeToolsMixin
from .builders import BuilderMixin
from .function_graphs import FunctionGraphMixin
from .render import RenderMixin


class CommandHandler(SDContextMixin, LibraryMixin, SceneToolsMixin, NodeToolsMixin,
                     BuilderMixin, FunctionGraphMixin, RenderMixin):

    def __init__(self):
        self.HANDLERS = {
            "get_scene_info":         self.get_scene_info,
            "create_package":         self.create_package,
            "create_graph":           self.create_graph,
            "delete_graph":           self.delete_graph,
            "open_graph":             self.open_graph,
            "get_graph_info":         self.get_graph_info,
            "save_package":           self.save_package,
            "graph_snapshot":         self.graph_snapshot,
            "diagnostic":             self.diagnostic,
            "list_node_definitions":  self.list_node_definitions,
            "create_node":            self.create_node,
            "create_instance_node":   self.create_instance_node,
            "create_output_node":     self.create_output_node,
            "delete_node":            self.delete_node,
            "move_node":              self.move_node,
            "duplicate_node":         self.duplicate_node,
            "get_node_info":          self.get_node_info,
            "get_library_nodes":      self.get_library_nodes,
            "list_library_paths":     self.list_library_paths,
            "add_library_path":       self.add_library_path,
            "remove_library_path":    self.remove_library_path,
            "rescan_library":         self.rescan_library,
            "connect_nodes":          self.connect_nodes,
            "disconnect_nodes":       self.disconnect_nodes,
            "set_parameter":          self.set_parameter,
            "set_graph_output_size":  self.set_graph_output_size,
            "create_batch_graph":     self.create_batch_graph,
            "build_material_graph":   self.build_material_graph,
            "build_heightmap_graph":  self.build_heightmap_graph,
            "list_recipes":           self.list_recipes,
            "get_recipe_info":        self.get_recipe_info,
            "apply_recipe":           self.apply_recipe,
            "smart_connect":          self.smart_connect,
            "arrange_nodes":          self.arrange_nodes,
            "execute_code":           self.execute_code,
            "list_documentation":     self.list_documentation,
            "list_material_models":   self.list_material_models,
            "list_function_nodes":     self.list_function_nodes,
            "list_sdf_functions":      self.list_sdf_functions,
            "build_function_graph":    self.build_function_graph,
            "get_function_graph_info": self.get_function_graph_info,
            "build_sdf_scene":         self.build_sdf_scene,
            "set_shape_splatter_sdf":  self.set_shape_splatter_sdf,
            "render_outputs":          self.render_outputs,
            "export_outputs":          self.export_outputs,
            "validate_library":        self.validate_library,
            "close_package":           self.close_package,
        }
        # Library node URL cache (populated lazily, session-lifetime)
        self._lib_url_cache = {}  # lower-case keyword -> exact library identifier
        self._lib_file_index = None  # identifier -> [.sbs paths], built lazily
        self._lib_hidden = set()     # {(identifier, path)} marked hideInLibrary
        self._fn_file_index = None   # function identifier -> [.sbs paths]
        self._fn_hidden = set()
        self._lib_meta = {}          # (kind, identifier, path) -> label/category/...
        self._lib_file_info = {}     # path -> {"source", "root"}

    def dispatch(self, cmd_type, params):
        handler = self.HANDLERS.get(cmd_type)
        if not handler:
            raise ValueError("Unknown command: '{}'. Available: {}".format(
                cmd_type, sorted(self.HANDLERS.keys())))
        return handler(**params)

    def list_documentation(self, category="all", filter_text="", node_name="",
                            action="", topic="", query=""):
        """
        Browse the SD MCP internal documentation knowledge base.

        Params:
          category    — one of: all, atomic_nodes, library_nodes, blend_modes,
                        port_reference, pbr_outputs, workflow, concepts, shortcuts,
                        connection_patterns, node_categories, parameters
          filter_text — substring filter applied to results (case-insensitive)
          node_name   — get detailed info for a specific node (e.g. 'blur', 'blend')
          action      — legacy compat alias for category ('categories', 'search')
          topic       — unused (kept for compat with newer schema)
          query       — alias for filter_text when action='search'
        """
        from . import sd_documentation as _doc

        # action='search' compat → use query as filter_text
        if action == "search" and query and not filter_text:
            filter_text = query

        # action='categories' → list available categories
        if action == "categories":
            return {
                "status": "ok",
                "categories": list(_doc.CATEGORIES.keys()),
                "descriptions": _doc.CATEGORIES,
            }

        try:
            result = _doc.query_documentation(
                category=category or "all",
                filter_text=filter_text or "",
                node_name=node_name or "",
            )
            return {"status": "ok", "result": result}
        except SDError as e:
            return {"status": "error", "message": str(e)}

    def execute_code(self, code):
        """Execute arbitrary Python on the SD main thread. Keep it short."""
        stdout_cap = io.StringIO()
        stderr_cap = io.StringIO()
        app_obj    = sd.getContext().getSDApplication()

        def _open_in_editor_safe(g):
            try:
                app_obj.getUIMgr().openResourceInEditor(g)
            except SDError as e:
                print("[MCP] open_in_editor warning: {}".format(e))

        namespace = {
            "sd": sd, "app": app_obj,
            "pkg_mgr": app_obj.getPackageMgr(),
            "ui_mgr":  app_obj.getUIMgr(),
            "open_in_editor": _open_in_editor_safe,
        }
        error = None
        try:
            with redirect_stdout(stdout_cap), redirect_stderr(stderr_cap):
                exec(compile(code, "<mcp_execute>", "exec"), namespace)
        except SDError as e:
            error = "{}: {}".format(type(e).__name__, e)
            stderr_cap.write(traceback.format_exc())

        return {
            "executed": error is None,
            "stdout":   stdout_cap.getvalue(),
            "stderr":   stderr_cap.getvalue(),
            "error":    error,
        }
