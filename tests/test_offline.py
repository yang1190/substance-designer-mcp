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
* custom Library paths (plugin/library_paths.py): SD .sbsprj parsing, URL
  aliases, plugin config, env var, recursive scan, .sbs header parsing
"""
import ast
import asyncio
import base64
import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
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
LP = _load("sd_mcp_library_paths_offline", os.path.join(PLUGIN, "library_paths.py"))


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
                         "create_batch_graph", "arrange_nodes", "list_material_models",
                         "list_library_paths", "add_library_path", "remove_library_path",
                         "rescan_library"):
            self.assertIn(required, names)
        props = {t.name: set(t.inputSchema.get("properties", {})) for t in tools}
        self.assertIn("material_model", props["build_material_graph"])
        self.assertIn("source", props["get_library_nodes"])

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


# Structure copied from SD 16.0.5's settings folder (paths made relative).
_DEFAULT_PRJ = """<?xml version="1.0" encoding="UTF-8"?>
<root>
	<settingsinfo><version>5</version></settingsinfo>
	<preferences>
		<resources>
			<urlaliases>
				<size>2</size>
				<_2 prefix="_"><path>file:///{root}/sd/resources/view3d/maps</path><name>sd-3dview-maps</name></_2>
				<_1 prefix="_"><path>file:///{root}/sd/resources/packages</path><name>sbs</name></_1>
			</urlaliases>
		</resources>
		<library>
			<watchedpaths>
				<size>2</size>
				<_2 prefix="_"><url>sbs://</url><isrecursive>true</isrecursive><isenabled>true</isenabled></_2>
				<_1 prefix="_"><url>sd-3dview-maps://</url><isrecursive>true</isrecursive><isenabled>true</isenabled></_1>
			</watchedpaths>
		</library>
	</preferences>
</root>
"""

_USER_PRJ = """<?xml version="1.0" encoding="UTF-8"?>
<root>
	<projectinfo><label>User project</label></projectinfo>
	<preferences>
		<resources><urlaliases><size>1</size>
			<_1 prefix="_"><path>file:///{root}/team</path><name>team</name></_1>
		</urlaliases></resources>
		<library>
			<watchedpaths>
				<size>4</size>
				<_4 prefix="_"><url>file:///{root}/Custom%20Library</url><isrecursive>false</isrecursive><isenabled>true</isenabled><excludepattern></excludepattern><excludefilter></excludefilter></_4>
				<_3 prefix="_"><url>team://rocks</url><isrecursive>true</isrecursive><isenabled>true</isenabled><excludepattern>*_wip*</excludepattern><excludefilter></excludefilter></_3>
				<_2 prefix="_"><url>file:///{root}/disabled</url><isrecursive>false</isrecursive><isenabled>false</isenabled></_2>
				<_1 prefix="_"><url>sbs://materials</url><isrecursive>true</isrecursive><isenabled>true</isenabled></_1>
			</watchedpaths>
		</library>
	</preferences>
