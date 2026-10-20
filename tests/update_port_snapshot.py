#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Regenerate tests/data/sd_node_ports.json from a live Substance 3D Designer.

The snapshot lists, for every node type used by the built-in recipes (atomic
definitions and Library graphs), its input ports, output ports and parameter
ids. tests/test_offline.py validates every recipe against it WITHOUT needing
SD, so CI can catch wrong port names or misspelled parameters.

Run after an SD update (SD running with the MCP plugin):
    python tests/update_port_snapshot.py
"""
import json
import os
import socket
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "sd_node_ports.json")

# Executed inside SD (via the plugin's execute_code command). Writes OUT.
SNIPPET = r'''
import json, sys
from sd.api.sdproperty import SDPropertyCategory
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
P = sys.modules["sd_mcp_plugin"]
h = P.CommandHandler()
R = __import__("sd_mcp_plugin.recipes", fromlist=["x"])
types = set()
def collect(rec):
    for n in rec.get("nodes", []):
        if n.get("resource_url"):
            types.add(("library", h._lib_identifier_from_ref(n["resource_url"])))
        elif n.get("library_keyword"):
            types.add(("library", n["library_keyword"]))
        else:
            types.add(("atomic", n.get("definition_id", "sbs::compositing::uniform")))
for rec in R.RECIPE_REGISTRY.values():
    collect(rec)
for b in R.HEIGHTMAP_RECIPES.values():
    collect(b(detail_level=3, scale=5.0, disorder=0.5))
pm = app.getPackageMgr()
tmp = pm.newUserPackage()
out = {"sd_version": app.getVersion(), "plugin_version": ".".join(map(str, P.PLUGIN_VERSION)),
       "atomic": {}, "library": {}}
try:
    g = SDSBSCompGraph.sNew(tmp)
    for kind, key in sorted(types):
        try:
            node = g.newNode(key) if kind == "atomic" else h._new_library_node(g, key)
            ins = [p.getId() for p in node.getProperties(SDPropertyCategory.Input) if p.isConnectable()]
            outs = [p.getId() for p in node.getProperties(SDPropertyCategory.Output)]
            params = {p.getId(): p.getType().getId()
                      for p in node.getProperties(SDPropertyCategory.Input) if not p.isConnectable()}
            annots = [p.getId() for p in node.getProperties(SDPropertyCategory.Annotation)]
            out[kind][key] = {"inputs": ins, "outputs": outs, "parameters": params, "annotations": annots}
        except BaseException as e:
            out[kind][key] = {"error": str(e)}
finally:
    pm.unloadUserPackage(tmp)
open(__OUT__, "w").write(json.dumps(out, indent=1, sort_keys=True))
print("written", len(out["atomic"]), "atomic,", len(out["library"]), "library types")
'''


def _call(cmd, params, port=9881, timeout=180):
    data = json.dumps({"type": cmd, "params": params}).encode("utf-8")
    s = socket.create_connection(("localhost", port), timeout=10)
    try:
        s.settimeout(timeout)
        s.sendall(struct.pack(">I", len(data)) + data)
        def rx(n):
            b = b""
            while len(b) < n:
                c = s.recv(n - len(b))
                if not c:
                    raise ConnectionError("closed")
                b += c
            return b
        n = struct.unpack(">I", rx(4))[0]
        return json.loads(rx(n).decode("utf-8"))
    finally:
        s.close()


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    code = SNIPPET.replace("__OUT__", repr(OUT.replace("\\", "/")))
    resp = _call("execute_code", {"code": code})
    res = resp.get("result") or {}
    print(res.get("stdout", "").strip() or resp)
    if res.get("error"):
        print(res.get("stderr"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
