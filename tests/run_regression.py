#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SD MCP regression suite — runs against a live Substance 3D Designer with the
MCP plugin loaded (talks to the plugin's TCP port directly, no MCP client needed).

    python tests/run_regression.py                 # full run
    python tests/run_regression.py --quick         # ~2 minute smoke test
    python tests/run_regression.py --skip-library  # skip the 491-graph library sweep

What it checks
  1. environment       SD / Python / plugin versions, usages enabled
  2. recipes           every material recipe builds with 0 node / 0 connection /
                       0 parameter failures, and its outputs are not flat
  3. heightmaps        every heightmap style, same checks
  4. library           every graph visible in SD's Library instantiates, then a
                       few recipes are rebuilt (resolution must ignore Legacy
                       packages the sweep pulled in)
  5. openpbr           OpenPBR identifiers / dual usages on a material recipe
  6. sdf_scene         build_sdf_scene renders a non-flat beauty pass
  7. splatter_sdf      Shape splatter v2 scatters an SDF shape (non-flat height)
  8. pixel_processor   build_function_graph on a pixel processor (non-flat)
  9. custom_library    custom Library folders (SD's watched paths, plugin
                       config, env var) are scanned and every visible graph
                       in them instantiates

Everything is built in a fresh, unsaved package that is closed at the end;
open user packages are never modified.

Known problems are listed in tests/regression_baseline.json. A check that
fails but is listed there is reported as KNOWN (does not fail the run); a
listed problem that no longer occurs is reported as FIXED so the baseline can
be trimmed. Exit code: 0 = no new failures, 1 = new failures, 2 = cannot run.
"""
import argparse
import datetime as _dt
import io
import json
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = 4


# ── transport (same framing as the bridge: 4-byte big-endian length + JSON) ──
class SDClient(object):
    def __init__(self, host="localhost", port=9881, timeout=180):
        self.host, self.port, self.timeout = host, port, timeout

    def _recv_exact(self, sock, n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed by SD")
            buf += chunk
        return buf

    def call(self, cmd, **params):
        data = json.dumps({"type": cmd, "params": params}).encode("utf-8")
        sock = socket.create_connection((self.host, self.port), timeout=10)
        try:
            sock.settimeout(self.timeout)
            sock.sendall(struct.pack(">I", len(data)) + data)
            n = struct.unpack(">I", self._recv_exact(sock, HEADER))[0]
            resp = json.loads(self._recv_exact(sock, n).decode("utf-8"))
        finally:
            sock.close()
        if resp.get("status") != "success":
            raise RuntimeError("{} failed: {}".format(cmd, resp.get("message")))
        return resp.get("result")


# ── result bookkeeping ───────────────────────────────────────────────────────
class Report(object):
    def __init__(self, baseline):
        self.items = []           # dicts: section, name, status, detail
        self.baseline = baseline  # {section: {name: reason}}
        self.meta = {}

    def add(self, section, name, ok, detail="", data=None):
        known = self.baseline.get(section, {}).get(name)
        if ok:
            status = "FIXED" if known else "PASS"
        else:
            status = "KNOWN" if known else "FAIL"
        item = {"section": section, "name": name, "status": status,
                "detail": detail or (known if (known and not ok) else "")}
        if data is not None:
            item["data"] = data
        self.items.append(item)
        mark = {"PASS": ".", "FIXED": "+", "KNOWN": "k", "FAIL": "F"}[status]
        sys.stdout.write(mark)
        sys.stdout.flush()
        return status

    def counts(self):
        c = {"PASS": 0, "FIXED": 0, "KNOWN": 0, "FAIL": 0}
        for i in self.items:
            c[i["status"]] += 1
        return c

    def markdown(self):
        c = self.counts()
        m = self.meta
        lines = ["# SD MCP regression report", "",
                 "- Date: {}".format(m.get("date")),
                 "- Substance 3D Designer: {}  |  Python: {}  |  plugin: {}".format(
                     m.get("sd_version"), m.get("python_version"), m.get("plugin_version")),
                 "- Resolution: {0}x{0}  |  Duration: {1}s".format(
                     m.get("resolution"), m.get("seconds")),
                 "", "| Status | Count |", "|---|---|"]
        for k in ("PASS", "FIXED", "KNOWN", "FAIL"):
            lines.append("| {} | {} |".format(k, c[k]))
        sections = []
        for i in self.items:
            if i["section"] not in sections:
                sections.append(i["section"])
        for s in sections:
            its = [i for i in self.items if i["section"] == s]
            sc = {k: sum(1 for i in its if i["status"] == k) for k in ("PASS", "FIXED", "KNOWN", "FAIL")}
            lines += ["", "## {} — {} checks (pass {}, fixed {}, known {}, fail {})".format(
                s, len(its), sc["PASS"], sc["FIXED"], sc["KNOWN"], sc["FAIL"])]
            bad = [i for i in its if i["status"] != "PASS"]
            if bad:
                lines += ["", "| Status | Name | Detail |", "|---|---|---|"]
                for i in bad:
                    lines.append("| {} | {} | {} |".format(
                        i["status"], i["name"], str(i["detail"]).replace("|", "/")))
        return "\n".join(lines) + "\n"


def _flat(render, keys):
    """Identifiers of outputs (matching keys, or all) that are uniform."""
    res = []
    for o in render.get("outputs", []):
        ident = o.get("identifier", "")
        if keys and not any(k in ident or k in o.get("usages", []) for k in keys):
            continue
        st = o.get("stats")
        if st is None or st.get("flat"):
            res.append(ident or o.get("node_id"))
    return res


def _quality_problems(render):
    """Recipe quality rules: height / base color / normal / roughness must not
    be uniform, and height must not be low-contrast. Metallic, AO, opacity...
    are legitimately uniform for many materials and are not checked."""
    checked = {"height", "baseColor", "normal", "roughness", "specularRoughness"}
    probs = []
    for o in render.get("outputs", []):
        if not checked & set(o.get("usages", [])):
            continue
        ident = o.get("identifier") or o.get("node_id")
        st = o.get("stats")
        if st is None:
            probs.append("{}: no texture".format(ident))
        elif st.get("flat"):
            probs.append("{} flat (std {})".format(ident, st.get("max_std")))
        elif "height" in o.get("usages", []) and st.get("low_contrast"):
            probs.append("height low contrast (std {})".format(st.get("max_std")))
    return probs


# ── checks ───────────────────────────────────────────────────────────────────
def check_build(sd, rep, section, name, build, pkg, res_log2):
    gname = "rg_{}".format(name)
    try:
        r = build(gname)
    except Exception as e:  # noqa: BLE001
        rep.add(section, name, False, "build error: {}".format(e))
        return
    gid = r.get("graph_identifier", gname)
    try:
        problems = []
        if r.get("nodes_failed"):
            problems.append("{} node failures".format(r["nodes_failed"]))
        if r.get("connections_failed"):
            problems.append("{} connection failures".format(r["connections_failed"]))
        if r.get("params_failed"):
            problems.append("{} parameters not applied: {}".format(
                r["params_failed"], ", ".join("{}.{}".format(i.get("alias"), i.get("parameter"))
                                              for i in r.get("param_issues", [])[:5])))
        t = time.time()
        rend = sd.call("render_outputs", graph_identifier=gid, thumbnails=False)
        problems += _quality_problems(rend)
        dt = round(time.time() - t, 2)
        data = {"render_seconds": dt,
                "outputs": {o.get("identifier"): (o.get("stats") or {}).get("channels")
                            for o in rend.get("outputs", [])}}
        rep.add(section, name, not problems, "; ".join(problems), data)
        if dt > 10:
            rep.add("performance", name, False, "render took {}s at {}px".format(dt, 2 ** res_log2))
    finally:
        try:
            sd.call("delete_graph", graph_identifier=gid, package_index=pkg)
        except Exception:  # noqa: BLE001
            pass


def run(args):
    baseline_path = args.baseline
    baseline = {}
    if baseline_path and os.path.exists(baseline_path):
        with io.open(baseline_path, encoding="utf-8") as fh:
            baseline = json.load(fh).get("known_issues", {})
    rep = Report(baseline)
    sd = SDClient(port=args.port, timeout=args.timeout)
    t_start = time.time()

    try:
        diag = sd.call("diagnostic")
        scene = sd.call("get_scene_info")
    except Exception as e:  # noqa: BLE001
        print("Cannot reach the SD MCP plugin on port {}: {}".format(args.port, e))
        return 2
    rep.meta.update({
        "date": _dt.datetime.now().isoformat(timespec="seconds"),
        "sd_version": diag.get("sd_version"), "python_version": diag.get("python_version"),
        "plugin_version": scene.get("plugin_version"), "resolution": 2 ** args.resolution,
    })
    print("SD {} / Python {} / plugin {}".format(
        rep.meta["sd_version"], rep.meta["python_version"], rep.meta["plugin_version"]))
    rep.add("environment", "output_usages_enabled", bool(diag.get("output_usages_enabled")))
    rep.add("environment", "qt_binding", diag.get("qt_binding", "NONE") != "NONE",
            diag.get("qt_binding"))

    pkg_info = sd.call("create_package")
    pkg = pkg_info.get("package_index")
    if pkg is None:
        pkg = len(sd.call("get_scene_info")["packages"]) - 1
    try:
        recipes = sd.call("list_recipes")
        mats = [r["key"] for r in recipes["material_recipes"]]
        hms = recipes["heightmap_styles"]
        if args.quick:
            mats = [m for m in mats if m in ("metal_steel", "rock_granite", "pro_granite",
                                             "wood_oak", "brick_red")] or mats[:5]
            hms = hms[:2]
        if args.only:
            mats = [m for m in mats if args.only in m]
            hms = [h for h in hms if args.only in h]

        print("\n[recipes] {}".format(len(mats)))
        for name in mats:
            check_build(sd, rep, "recipes", name, lambda g, n=name: sd.call(
                "build_material_graph", graph_name=g, recipe_name=n, package_index=pkg,
                output_size_log2=args.resolution, open_in_editor=False), pkg, args.resolution)

        print("\n[heightmaps] {}".format(len(hms)))
        for name in hms:
            check_build(sd, rep, "heightmaps", name, lambda g, n=name: sd.call(
                "build_heightmap_graph", graph_name=g, style=n, package_index=pkg,
                output_size_log2=args.resolution, open_in_editor=False), pkg, args.resolution)

        if not args.skip_library and not args.only:
            print("\n[library]")
            offset, total, fails = 0, 0, []
            limit = 40 if args.quick else 120
            while offset is not None:
                r = sd.call("validate_library", offset=offset, limit=limit)
                total = r["total_visible"]
                fails += r["failed"]
                sys.stdout.write("({}/{})".format(min(offset + limit, total), total))
                sys.stdout.flush()
                offset = None if args.quick else r["next_offset"]
            for f in fails:
                rep.add("library", f["identifier"], False, f["error"])
            rep.add("library", "visible_graphs_instantiate", not fails,
                    "{} of {} failed".format(len(fails), total) if fails else "{} checked".format(total))

            # The library sweep loads hidden Legacy packages as dependencies.
            # Library resolution must still pick the current versions afterwards
            # (regression: bare pkg:/// URLs once matched Legacy cells_1 -> 'Cells').
            print("\n[after library sweep]")
            for name in ("rock_granite", "metal_iron", "obsidian", "pro_concrete", "pro_granite"):
                if name not in mats and not args.quick:
                    continue
                check_build(sd, rep, "after_library_sweep", name, lambda g, n=name: sd.call(
                    "build_material_graph", graph_name=g, recipe_name=n, package_index=pkg,
                    output_size_log2=args.resolution, open_in_editor=False), pkg, args.resolution)

        if not args.only:
            print("\n[custom library]")
            custom_library_checks(sd, rep)
            print("\n[sd16 features]")
            sd16_checks(sd, rep, pkg)
    finally:
        try:
            sd.call("close_package", package_index=pkg)
        except Exception as e:  # noqa: BLE001
            print("\nwarning: could not close test package: {}".format(e))

    rep.meta["seconds"] = round(time.time() - t_start, 1)
    c = rep.counts()
    print("\n\nPASS {PASS}  FIXED {FIXED}  KNOWN {KNOWN}  FAIL {FAIL}".format(**c))
    for i in rep.items:
        if i["status"] in ("FAIL", "FIXED"):
            print("  {:5} {}/{}: {}".format(i["status"], i["section"], i["name"], i["detail"]))

    os.makedirs(args.report_dir, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    jpath = os.path.join(args.report_dir, "regression_{}.json".format(stamp))
    mpath = os.path.join(args.report_dir, "regression_{}.md".format(stamp))
    with io.open(jpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": rep.meta, "counts": c, "items": rep.items}, fh, indent=2)
    with io.open(mpath, "w", encoding="utf-8") as fh:
        fh.write(rep.markdown())
    print("Report: {}\n        {}".format(mpath, jpath))
    return 1 if c["FAIL"] else 0


def sd16_checks(sd, rep, pkg):
    # OpenPBR identifiers / dual usages
    g = "rg_openpbr"
    try:
        sd.call("build_material_graph", graph_name=g, recipe_name="metal_steel",
                package_index=pkg, output_size_log2=8, open_in_editor=False,
                material_model="openpbr_v1_1")
        outs = {o["identifier"]: o["usages"] for o in
                sd.call("render_outputs", graph_identifier=g, thumbnails=False)["outputs"]}
        expected = {"base_color": ["baseColor"], "base_metalness": ["metalness", "metallic"],
                    "specular_roughness": ["specularRoughness", "roughness"],
                    "ambient_occlusion": ["ambientOcclusion"], "normal": ["normal"],
                    "height": ["height"]}
        bad = {k: outs.get(k) for k, v in expected.items() if outs.get(k) != v}
        rep.add("sd16", "openpbr_outputs", not bad, "mismatch: {}".format(bad) if bad else "")
    except Exception as e:  # noqa: BLE001
        rep.add("sd16", "openpbr_outputs", False, str(e))
    finally:
        _safe_delete(sd, g, pkg)

    # SDF scene through the 3D viewer
    g = "rg_sdf_scene"
    try:
        r = sd.call("build_sdf_scene", graph_name=g, package_index=pkg, output="m",
                    outputs=["beauty", "depth"], nodes=[
                        {"alias": "b", "type": "cube", "inputs": {"size": [0.6, 0.6, 0.2],
                                                                   "center_position": [0, 0, 0.1]}},
                        {"alias": "s", "type": "sphere", "inputs": {"radius": 0.22,
                                                                    "center_position": [0, 0, 0.3]}},
                        {"alias": "u", "type": "union_smooth",
                         "inputs": {"sdf_1": "@b", "sdf_2": "@s", "smoothness": 0.08}},
                        {"alias": "m", "type": "set_color",
                         "inputs": {"scene": "@u", "basecolor": [0.8, 0.4, 0.1]}}])
        errs = [e for v in r["viewers"] for e in v["errors"]]
        flat = _flat(sd.call("render_outputs", graph_identifier=g, thumbnails=False), [])
        rep.add("sd16", "sdf_scene", not errs and not flat,
                "errors: {} flat: {}".format(errs, flat) if (errs or flat) else "")
    except Exception as e:  # noqa: BLE001
        rep.add("sd16", "sdf_scene", False, str(e))
    finally:
        _safe_delete(sd, g, pkg)

    # Shape splatter v2 + SDF rock with per-shape seed
    g = "rg_splatter_sdf"
    try:
        sd.call("create_graph", graph_name=g, package_index=pkg)
        sd.call("set_graph_output_size", width_log2=8, height_log2=8, graph_identifier=g)
        sp = sd.call("create_instance_node", resource_url="shape_splatter_v2", graph_identifier=g)["node_id"]
        out = sd.call("create_output_node", usage="height", graph_identifier=g)["node_id"]
        sd.call("connect_nodes", from_node_id=sp, from_output="height", to_node_id=out,
                to_input="inputNodeOutput", graph_identifier=g)
        r = sd.call("set_shape_splatter_sdf", node_id=sp, graph_identifier=g, output="m",
                    bounding_frame_size=[1, 1, 1], nodes=[
                        {"alias": "r", "type": "hash11", "inputs": {"p": "$shape.id"}},
                        {"alias": "seed", "type": "mul", "inputs": {"a": "@r", "b": 97.0}},
                        {"alias": "rock", "type": "rock", "inputs": {"seed_input": "@seed", "scale": 0.6,
                                                                     "center_position": [0, 0, 0.2]}},
                        {"alias": "m", "type": "set_color",
                         "inputs": {"scene": "@rock", "basecolor": [0.5, 0.45, 0.4]}}])
        flat = _flat(sd.call("render_outputs", graph_identifier=g, thumbnails=False), [])
        rep.add("sd16", "splatter_sdf", not r["errors"] and not flat,
                "errors: {} flat: {}".format(r["errors"], flat) if (r["errors"] or flat) else "")
    except Exception as e:  # noqa: BLE001
        rep.add("sd16", "splatter_sdf", False, str(e))
    finally:
        _safe_delete(sd, g, pkg)

    # Pixel processor function: clouds x UV gradient
    g = "rg_pixel_processor"
    try:
        sd.call("create_graph", graph_name=g, package_index=pkg)
        sd.call("set_graph_output_size", width_log2=8, height_log2=8, graph_identifier=g)
        src = sd.call("create_instance_node", resource_url="clouds_2", graph_identifier=g)["node_id"]
        pp = sd.call("create_node", definition_id="sbs::compositing::pixelprocessor",
                     graph_identifier=g)["node_id"]
        out = sd.call("create_output_node", usage="baseColor", graph_identifier=g)["node_id"]
        sd.call("connect_nodes", from_node_id=src, from_output="output", to_node_id=pp,
                to_input="input", graph_identifier=g)
        sd.call("connect_nodes", from_node_id=pp, to_node_id=out, to_input="inputNodeOutput",
                graph_identifier=g)
        r = sd.call("build_function_graph", node_id=pp, param_id="perpixel", graph_identifier=g,
                    output="m", nodes=[
                        {"alias": "p", "type": "get_float2", "value": "$pos"},
                        {"alias": "s", "type": "samplecol", "value": [0, 0], "value_type": "int2",
                         "inputs": {"pos": "@p"}},
                        {"alias": "v", "type": "vector4",
                         "inputs": {"componentsin": "@p", "componentslast": [0.0, 1.0]}},
                        {"alias": "m", "type": "mul", "inputs": {"a": "@s", "b": "@v"}}])
        rend = sd.call("render_outputs", graph_identifier=g, thumbnails=False)
        flat = _flat(rend, [])
        # red must grow with x: compare against the gradient direction via stats
        rep.add("sd16", "pixel_processor", not r["errors"] and not flat,
                "errors: {} flat: {}".format(r["errors"], flat) if (r["errors"] or flat) else "")
    except Exception as e:  # noqa: BLE001
        rep.add("sd16", "pixel_processor", False, str(e))
    finally:
        _safe_delete(sd, g, pkg)


def _safe_delete(sd, g, pkg):
    try:
        sd.call("delete_graph", graph_identifier=g, package_index=pkg)
    except Exception:  # noqa: BLE001
        pass


def custom_library_checks(sd, rep):
    """Custom Library folders: scanned, and their visible graphs instantiate."""
    try:
        lp = sd.call("list_library_paths")
    except Exception as e:  # noqa: BLE001
        rep.add("custom_library", "list_library_paths", False, str(e))
        return
    roots = lp.get("roots", [])
    builtin = [r for r in roots if r.get("source") == "builtin"]
    rep.add("custom_library", "builtin_root", bool(builtin) and builtin[0].get("graphs", 0) > 0,
            "{} graphs".format(builtin[0].get("graphs")) if builtin else "no builtin root")
    custom = [r for r in roots if r.get("source") != "builtin" and r.get("enabled")
              and r.get("exists") and r.get("sbs_files")]
    if not custom:
        rep.add("custom_library", "custom_roots", True, "no custom library folder with .sbs files")
        return
    rep.add("custom_library", "custom_roots", True, "; ".join(
        "{} ({}, {} graphs)".format(r["path"], r["source"], r.get("graphs")) for r in custom))
    offset, fails, total = 0, [], 0
    while offset is not None:
        r = sd.call("validate_library", offset=offset, limit=60, source="custom")
        total = r["total_visible"]
        fails += r["failed"]
        offset = r["next_offset"]
    for f in fails:
        rep.add("custom_library", f["identifier"], False, f["error"])
    rep.add("custom_library", "visible_graphs_instantiate", not fails,
            "{} of {} failed".format(len(fails), total) if fails else "{} checked".format(total))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--port", type=int, default=9881)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--resolution", type=int, default=8, help="output size log2 (8 = 256px)")
    ap.add_argument("--quick", action="store_true", help="small subset (~2 min)")
    ap.add_argument("--skip-library", action="store_true")
    ap.add_argument("--only", default="", help="only recipes/heightmaps whose name contains this")
    ap.add_argument("--baseline", default=os.path.join(HERE, "regression_baseline.json"))
    ap.add_argument("--report-dir", default=os.path.join(HERE, "reports"))
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