</root>
"""

_CFG = """<?xml version="1.0" encoding="UTF-8"?>
<root><projects><projectfiles><size>0</size></projectfiles></projects></root>
"""

_SBS = (b'<?xml version="1.0" encoding="UTF-8"?><package><identifier v="Unsaved Package"/>'
        b'<content><graph><identifier v="FloodFills"/><uid v="1"/><attributes>'
        b'<category v="Tom Jacobs/Filter"/><label v="Flood Fills"/><author v="Tom Jacobs"/>'
        b'<description v="a &amp; b"/></attributes><paraminputs><paraminput>'
        b'<identifier v="x"/><attributes><hideInLibrary v="1"/></attributes></paraminput>'
        b'</paraminputs></graph>'
        b'<graph><identifier v="Splitter"/><uid v="2"/><attributes><hideInLibrary v="1"/>'
        b'</attributes></graph>'
        b'<graph><identifier v="noattr"/><uid v="3"/><paraminputs><paraminput><identifier v="p"/>'
        b'<attributes><hideInLibrary v="1"/></attributes></paraminput></paraminputs></graph>'
        b'<function><identifier v="my_fn"/><uid v="4"/></function></content></package>')


class TestLibraryPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = self.tmp.replace("\\", "/")
        r = self.root
        self.settings = os.path.join(r, "appdata", "Adobe", "Adobe Substance 3D Designer")
        sd16 = os.path.join(self.settings, "16.0")
        for d in ("sd/resources/packages/materials", "sd/resources/view3d/maps",
                  "Custom Library/sub", "team/rocks/deep", "disabled", "cfg"):
            os.makedirs(os.path.join(r, d))
        os.makedirs(sd16)
        os.makedirs(os.path.join(self.settings, "15.1"))
        for name, text in (("default_project.sbsprj", _DEFAULT_PRJ),
                           ("user_project.sbsprj", _USER_PRJ),
                           ("default_configuration.sbscfg", _CFG)):
            with open(os.path.join(sd16, name), "w", encoding="utf-8") as fh:
                fh.write(text.format(root=r.lstrip("/")))
        for f in ("sd/resources/packages/perlin.sbs", "Custom Library/FloodFills.sbs",
                  "Custom Library/sub/nested.sbs", "Custom Library/readme.txt",
                  "team/rocks/a.sbs", "team/rocks/deep/b.sbs", "team/rocks/c_wip.sbs"):
            with open(os.path.join(r, f), "wb") as fh:
                fh.write(_SBS)
        self.builtin = LP.norm_path(os.path.join(r, "sd/resources/packages"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_dir_and_urls(self):
        self.assertTrue(LP.sd_settings_dir("16.0.5", [self.settings]).endswith("/16.0"))
        self.assertTrue(LP.sd_settings_dir(None, [self.settings]).endswith("/16.0"))
        self.assertTrue(LP.sd_settings_dir("15.1.2", [self.settings]).endswith("/15.1"))
        self.assertEqual(LP.file_url_to_path("file:///C:/A%20B/c"), "C:/A B/c")
        self.assertEqual(LP.file_url_to_path("sbs://x", {"sbs": "C:/sd/pk"}), "C:/sd/pk/x")
        self.assertEqual(LP.file_url_to_path("sbs://", {"sbs": "C:/sd/pk"}), "C:/sd/pk")
        self.assertIsNone(LP.file_url_to_path("environment:SBS_DESIGNER_PYTHON_PATH"))
        self.assertIsNone(LP.file_url_to_path("unknown://x", {}))

    def test_project_parsing(self):
        sd16 = LP.sd_settings_dir("16.0", [self.settings])
        w = LP.sd_project_watched_paths(sd16)
        urls = [x["url"] for x in w]
        self.assertIn("sbs://", urls)
        custom = next(x for x in w if "Custom" in x["url"])
        self.assertEqual(custom["path"], LP.norm_path(os.path.join(self.root, "Custom Library")))
        self.assertFalse(custom["recursive"])
        team = next(x for x in w if x["url"] == "team://rocks")
        self.assertEqual(team["path"], LP.norm_path(os.path.join(self.root, "team/rocks")))
        self.assertTrue(team["recursive"])
        self.assertEqual(team["exclude_pattern"], "*_wip*")
        self.assertFalse(next(x for x in w if "disabled" in x["url"])["enabled"])

    def test_collect_and_scan(self):
        sd16 = LP.sd_settings_dir("16.0", [self.settings])
        cfg_path = os.path.join(self.root, "cfg", "library_paths.json")
        cfg = LP.load_config(cfg_path)          # missing file -> defaults
        self.assertEqual(cfg["paths"], [])
        cfg["paths"].append({"path": os.path.join(self.root, "cfg"), "recursive": False})
        LP.save_config(cfg_path, cfg)
        cfg = LP.load_config(cfg_path)
        env = {LP.ENV_VAR: os.path.join(self.root, "Custom Library") + "*"}
        roots = LP.collect_library_roots([self.builtin], sd16, cfg, env)
        by_src = {}
        for r in roots:
            by_src.setdefault(r["source"], []).append(r)
        self.assertEqual(len(by_src["builtin"]), 1)
        self.assertFalse(by_src["builtin"][0]["recursive"])
        # sbs:// and sbs://materials are the built-in library -> not duplicated;
        # sd-3dview-maps:// is inside SD's resources -> skipped
        self.assertFalse(any(r["path"].startswith(self.builtin + "/") for r in roots))
        self.assertFalse(any("view3d" in r["path"] for r in roots))
        cl = next(r for r in roots if r["path"].endswith("Custom Library"))
        self.assertEqual(cl["source"], "sd_project")
        self.assertTrue(cl["recursive"], "env var with '*' turns on recursion")
        self.assertIn("env", cl["also_in"])
        self.assertIn("plugin_config", by_src)
        files = {os.path.basename(f) for r in roots for f in LP.iter_sbs_files(r)}
        self.assertEqual(files, {"perlin.sbs", "FloodFills.sbs", "nested.sbs", "a.sbs", "b.sbs"})
        # ignore an SD project path
        cfg["ignored"] = [os.path.join(self.root, "team/rocks")]
        roots = LP.collect_library_roots([self.builtin], sd16, cfg, {})
        team = next(r for r in roots if r["path"].endswith("team/rocks"))
        self.assertFalse(team["enabled"])
        self.assertEqual(list(LP.iter_sbs_files(team)), [])

    def test_scan_sbs_bytes(self):
        e = {x["identifier"]: x for x in LP.scan_sbs_bytes(_SBS)}
        self.assertEqual(e["FloodFills"]["label"], "Flood Fills")
        self.assertEqual(e["FloodFills"]["category"], "Tom Jacobs/Filter")
        self.assertEqual(e["FloodFills"]["description"], "a & b")
        self.assertFalse(e["FloodFills"]["hidden"], "parameter attributes must not leak")
        self.assertTrue(e["Splitter"]["hidden"])
        self.assertFalse(e["noattr"]["hidden"])
        self.assertEqual(e["my_fn"]["kind"], "function")

    def test_split_ref(self):
        self.assertEqual(LP.split_ref("pkg:///clouds_2?dependency=12"), (None, "clouds_2"))
        self.assertEqual(LP.split_ref("FloodFills.sbs#FloodFills"), ("FloodFills.sbs", "FloodFills"))
        self.assertEqual(LP.split_ref("D:/lib/x.sbs#rock_a"), ("D:/lib/x.sbs", "rock_a"))
        self.assertEqual(LP.split_ref("perlin_noise"), (None, "perlin_noise"))


class TestSkills(unittest.TestCase):
    """skills/<name>/SKILL.md frontmatter and the Claude plugin manifests."""
    SKILLS = os.path.join(ROOT, "skills")

    def _frontmatter(self, path):
        text = open(path, encoding="utf-8").read()
        self.assertTrue(text.startswith("---\n"), path)
        head = text.split("---\n", 2)[1]
        meta = {}
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta, text

    def test_skill_frontmatter(self):
        names = [n for n in os.listdir(self.SKILLS)
                 if os.path.isfile(os.path.join(self.SKILLS, n, "SKILL.md"))]
        self.assertGreaterEqual(len(names), 3)
        for n in names:
            meta, text = self._frontmatter(os.path.join(self.SKILLS, n, "SKILL.md"))
            self.assertEqual(meta.get("name"), n)
            self.assertTrue(meta.get("description"), n)
            self.assertLessEqual(len(meta["description"]), 1024, n)
            self.assertNotIn("<", meta["description"], n)

    def test_packages_match_sources(self):
        import zipfile
        for n in os.listdir(self.SKILLS):
            src = os.path.join(self.SKILLS, n, "SKILL.md")
            if not os.path.isfile(src):
                continue
            pkg = os.path.join(self.SKILLS, "packages", n + ".skill")
            self.assertTrue(os.path.isfile(pkg), pkg + " missing: run tests/build_skill_packages.py")
            with zipfile.ZipFile(pkg) as z:
                self.assertEqual(z.read(n + "/SKILL.md").replace(b"\r\n", b"\n"),
                                 open(src, "rb").read().replace(b"\r\n", b"\n"),
                                 pkg + " is stale: run tests/build_skill_packages.py")

    def test_plugin_manifests(self):
        man = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
        mkt = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
        self.assertIn(man["name"], [p["name"] for p in mkt["plugins"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
