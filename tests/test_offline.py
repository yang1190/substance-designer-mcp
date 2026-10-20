#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Offline checks — no Substance Designer needed (runs in CI).

    python -m unittest tests/test_offline.py -v

* syntax of every Python file
* recipe structure: unique aliases, connections reference existing aliases,
  every node has a type, output nodes have a usage
* recipe ports and parameters against tests/data/sd_node_ports.json
  (a snapshot taken from a live SD with tests/update_port_snapshot.py):
  from_output / to_input exist on the node type, every parameter id exists
* bridge (skipped when the `mcp` package is missing): tool list and the
  render_outputs thumbnail -> MCP image conversion
"""
import ast
import asyncio
import base64
import importlib.util
import json
import os
import struct
import sys
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugin")
SERVER = os.path.join(ROOT, "server")
SNAPSHOT = os.path.join(ROOT, "tests", "data", "sd_node_ports.json")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


recipes = _load("sd_mcp_recipes_offline", os.path.join(PLUGIN, "recipes.py"))


def _all_recipes():
    out = dict(recipes.RECIPE_REGISTRY)
    for style, builder in recipes.HEIGHTMAP_RECIPES.items():
        for detail in (1, 2, 3):
            out["heightmap:{}:{}".format(style, detail)] = builder(
                detail_level=detail, scale=5.0, disorder=0.5)
    return out


def _node_type(spec):
    url = spec.get("resource_url")
    if url:
        ident = url[len("pkg:///"):] if url.startswith("pkg:///") else url
        return "library", ident.split("?", 1)[0].strip("/")
    if spec.get("library_keyword"):
        return "library", spec["library_keyword"]
    return "atomic", spec.get("definition_id", "sbs::compositing::uniform")


class TestSyntax(unittest.TestCase):
    def test_python_files_parse(self):
        bad = []
        for base in ("plugin", "server", "tests"):
            for dirpath, _, files in os.walk(os.path.join(ROOT, base)):
                if ".venv" in dirpath or "__pycache__" in dirpath:
                    continue
                for f in files:
                    if f.endswith(".py"):
                        p = os.path.join(dirpath, f)
                        try:
                            with open(p, encoding="utf-8-sig") as fh:
                                ast.parse(fh.read(), p)
                        except SyntaxError as e:
                            bad.append("{}: {}".format(p, e))
        self.assertEqual(bad, [])


class TestRecipeStructure(unittest.TestCase):
    def test_counts(self):
        self.assertGreaterEqual(len(recipes.RECIPE_REGISTRY), 79)
        self.assertGreaterEqual(len(recipes.HEIGHTMAP_RECIPES), 8)

    def test_structure(self):
        problems = []
        for name, rec in _all_recipes().items():
            aliases = [n.get("id_alias") for n in rec["nodes"]]
            dup = {a for a in aliases if aliases.count(a) > 1}
            if dup:
                problems.append("{}: duplicate aliases {}".format(name, sorted(dup)))
            known = set(aliases)
            for n in rec["nodes"]:
                if not (n.get("definition_id") or n.get("resource_url") or n.get("library_keyword")):
                    problems.append("{}: node {} has no type".format(name, n.get("id_alias")))
                if n.get("definition_id") == "sbs::compositing::output" and not n.get("usage"):
                    problems.append("{}: output {} has no usage".format(name, n.get("id_alias")))
            for c in rec["connections"]:
                for k in ("from", "to"):
                    if c.get(k) not in known:
                        problems.append("{}: connection {} '{}' unknown".format(name, k, c.get(k)))
            # every output node fed
            fed = {c["to"] for c in rec["connections"]}
            for n in rec["nodes"]:
                if n.get("definition_id") == "sbs::compositing::output" and n["id_alias"] not in fed:
                    problems.append("{}: output {} not connected".format(name, n["id_alias"]))
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:40]))


@unittest.skipUnless(os.path.exists(SNAPSHOT), "no port snapshot (run tests/update_port_snapshot.py)")
class TestRecipePortsAgainstSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SNAPSHOT, encoding="utf-8") as fh:
            cls.snap = json.load(fh)

    def _entry(self, kind, key):
        return self.snap.get(kind, {}).get(key)

    def test_node_types_known(self):
        missing = set()
        for name, rec in _all_recipes().items():
            for n in rec["nodes"]:
                kind, key = _node_type(n)
                e = self._entry(kind, key)
                if e is None or "error" in e:
                    missing.add("{}:{}".format(kind, key))
        self.assertEqual(sorted(missing), [],
                         "node types missing from the snapshot — rerun tests/update_port_snapshot.py")

    def test_ports(self):
        problems = []
        for name, rec in _all_recipes().items():
            types = {n["id_alias"]: _node_type(n) for n in rec["nodes"]}
            for c in rec["connections"]:
                fe = self._entry(*types.get(c["from"], ("?", "?"))) or {}
                te = self._entry(*types.get(c["to"], ("?", "?"))) or {}
                fo = c.get("from_output", "unique_filter_output")
                ti = c.get("to_input", "input1")
                if fe.get("outputs") is not None and fo not in fe["outputs"]:
                    problems.append("{}: {}.{} not an output (has {})".format(
                        name, c["from"], fo, fe["outputs"]))
                if te.get("inputs") is not None and ti not in te["inputs"]:
                    problems.append("{}: {}.{} not an input (has {})".format(
                        name, c["to"], ti, te["inputs"]))
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:40]))

    def test_parameters(self):
        problems = []
        for name, rec in _all_recipes().items():
            for n in rec["nodes"]:
                e = self._entry(*_node_type(n)) or {}
                valid = set(e.get("parameters", {})) | set(e.get("annotations", []))
                if not valid:
                    continue
                for pid in (n.get("parameters") or {}):
                    if pid not in valid:
                        problems.append("{}: {}.{} unknown parameter".format(name, n["id_alias"], pid))
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:40]))


def _tiny_png():
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp package not installed")
class TestBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old = sys.argv
        sys.argv = ["sd_mcp_bridge.py"]
        try:
            cls.b = _load("sd_mcp_bridge_offline", os.path.join(SERVER, "sd_mcp_bridge.py"))
        finally:
            sys.argv = old

    def test_tools(self):
        tools = asyncio.run(self.b.mcp.list_tools())
        names = {t.name for t in tools}
        for required in ("get_scene_info", "build_material_graph", "render_outputs",
                         "build_function_graph", "build_sdf_scene", "set_shape_splatter_sdf",
                         "create_batch_graph", "arrange_nodes", "list_material_models"):
            self.assertIn(required, names)
        props = {t.name: set(t.inputSchema.get("properties", {})) for t in tools}
        self.assertIn("material_model", props["build_material_graph"])

    def test_render_outputs_returns_images(self):
        png = _tiny_png()

        async def fake(cmd, params=None):
            return json.dumps({"graph": "g", "outputs": [
                {"identifier": "height", "node_id": "1", "stats": {"flat": False},
                 "thumbnail_png_base64": base64.b64encode(png).decode()}]})
        orig = self.b._async_send
        self.b._async_send = fake
        try:
            res = asyncio.run(self.b.mcp.call_tool("render_outputs", {}))
        finally:
            self.b._async_send = orig
        items = res[0] if isinstance(res, tuple) else res
        kinds = [getattr(c, "type", None) for c in items]
        self.assertIn("image", kinds)
        self.assertNotIn("thumbnail_png_base64", items[0].text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
