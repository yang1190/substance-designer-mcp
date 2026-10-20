"""
Batch graph builder, recipe-based material / heightmap builders.
"""

import copy

from .common import (
    SDError,
    SDSBSCompGraph,
    _log,
    _sanitize_identifier,
    float2,
)


class BuilderMixin(object):
    """Mixed into CommandHandler."""

    # ── shared node/connection population ─────────────────────────────────
    @staticmethod
    def _recipe_variant(recipe, overrides=None, position_offset=None):
        """Deep copy of a recipe with per-alias parameter overrides and an
        optional [x, y] position offset applied."""
        recipe = copy.deepcopy(recipe)
        if position_offset:
            ox, oy = float(position_offset[0]), float(position_offset[1])
            for spec in recipe.get("nodes", []):
                p = spec.get("position", [0, 0])
                spec["position"] = [p[0] + ox, p[1] + oy]
        for node_alias, node_overrides in (overrides or {}).items():
            for spec in recipe.get("nodes", []):
                if spec.get("id_alias") == node_alias:
                    spec.setdefault("parameters", {}).update(node_overrides)
        return recipe

    def _populate_graph(self, graph, nodes, connections):
        """Create every node descriptor in `graph`, apply its parameters and
        wire the connections. Used by create_batch_graph and apply_recipe.
        Returns a result dict with node_map, failures, parameter issues and
        per-connection results."""
        try:
            known_defs = {d.getId() for d in list(graph.getNodeDefinitions())}
        except SDError:
            known_defs = set()

        alias_map = {}       # alias -> (node, node_id)
        created, failed, param_issues = [], [], []

        for spec in nodes or []:
            defn_id = spec.get("definition_id", "sbs::compositing::uniform")
            pos     = spec.get("position", [0, 0])
            params  = spec.get("parameters", {})
            alias   = (spec.get("id_alias") or spec.get("alias")
                       or defn_id.split("::")[-1])
            orig_alias = alias
            res_url = spec.get("resource_url")
            lib_kw  = spec.get("library_keyword")
            try:
                if defn_id == "sbs::compositing::output":
                    node = self._new_output_node(graph, spec.get("usage"), spec.get("label"))
                elif res_url:
                    node = self._new_library_node(graph, res_url)
                elif lib_kw:
                    node = self._create_library_node(graph, lib_kw)
                else:
                    # newNode(unknown definition) hangs SD 15: validate first
                    if known_defs and defn_id not in known_defs:
                        raise ValueError("Unknown definition '{}'. "
                                         "Use resource_url / library_keyword for library nodes."
                                         .format(defn_id))
                    node = graph.newNode(defn_id)
                if not node:
                    raise RuntimeError("newNode returned None for '{}'.".format(defn_id))

                node.setPosition(float2(float(pos[0]), float(pos[1])))
                param_issues += self._param_issues(
                    alias, node, self._set_node_params(node, params))

                node_id = node.getIdentifier()
                counter = 0
                while alias in alias_map:          # deduplicate aliases
                    counter += 1
                    alias = "{}_{}".format(orig_alias, counter)
                alias_map[alias] = (node, node_id)
                created.append({"alias": alias, "node_id": node_id,
                                "definition": self._get_node_def_id(node)})
            except SDError as e:
                _log("Error creating node '{}': {}".format(alias, e))
                failed.append({"alias": alias, "error": str(e)})

        conn_results = []
        for conn in connections or []:
            fa = conn.get("from") or conn.get("from_alias")
            ta = conn.get("to") or conn.get("to_alias")
            fo = conn.get("from_output", "unique_filter_output")
            ti = conn.get("to_input", "input1")
            if fa not in alias_map:
                conn_results.append({"from": fa, "to": ta, "success": False,
                                     "error": "from '{}' not found".format(fa)})
                continue
            if ta not in alias_map:
                conn_results.append({"from": fa, "to": ta, "success": False,
                                     "error": "to '{}' not found".format(ta)})
                continue
            try:
                self._safe_connect(graph, alias_map[fa][0], fo, alias_map[ta][0], ti)
                conn_results.append({"from": fa, "to": ta, "success": True})
            except SDError as e:
                conn_results.append({"from": fa, "to": ta, "success": False, "error": str(e)})

        return {
            "nodes_created":      len(created),
            "nodes_failed":       len(failed),
            "connections_ok":     sum(1 for c in conn_results if c.get("success")),
            "connections_failed": sum(1 for c in conn_results if not c.get("success")),
            "params_failed":      len(param_issues),
            "param_issues":       param_issues,
            "node_map":           {a: nid for a, (_, nid) in alias_map.items()},
            "nodes":              created,
            "failed_nodes":       failed,
            "connections":        conn_results,
        }

    # ── public builders ─────────────────────────────────────────────────────
    def create_batch_graph(self, graph_name, package_index=0, package_path=None,
                           nodes=None, connections=None, output_size_log2=11,
                           open_in_editor=True, material_model=None):
        """
        Create a complete graph in one call: atomic nodes, library nodes (via
        resource_url or library_keyword), output nodes and connections.
        """
        pkg = self._resolve_package(package_index, package_path)
        graph = SDSBSCompGraph.sNew(pkg)
        graph.setIdentifier(_sanitize_identifier(graph_name))
        self._apply_material_model(graph, material_model)
        try:
            self._set_absolute_output_size(graph, output_size_log2, output_size_log2)
        except SDError as e:
            _log("Warning: Could not set graph output size: {}".format(e))

        result = self._populate_graph(graph, nodes, connections)

        if open_in_editor:
            try:
                self._ui_mgr().openResourceInEditor(graph)
            except SDError as e:
                _log("Warning: openResourceInEditor failed: {}".format(e))

        out = {"graph_identifier": graph.getIdentifier(), "requested_name": graph_name}
        out.update(result)
        return out

    def build_material_graph(self, graph_name, recipe_name,
                              package_index=0, package_path=None,
                              overrides=None, output_size_log2=11,
                              open_in_editor=True, material_model=None):
        """
        Build a complete PBR material graph from a named recipe.
        overrides: dict of parameter overrides applied on top of recipe defaults.
        """
        from .recipes import RECIPE_REGISTRY
        recipe_name_key = recipe_name.lower().replace(" ", "_").replace("-", "_")
        recipe = RECIPE_REGISTRY.get(recipe_name_key)
        if not recipe:
            available = sorted(RECIPE_REGISTRY.keys())
            raise ValueError(
                "Recipe '{}' not found. Available: {}".format(recipe_name, available))

        if overrides:
            recipe = self._recipe_variant(recipe, overrides=overrides)

        nodes       = recipe.get("nodes", [])
        connections = recipe.get("connections", [])

        return self.create_batch_graph(
            graph_name       = graph_name,
            package_index    = package_index,
            package_path     = package_path,
            nodes            = nodes,
            connections      = connections,
            output_size_log2 = output_size_log2,
            open_in_editor   = open_in_editor,
            material_model   = material_model,
        )

    def build_heightmap_graph(self, graph_name, style,
                               package_index=0, package_path=None,
                               output_size_log2=11, open_in_editor=True,
                               detail_level=2, scale=5.0, disorder=0.5,
                               material_model=None):
        """
        Build a heightmap graph for terrain/rock/cliff styles.
        style: 'cliff', 'rock', 'cracked', 'sand', 'mud', 'mountain', 'cobblestone'
        detail_level: 1=basic, 2=standard, 3=high detail
        """
        from .recipes import HEIGHTMAP_RECIPES
        style_key = style.lower().replace(" ", "_")
        builder   = HEIGHTMAP_RECIPES.get(style_key)
        if not builder:
            available = sorted(HEIGHTMAP_RECIPES.keys())
            raise ValueError(
                "Heightmap style '{}' not found. Available: {}".format(style, available))

        recipe = builder(detail_level=detail_level, scale=scale, disorder=disorder)
        nodes       = recipe.get("nodes", [])
        connections = recipe.get("connections", [])
        return self.create_batch_graph(
            graph_name       = graph_name,
            package_index    = package_index,
            package_path     = package_path,
            nodes            = nodes,
            connections      = connections,
            output_size_log2 = output_size_log2,
            open_in_editor   = open_in_editor,
            material_model   = material_model,
        )

    def list_recipes(self):
        """List all available material recipes."""
        try:
            from .recipes import RECIPE_REGISTRY, HEIGHTMAP_RECIPES
            recipes = []
            for key, recipe in RECIPE_REGISTRY.items():
                recipes.append({
                    "key":         key,
                    "name":        recipe.get("name", key),
                    "category":    recipe.get("category", "unknown"),
                    "description": recipe.get("description", ""),
                    "node_count":  len(recipe.get("nodes", [])),
                    "outputs":     recipe.get("outputs", []),
                })
            heightmaps = sorted(HEIGHTMAP_RECIPES.keys())
            return {
                "material_recipes": recipes,
                "heightmap_styles": heightmaps,
                "total_recipes": len(recipes),
                "total_heightmap_styles": len(heightmaps),
            }
        except ImportError as e:
            return {"error": "Recipes module not loaded: {}".format(e)}

    def get_recipe_info(self, recipe_name):
        """Get detailed info about a specific recipe."""
        try:
            from .recipes import RECIPE_REGISTRY
            key = recipe_name.lower().replace(" ", "_").replace("-", "_")
            recipe = RECIPE_REGISTRY.get(key)
            if not recipe:
                return {"error": "Recipe '{}' not found.".format(recipe_name)}
            return {
                "key":          key,
                "name":         recipe.get("name", key),
                "category":     recipe.get("category", "unknown"),
                "description":  recipe.get("description", ""),
                "outputs":      recipe.get("outputs", []),
                "node_count":   len(recipe.get("nodes", [])),
                "nodes_preview": [
                    {
                        "alias": s.get("id_alias", "?"),
                        "type":  s.get("definition_id", s.get("library_keyword", "?")),
                    }
                    for s in recipe.get("nodes", [])[:20]
                ],
            }
        except ImportError as e:
            return {"error": "Recipes module not loaded: {}".format(e)}

    def apply_recipe(self, recipe_name, graph_identifier=None, position_offset=None,
                     overrides=None):
        """
        Apply a recipe to an EXISTING graph (add nodes + connections to it).
        Useful for combining multiple recipes or adding detail passes.
        """
        from .recipes import RECIPE_REGISTRY
        key = recipe_name.lower().replace(" ", "_").replace("-", "_")
        recipe = RECIPE_REGISTRY.get(key)
        if not recipe:
            raise ValueError("Recipe '{}' not found.".format(recipe_name))
        recipe = self._recipe_variant(recipe, overrides=overrides,
                                      position_offset=position_offset)
        graph = self._resolve_graph(graph_identifier)
        result = self._populate_graph(graph, recipe.get("nodes", []),
                                      recipe.get("connections", []))
        out = {"graph_identifier": graph.getIdentifier(), "recipe": recipe_name,
               "nodes_added": result["nodes_created"]}
        out.update(result)
        return out
