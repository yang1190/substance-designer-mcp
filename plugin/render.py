"""
Render / inspect / export tools for the SD MCP plugin.

Lets an AI client *see* what it built:
  render_outputs   compute a graph, return per-output pixel statistics and
                   PNG thumbnails (base64) of every output node
  export_outputs   compute and write output textures to disk (png/tga/exr/tif/jpg)
  validate_library instantiate every Library graph (batched) to detect broken
                   library resolution after an SD update
  close_package    unload a (temporary) package

Pixel access reads SDTexture.getPixelBufferAddress() directly (no temp files);
formats handled: 8/16-bit int, 16F (half) and 32F, 1 (LUM) or 4 (RGBA) channels.
"""

import ctypes
import math
import os
import re
import struct
import time
import base64

from sd.api.sdproperty import SDPropertyCategory

from .common import SDError




# ── raw texture access ───────────────────────────────────────────────────────
def _texture_layout(tex):
    """-> (channels, kind, bytes_per_channel) where kind in u8/u16/f16/f32."""
    fmt = str(tex.getPixelFormat()).split(".")[-1].upper()
    bpp = tex.getBytesPerPixel()
    channels = 1 if ("LUM" in fmt or "GRAY" in fmt or "L16" in fmt or "L8" in fmt) else 4
    bpc = max(1, bpp // channels)
    if "32F" in fmt or (bpc == 4):
        kind = "f32"
    elif "16F" in fmt:
        kind = "f16"
    elif bpc == 2:
        kind = "u16"
    else:
        kind = "u8"
    return channels, kind, bpc, fmt


def _sample_texture(tex, max_side=256):
    """Nearest-neighbour downsample to <= max_side. Returns
    (w, h, channels, rows) where rows is a list of lists of floats in [0..1]
    (or raw float values for float formats), row-major, channel-interleaved."""
    size = tex.getSize()
    W, H = int(size.x), int(size.y)
    channels, kind, bpc, fmt = _texture_layout(tex)
    pitch = tex.getRowPitch()
    addr = tex.getPixelBufferAddress()
    step = max(1, int(math.ceil(max(W, H) / float(max_side))))
    w, h = (W + step - 1) // step, (H + step - 1) // step
    rows = []
    px_bytes = channels * bpc
    for y in range(0, H, step):
        row_addr = addr + y * pitch
        raw = ctypes.string_at(row_addr, W * px_bytes)
        if kind == "u8":
            vals = raw
            scale = 1.0 / 255.0
            conv = lambda i: vals[i] * scale  # noqa: E731
        elif kind == "u16":
            vals = struct.unpack("<%dH" % (W * channels), raw)
            scale = 1.0 / 65535.0
            conv = lambda i: vals[i] * scale  # noqa: E731
        elif kind == "f16":
            vals = struct.unpack("<%de" % (W * channels), raw)
            conv = lambda i: float(vals[i])  # noqa: E731
        else:
            vals = struct.unpack("<%df" % (W * channels), raw)
            conv = lambda i: float(vals[i])  # noqa: E731
        out = []
        for x in range(0, W, step):
            base = x * channels
            for c in range(channels):
                out.append(conv(base + c))
        rows.append(out)
    return w, h, channels, rows, fmt


def _stats(w, h, channels, rows):
    """Per-channel min/max/mean/std over the sampled pixels (RGB(A) or L)."""
    n = w * h
    names = ["L"] if channels == 1 else ["R", "G", "B", "A"]
    res = {}
    for c, name in enumerate(names):
        vals = [r[i] for r in rows for i in range(c, len(r), channels)]
        if not vals:
            continue
        mn, mx = min(vals), max(vals)
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        res[name] = {"min": round(mn, 4), "max": round(mx, 4),
                     "mean": round(mean, 4), "std": round(math.sqrt(var), 4)}
    color = [k for k in ("R", "G", "B", "L") if k in res]
    max_std = max(res[k]["std"] for k in color) if color else 0.0
    rng = max(res[k]["max"] - res[k]["min"] for k in color) if color else 0.0
    return {
        "channels": res,
        "samples": n,
        "max_std": round(max_std, 4),
        "flat": max_std < 0.004,         # uniform (std below one 8-bit level)
        "low_contrast": max_std < 0.02,  # barely any variation
        "value_range": round(rng, 4),
    }


def _encode_png(w, h, channels, rows, normalize=False):
    """Encode sampled pixels as PNG bytes using Qt (bundled with SD)."""
    from PySide6.QtGui import QImage
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    lo, hi = 0.0, 1.0
    if normalize:
        flat = [v for r in rows for i, v in enumerate(r) if channels == 1 or i % 4 != 3]
        if flat:
            lo, hi = min(flat), max(flat)
            if hi - lo < 1e-6:
                hi = lo + 1e-6
    span = hi - lo
    buf = bytearray()
    for r in rows:
        if channels == 1:
            for v in r:
                g = int(max(0.0, min(1.0, (v - lo) / span)) * 255 + 0.5)
                buf += bytes((g, g, g, 255))
        else:
            for i in range(0, len(r), 4):
                rr, gg, bb = r[i], r[i + 1], r[i + 2]
                buf += bytes((int(max(0.0, min(1.0, (rr - lo) / span)) * 255 + 0.5),
                              int(max(0.0, min(1.0, (gg - lo) / span)) * 255 + 0.5),
                              int(max(0.0, min(1.0, (bb - lo) / span)) * 255 + 0.5),
                              255))
    img = QImage(bytes(buf), w, h, w * 4, QImage.Format_RGBA8888).copy()
    ba = QByteArray()
    qbuf = QBuffer(ba)
    qbuf.open(QIODevice.WriteOnly)
    img.save(qbuf, "PNG")
    qbuf.close()
    return bytes(ba.data())


class RenderMixin(object):
    """Mixed into CommandHandler. Relies on _resolve_graph, _pkg_mgr,
    _graph_material_model, _new_library_node, _lib_index, _lib_hidden, _lib_source."""

    # ── helpers ────────────────────────────────────────────────────────────
    def _output_nodes(self, graph, output_ids=None):
        wanted = set(output_ids or [])
        res = []
        for n in graph.getNodes():
            if n.getDefinition().getId() != "sbs::compositing::output":
                continue
            info = {"node_id": n.getIdentifier()}
            for key in ("identifier", "label"):
                try:
                    v = n.getAnnotationPropertyValueFromId(key)
                    info[key] = v.get() if v is not None else ""
                except SDError:
                    info[key] = ""
            try:
                arr = n.getAnnotationPropertyValueFromId("usages").get()
                info["usages"] = [arr.getItem(i).get().getName() for i in range(arr.getSize())]
            except SDError:
                info["usages"] = []
            if wanted and not (wanted & {info["node_id"], info["identifier"], info["label"]}
                               or wanted & set(info["usages"])):
                continue
            res.append((n, info))
        try:
            res.sort(key=lambda t: (t[0].getPosition().y, t[0].getPosition().x))
        except SDError:
            pass
        return res

    @staticmethod
    def _output_texture(node):
        for p in node.getProperties(SDPropertyCategory.Output):
            v = node.getPropertyValue(p)
            if v is not None:
                t = v.get()
                if t is not None and hasattr(t, "getPixelBufferAddress"):
                    return t
        return None

    # ── public commands ────────────────────────────────────────────────────
    def render_outputs(self, graph_identifier=None, output_ids=None, thumbnails=True,
                       thumbnail_size=256, normalize_grayscale=True, compute=True):
        """Compute the graph and return, for every output node: identifier,
        usages, size, pixel format, per-channel statistics (min/max/mean/std,
        'flat' when visually uniform) and optionally a PNG thumbnail (base64).
        Grayscale thumbnails are normalized to their own range by default so
        low-contrast heights stay readable (stats stay un-normalized)."""
        graph = self._resolve_graph(graph_identifier)
        t0 = time.time()
        if compute:
            graph.compute()
        compute_s = round(time.time() - t0, 3)
        thumbnail_size = max(16, min(int(thumbnail_size or 256), 1024))
        outputs, warnings = [], []
        nodes = self._output_nodes(graph, output_ids)
        # The engine occasionally returns no texture for a freshly built graph
        # (seen once in a 79-recipe regression run): recompute once before failing.
        if compute and any(self._output_texture(n) is None for n, _ in nodes):
            graph.compute()
            compute_s = round(time.time() - t0, 3)
        for node, info in nodes:
            tex = self._output_texture(node)
            if tex is None:
                info["error"] = "no texture (output not connected or not computed)"
                outputs.append(info)
                continue
            size = tex.getSize()
            info["size"] = [int(size.x), int(size.y)]
            try:
                w, h, ch, rows, fmt = _sample_texture(tex, thumbnail_size)
                info["format"] = fmt
                info["stats"] = _stats(w, h, ch, rows)
                if info["stats"]["flat"]:
                    warnings.append("{} is flat (uniform)".format(
                        info.get("identifier") or info["node_id"]))
                if thumbnails:
                    png = _encode_png(w, h, ch, rows, normalize=(normalize_grayscale and ch == 1))
                    info["thumbnail_png_base64"] = base64.b64encode(png).decode("ascii")
                    info["thumbnail_size"] = [w, h]
                    info["thumbnail_normalized"] = bool(normalize_grayscale and ch == 1)
            except SDError as e:
                info["error"] = "pixel read failed: {}".format(e)
            outputs.append(info)
        return {"graph": graph.getIdentifier(),
                "material_model": self._graph_material_model(graph),
                "compute_seconds": compute_s, "output_count": len(outputs),
                "warnings": warnings, "outputs": outputs}

    def export_outputs(self, directory, graph_identifier=None, output_ids=None,
                       file_format="png", name_pattern="{graph}_{identifier}",
                       compute=True):
        """Compute the graph and save each output texture to `directory`.
        file_format: png, tga, exr, tif, jpg, bmp... (SDTexture.save picks the
        writer from the extension). name_pattern keys: graph, identifier,
        label, node_id, usage."""
        graph = self._resolve_graph(graph_identifier)
        if not directory:
            raise ValueError("directory is required")
        directory = os.path.abspath(os.path.expanduser(directory))
        os.makedirs(directory, exist_ok=True)
        ext = file_format.lower().lstrip(".")
        if compute:
            graph.compute()
        written, errors = [], []
        for node, info in self._output_nodes(graph, output_ids):
            tex = self._output_texture(node)
            if tex is None:
                errors.append({"node_id": info["node_id"], "error": "no texture"})
                continue
            name = name_pattern.format(
                graph=graph.getIdentifier(), identifier=info.get("identifier") or info["node_id"],
                label=info.get("label") or "", node_id=info["node_id"],
                usage=(info.get("usages") or [""])[0])
            name = re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or info["node_id"]
            path = os.path.join(directory, "{}.{}".format(name, ext)).replace("\\", "/")
            try:
                tex.save(path)
                written.append({"identifier": info.get("identifier"), "path": path,
                                "bytes": os.path.getsize(path) if os.path.exists(path) else None})
            except SDError as e:
                errors.append({"identifier": info.get("identifier"), "error": str(e)})
        return {"graph": graph.getIdentifier(), "directory": directory.replace("\\", "/"),
                "written": written, "errors": errors}

    def validate_library(self, offset=0, limit=150, filter_text="", source="all"):
        """Instantiate visible Library graphs in a throw-away package to check
        that library resolution works (run in batches: offset/limit). Returns
        failures and 'next_offset' (None when done).
        source: all | builtin | custom (graphs from custom Library folders)."""
        idx = self._lib_index()
        ft = (filter_text or "").lower()
        source = (source or "all").lower()

        def wanted(k):
            files = [f for f in idx[k] if (k, f) not in self._lib_hidden]
            if source == "builtin":
                files = [f for f in files if self._lib_source(f) == "builtin"]
            elif source == "custom":
                files = [f for f in files if self._lib_source(f) != "builtin"]
            return bool(files) and (not ft or ft in k.lower())
        names = sorted(k for k in idx if wanted(k))
        if source == "custom":
            # address custom graphs explicitly: built-in wins on collisions
            names = [k if all(self._lib_source(f) != "builtin" for f in idx[k]) else
                     "{}#{}".format(next(f for f in idx[k] if self._lib_source(f) != "builtin"), k)
                     for k in names]
        batch = names[offset:offset + limit]
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        pm = self._pkg_mgr()
        before = {(p.getFilePath() or "").replace("\\", "/").lower()
                  for p in pm.getUserPackages()}
        tmp = pm.newUserPackage()
        ok, failed = 0, []
        t0 = time.time()
        try:
            g = SDSBSCompGraph.sNew(tmp)
            g.setIdentifier("mcp_validate_library")
            for ident in batch:
                try:
                    n = self._new_library_node(g, ident)
                    g.deleteNode(n)
                    ok += 1
                except SDError as e:
                    failed.append({"identifier": ident, "error": str(e)[:200]})
        finally:
            try:
                pm.unloadUserPackage(tmp)
            except SDError:
                pass
            # drop library packages that ended up as user packages
            lib_files = {f.lower() for f in getattr(self, "_lib_file_info", {})}
            for p in list(pm.getUserPackages()):
                fp = (p.getFilePath() or "").replace("\\", "/")
                if fp.lower() in before:
                    continue  # opened by the user: never touch
                if "/resources/packages/" in fp or fp.lower() in lib_files:
                    try:
                        pm.unloadUserPackage(p)
                    except SDError:
                        pass
        nxt = offset + limit
        return {"total_visible": len(names), "offset": offset, "checked": len(batch),
                "ok": ok, "failed": failed, "seconds": round(time.time() - t0, 2),
                "next_offset": nxt if nxt < len(names) else None}

    def close_package(self, package_index=None, package_path=None, force=False):
        """Unload a user package. Refuses a saved package with unsaved changes
        unless force=True (unsaved/new packages are closed directly)."""
        pm = self._pkg_mgr()
        pkgs = list(pm.getUserPackages())
        target = None
        if package_path:
            norm = package_path.replace("\\", "/").lower()
            target = next((p for p in pkgs
                           if (p.getFilePath() or "").replace("\\", "/").lower() == norm), None)
        elif package_index is not None and 0 <= int(package_index) < len(pkgs):
            target = pkgs[int(package_index)]
        if target is None:
            raise ValueError("Package not found (index={}, path={}).".format(package_index, package_path))
        fp = target.getFilePath() or ""
        try:
            modified = target.isModified()
        except SDError:
            modified = False
        if fp and modified and not force:
            raise RuntimeError("Package '{}' has unsaved changes; save it or pass force=True."
                               .format(fp))
        pm.unloadUserPackage(target)
        return {"closed": fp or "(unsaved package)", "was_modified": bool(modified)}
