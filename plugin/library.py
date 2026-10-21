"""
Library node resolution: graph identifiers -> .sbs files in SD's built-in
library (<SD>/resources/packages) and in custom Library folders, loaded on
demand, preferring the version visible in SD's Library.

Custom folders come from SD's own Library watched paths (Preferences >
Projects > Library), the plugin config (add_library_path) and the
SD_MCP_LIBRARY_PATHS environment variable — see library_paths.py.

References accepted everywhere a library node is expected
(create_instance_node resource_url, batch "resource_url"/"library_keyword"):
  perlin_noise                  identifier / keyword / Library label
  pkg:///perlin_noise           portable URL
  FloodFills.sbs#FloodFills     qualified: graph in a given package file
  D:/libs/rocks.sbs#rock_a      qualified with a full path (need not be indexed)
On an identifier collision the built-in graph wins unless qualified.
"""

import os
import re
import time
from .common import (
    SDError,
    _log,
    float2,
)
from . import library_paths as LP

_STALE_CHECK_SECONDS = 2.0


class LibraryMixin(object):
    """Mixed into CommandHandler."""

    # ── references ───────────────────────────────────────────────────────
    @staticmethod
    def _lib_identifier_from_ref(ref):
        return LP.split_ref(ref)[1]

    # ── roots / config ───────────────────────────────────────────────────
    def _lib_packages_dirs(self):
        """SD's built-in library folder(s)."""
        dirs = []
        try:
            from sd.api.sdapplication import SDApplicationPath
            rd = self._app().getPath(SDApplicationPath.DefaultResourcesDir)
            if rd:
                dirs.append(LP.norm_path(os.path.join(rd, "packages")))
        except SDError as e:
            _log("Warning: cannot read resources dir: {}".format(e))
        return [d for d in dirs if os.path.isdir(d)]

    def _lib_settings_dir(self):
        try:
            ver = self._app().getVersion()
        except SDError:
            ver = None
        return LP.sd_settings_dir(ver)

    def _lib_config_path(self):
        return LP.config_file_path()

    def _lib_config(self):
        return LP.load_config(self._lib_config_path())

    def _lib_roots(self):
        return LP.collect_library_roots(self._lib_packages_dirs(), self._lib_settings_dir(),
                                        self._lib_config())

    # ── scanning / index ─────────────────────────────────────────────────
    def _lib_state(self):
        st = getattr(self, "_lib_scan_state", None)
        if st is None:
            st = self._lib_scan_state = {"files": {}, "built": None, "signature": None,
                                         "checked": 0.0, "roots": []}
        return st

    def _lib_signature(self, roots, files):
        """Cheap change detector: config / SD project file mtimes plus the
        (path, mtime, size) of every .sbs under the non-builtin roots."""
        sig = []
        sd_dir = self._lib_settings_dir()
        extra = [self._lib_config_path()]
        if sd_dir:
            extra += [os.path.join(sd_dir, n) for n in
                      ("user_project.sbsprj", "default_project.sbsprj",
                       "default_configuration.sbscfg")]
        for p in extra:
            try:
                sig.append((p, os.path.getmtime(p)))
            except OSError:
                sig.append((p, None))
        for fp, src in files:
            if src == "builtin":
                continue
            try:
                st = os.stat(fp)
                sig.append((fp, st.st_mtime, st.st_size))
            except OSError:
                pass
        return tuple(sig)

    def _lib_list_files(self, roots):
        out, seen = [], set()
        for r in roots:
            for fp in LP.iter_sbs_files(r):
                k = fp.lower()
                if k not in seen:
                    seen.add(k)
                    out.append((fp, r["source"]))
        return out

    def _lib_invalidate(self):
        """Forget the index (rebuilt lazily). Parsed files stay cached by mtime."""
        st = self._lib_state()
        st["built"] = None
        st["signature"] = None
        self._lib_file_index = None
        self._fn_file_index = None
        self._lib_url_cache = {}

    def _lib_check_stale(self):
        st = self._lib_state()
        if st["built"] is None:
            return
        now = time.time()
        if now - st["checked"] < _STALE_CHECK_SECONDS:
            return
        st["checked"] = now
        roots = self._lib_roots()
        sig = self._lib_signature(roots, self._lib_list_files(roots))
        if sig != st["signature"]:
            _log("Library changed on disk - re-indexing")
            self._lib_invalidate()

    def _lib_build(self):
        """(Re)build graph + function indexes from every library root."""
        st = self._lib_state()
        if st["built"] is not None:
            return
        t0 = time.time()
        roots = self._lib_roots()
        root_of = {}
        files = self._lib_list_files(roots)
        g_index, g_hidden, fn_index, fn_hidden, meta = {}, set(), {}, set(), {}
        file_info, cache = {}, st["files"]
        for r in roots:
            r["sbs_files"] = 0
            r["graphs"] = 0
        by_path = {r["path"].lower(): r for r in roots}
        for fp, src in files:
            try:
                s = os.stat(fp)
                key = (s.st_mtime, s.st_size)
            except OSError:
                continue
            c = cache.get(fp)
            if c is None or c[0] != key:
                try:
                    with open(fp, "rb") as fh:
                        entries = LP.scan_sbs_bytes(fh.read())
                except (OSError, SDError) as e:
                    _log("Warning: cannot read {}: {}".format(fp, e))
                    continue
                c = cache[fp] = (key, entries)
            # library root this file belongs to (longest matching prefix)
            low = fp.lower()
            root = None
            d = os.path.dirname(low)
            while d:
                if d in by_path:
                    root = by_path[d]
                    break
                nd = os.path.dirname(d)
                if nd == d:
                    break
                d = nd
            root_of[fp] = root["path"] if root else None
            if root:
                root["sbs_files"] += 1
            file_info[fp] = {"source": src, "root": root_of[fp]}
            for e in c[1]:
                ident = e["identifier"]
                if e["kind"] == "graph":
                    g_index.setdefault(ident, []).append(fp)
                    if e["hidden"]:
                        g_hidden.add((ident, fp))
                    if root:
                        root["graphs"] += 1
                else:
                    fn_index.setdefault(ident, []).append(fp)
                    if e["hidden"]:
                        fn_hidden.add((ident, fp))
                meta[(e["kind"], ident, fp)] = e
        self._lib_file_index, self._lib_hidden = g_index, g_hidden
        self._fn_file_index, self._fn_hidden = fn_index, fn_hidden
        self._lib_meta, self._lib_file_info = meta, file_info
        st["roots"] = roots
        st["signature"] = self._lib_signature(roots, files)
        st["built"] = st["checked"] = time.time()
        custom = sum(1 for i in file_info.values() if i["source"] != "builtin")
        _log("Library index: {} graphs, {} functions, {} files ({} custom) in {:.2f}s".format(
            len(g_index), len(fn_index), len(file_info), custom, time.time() - t0))

    def _lib_index(self):
        """identifier -> list of absolute .sbs paths (graphs)."""
        self._lib_check_stale()
        if getattr(self, "_lib_file_index", None) is None:
            self._lib_state()["built"] = None
            self._lib_build()
        return self._lib_file_index

    def _lib_source(self, path):
        info = getattr(self, "_lib_file_info", {}).get(path)
        return info["source"] if info else "other"

    def _rank_lib_file(self, identifier, path):
        """Lower is better. The same identifier often exists in several files,
        e.g. clouds_2 in clouds_2.sbs (Legacy, hidden, output 'Clouds_2'),
        noise_clouds_2.sbs (hidden) and noise_clouds_2_v2.sbs (current, output
        'output'). Prefer the version SD shows in its Library (no hideInLibrary),
        then the built-in library over custom folders, then a file named after
        the identifier, then the newest '_vN'."""
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        ident = identifier.lower()
        hidden = (identifier, path) in self._lib_hidden
        if stem == ident or stem.endswith("_" + ident) or \
                re.sub(r"_v\d+$", "", stem).endswith(ident):
            name_score = 0
        elif ident.startswith(stem):
            name_score = 1
        else:
            name_score = 2
        m = re.search(r"_v(\d+)$", stem)
        ver = int(m.group(1)) if m else 1
        builtin = 0 if self._lib_source(path) == "builtin" else 1
        return (1 if hidden else 0, builtin, name_score, -ver, len(stem), stem)

    def _resolve_lib_identifier(self, keyword):
        """Map a keyword / identifier / label / pkg URL to an exact library
        graph identifier. Fuzzy (prefix / substring) matches prefer the
        built-in library so custom folders never change what a recipe gets."""
        ident = self._lib_identifier_from_ref(keyword)
        key = ident.lower()
        index = self._lib_index()
        if key in self._lib_url_cache:
            return self._lib_url_cache[key]
        by_lower = {}
        for k in index:
            by_lower.setdefault(k.lower(), k)
        found = by_lower.get(key)
        if not found:
            def builtin_first(k):
                files = index[by_lower[k]]
                has_builtin = any(self._lib_source(f) == "builtin" for f in files)
                return (0 if has_builtin else 1, len(k), k)
            cands = [k for k in by_lower if k.startswith(key)] or \
                    [k for k in by_lower if key in k]
            if cands:
                cands.sort(key=builtin_first)
                found = by_lower[cands[0]]
        if not found:
            # Library label ("Flood Fills"), visible graphs first
            squash = re.sub(r"[\s_\-]+", "", key)
            hits = []
            for (kind, gid, fp), e in getattr(self, "_lib_meta", {}).items():
                if kind == "graph" and squash and \
                        re.sub(r"[\s_\-]+", "", (e.get("label") or "").lower()) == squash:
                    hits.append((self._rank_lib_file(gid, fp), gid))
            if hits:
                found = min(hits)[1]
        if not found:
            # graphs inside packages that are already loaded (user packages etc.)
            for pkg in list(self._pkg_mgr().getPackages()):
                try:
                    for res in pkg.getChildrenResources(True):
                        if "SDSBSCompGraph" in res.getClassName() and \
                                key in res.getIdentifier().lower():
                            found = res.getIdentifier()
                            break
                except SDError:
                    pass
                if found:
                    break
        if found:
            self._lib_url_cache[key] = found
        return found

    def _lib_files_for_hint(self, hint, ident):
        """Files for a qualified reference 'pkg.sbs#ident' (hint = file name,
        stem or full path). A full path to an existing file is accepted even
        when it is not in a library folder."""
        h = hint.replace("\\", "/").lower()
        if os.path.isfile(hint):
            return [LP.norm_path(hint)]
        out = []
        index = self._lib_index()
        for k, files in index.items():
            if k.lower() != ident.lower():
                continue
            for f in files:
                fl = f.lower()
                base = os.path.basename(fl)
                if h in (fl, base, os.path.splitext(base)[0]) or fl.endswith("/" + h):
                    out.append(f)
        return out

    @staticmethod
    def _find_graph_in_package(pkg, ident):
        """Find a compositing graph by identifier, including graphs stored in
        package folders (e.g. constant_values.sbs -> pkg:///float/constant_float),
        which findResourceFromUrl(identifier) does not resolve."""
        try:
            r = pkg.findResourceFromUrl(ident)
            if r is not None and "SDSBSCompGraph" in r.getClassName():
                return r
        except SDError:
            pass
        try:
            for r in pkg.getChildrenResources(True):
                if r.getIdentifier() == ident and "SDSBSCompGraph" in r.getClassName():
                    return r
        except SDError:
            pass
        try:
            low = ident.lower()
            for r in pkg.getChildrenResources(True):
                if r.getIdentifier().lower() == low and "SDSBSCompGraph" in r.getClassName():
                    return r
        except SDError:
            pass
        return None

    def _get_library_resource(self, ref):
        """Return (resource, temp_package_or_None). Caller should pass the temp
        package to _release_temp_lib_package() after instancing."""
        pkg_mgr = self._pkg_mgr()
        loaded = list(pkg_mgr.getPackages())
        hint, raw_ident = LP.split_ref(ref)
        # 1. exact package-relative URL ("pkg:///x?dependency=N") — only when a
        #    dependency UID is given. A bare "pkg:///x" must NOT be matched this
        #    way: any loaded package (e.g. a hidden Legacy copy pulled in as a
        #    dependency of another library graph) would satisfy it, and Legacy
        #    graphs have different port names (cells_1 -> 'Cells' vs 'output').
        if ref and ref.startswith("pkg:///") and "?dependency=" in ref:
            for p in loaded:
                try:
                    r = p.findResourceFromUrl(ref)
                    if r is not None:
                        return r, None
                except SDError:
                    pass
        if hint:
            # qualified reference: only the named package file
            ident = raw_ident
            files = self._lib_files_for_hint(hint, ident)
            if not files:
                return None, None
        else:
            ident = self._resolve_lib_identifier(ref)
            if not ident:
                return None, None
            files = sorted(self._lib_index().get(ident, []),
                           key=lambda f: self._rank_lib_file(ident, f))
        # 2. identifier inside an already-loaded package. Only accept the
        #    preferred file: a hidden Legacy copy may already be loaded as a
        #    dependency and has different port names.
        best = files[0].lower() if files else None
        for p in loaded:
            try:
                if best and (p.getFilePath() or "").replace("\\", "/").lower() != best:
                    continue
                r = self._find_graph_in_package(p, ident)
                if r is not None:
                    return r, None
            except SDError:
                pass
        # 3. load the library package on demand
        for fp in files:
            try:
                was_user = any((u.getFilePath() or "").replace("\\", "/").lower() == fp.lower()
                               for u in pkg_mgr.getUserPackages())
            except SDError:
                was_user = False
            try:
                pkg = pkg_mgr.loadUserPackage(fp)
            except SDError as e:
                _log("Warning: loadUserPackage({}) failed: {}".format(fp, e))
                continue
            if pkg is None:
                continue
            r = self._find_graph_in_package(pkg, ident)
            if r is not None:
                return r, (None if was_user else pkg)
            if not was_user:
                self._release_temp_lib_package(pkg)
        return None, None

    def _release_temp_lib_package(self, pkg):
        """Unload a library package we loaded as a *user* package. If a graph now
        depends on it, SD keeps it loaded as a hidden dependency."""
        if pkg is None:
            return
        try:
            self._pkg_mgr().unloadUserPackage(pkg)
        except SDError as e:
            _log("Warning: unloadUserPackage failed: {}".format(e))

    def _new_library_node(self, graph, ref, position=None):
        resource, temp_pkg = self._get_library_resource(ref)
        if resource is None:
            raise ValueError(
                "Library node '{}' not found. "
                "Use get_library_nodes(filter_text=...) to search, "
                "list_library_paths() to see the scanned folders.".format(ref))
        try:
            node = graph.newInstanceNode(resource)
        finally:
            self._release_temp_lib_package(temp_pkg)
        if not node:
            raise RuntimeError("newInstanceNode failed for '{}'.".format(ref))
        if position and len(position) >= 2:
            node.setPosition(float2(float(position[0]), float(position[1])))
        return node

    def _create_library_node(self, graph, keyword, position=None):
        """Create a library node from a keyword / identifier / pkg URL."""
        return self._new_library_node(graph, keyword, position)

    # ── tools ────────────────────────────────────────────────────────────
    def _lib_entry(self, ident, fp, best):
        e = getattr(self, "_lib_meta", {}).get(("graph", ident, fp), {})
        info = getattr(self, "_lib_file_info", {}).get(fp, {})
        src = info.get("source", "other")
        out = {
            "identifier": ident,
            "url":        "pkg:///{}".format(ident) if fp == best
                          else "{}#{}".format(os.path.basename(fp), ident),
            "package":    os.path.basename(fp),
            "source":     "library" if src == "builtin" else "custom",
        }
        if src != "builtin":
            out["path"] = fp
            out["library_root"] = info.get("root")
            out["root_source"] = src
            for k in ("label", "category", "author"):
                if e.get(k):
                    out[k] = e[k]
            if e.get("description"):
                out["description"] = e["description"][:240]
        if e.get("hidden"):
            out["hidden"] = True
        if fp != best:
            out["shadowed_by"] = os.path.basename(best)
        return out

    def get_library_nodes(self, filter_text="", limit=200, source="all",
                          include_hidden=True):
        """Search SD's built-in library (resources/packages), custom Library
        folders and graphs in loaded packages.
        source: all | builtin | custom | loaded.
        Returned URLs are 'pkg:///<identifier>' (or 'file.sbs#identifier'
        for a custom graph whose identifier is shadowed by another file)."""
        ft = (filter_text or "").lower()
        source = (source or "all").lower()
        results, seen = [], set()
        index = self._lib_index()
        meta = getattr(self, "_lib_meta", {})

        def matches(ident, fp):
            if not ft:
                return True
            if ft in ident.lower():
                return True
            e = meta.get(("graph", ident, fp), {})
            return any(ft in (e.get(k) or "").lower() for k in ("label", "category", "tags"))

        if source in ("all", "builtin", "custom", "library"):
            for ident in sorted(index, key=lambda k: (len(k), k)):
                files = sorted(index[ident], key=lambda f: self._rank_lib_file(ident, f))
                best = files[0]
                # one entry per identifier + custom copies shadowed by another file
                cands = [best] + [f for f in files[1:] if self._lib_source(f) != "builtin"]
                for fp in cands:
                    src = self._lib_source(fp)
                    if source in ("builtin", "library") and src != "builtin":
                        continue
                    if source == "custom" and src == "builtin":
                        continue
                    if not include_hidden and (ident, fp) in self._lib_hidden:
                        continue
                    if not matches(ident, fp):
                        continue
                    results.append(self._lib_entry(ident, fp, best))
                    seen.add(ident.lower())
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
        if len(results) < limit and source in ("all", "loaded"):
            for pkg in list(self._pkg_mgr().getPackages()):
                try:
                    fp = pkg.getFilePath() or "(unsaved)"
                    for res in pkg.getChildrenResources(True):
                        if "SDSBSCompGraph" not in res.getClassName():
                            continue
                        rid = res.getIdentifier()
                        if rid.lower() in seen or (ft and ft not in rid.lower()):
                            continue
                        seen.add(rid.lower())
                        results.append({
                            "identifier": rid,
                            "url":        res.getUrl(),
                            "package":    os.path.basename(fp),
                            "source":     "loaded_package",
                        })
                        if len(results) >= limit:
                            break
                except SDError:
                    pass
                if len(results) >= limit:
                    break
        return {
            "count":     len(results),
            "nodes":     results,
            "truncated": len(results) >= limit,
            "filter":    filter_text,
            "source":    source,
        }

    def list_library_paths(self):
        """Every folder the plugin scans for .sbs packages, where it comes
        from, and how many packages / graphs were found in it."""
        self._lib_index()
        st = self._lib_state()
        roots = []
        for r in st["roots"]:
            d = {k: r.get(k) for k in ("path", "source", "recursive", "enabled", "exists",
                                       "sbs_files", "graphs")}
            for k in ("project", "url", "label", "ignored", "also_in"):
                if r.get(k):
                    d[k] = r[k]
            if r.get("exclude"):
                d["exclude"] = r["exclude"]
            roots.append(d)
        cfg = self._lib_config()
        return {
            "roots":                roots,
            "config_file":          self._lib_config_path(),
            "sd_settings_dir":      self._lib_settings_dir(),
            "use_sd_project_paths": cfg.get("use_sd_project_paths", True),
            "env_var":              LP.ENV_VAR,
            "graphs":               len(self._lib_file_index or {}),
            "functions":            len(getattr(self, "_fn_file_index", None) or {}),
        }

    def add_library_path(self, path, recursive=True, label=""):
        """Add a folder of .sbs packages to the plugin's persistent config
        (survives SD restarts, plugin updates and SD upgrades)."""
        if not path:
            raise ValueError("path is required")
        p = LP.norm_path(path)
        if os.path.isfile(p) and p.lower().endswith(".sbs"):
            raise ValueError("Give the folder that contains the .sbs, not the file: {}".format(
                os.path.dirname(p)))
        if not os.path.isdir(p):
            raise ValueError("Folder not found: {}".format(p))
        cfg_path = self._lib_config_path()
        cfg = LP.load_config(cfg_path)
        k = p.lower()
        cfg["ignored"] = [x for x in cfg["ignored"] if x.lower() != k]
        existing = next((x for x in cfg["paths"] if x["path"].lower() == k), None)
        if existing:
            existing.update({"recursive": bool(recursive), "enabled": True})
            if label:
                existing["label"] = label
        else:
            cfg["paths"].append({"path": p, "recursive": bool(recursive),
                                 "enabled": True, "label": label or ""})
        LP.save_config(cfg_path, cfg)
        self._lib_invalidate()
        res = self.list_library_paths()
        root = next((r for r in res["roots"] if r["path"].lower() == k), None)
        return {"added": p, "recursive": bool(recursive), "config_file": cfg_path,
                "root": root, "already_configured": bool(existing)}

    def remove_library_path(self, path):
        """Remove a folder added with add_library_path. For a folder that
        comes from SD's own Library settings it is ignored by the plugin
        instead (SD's settings are not modified)."""
        p = LP.norm_path(path)
        k = p.lower()
        cfg_path = self._lib_config_path()
        cfg = LP.load_config(cfg_path)
        before = len(cfg["paths"])
        cfg["paths"] = [x for x in cfg["paths"] if x["path"].lower() != k]
        removed = len(cfg["paths"]) < before
        sd_paths = {(w.get("path") or "").lower()
                    for w in LP.sd_project_watched_paths(self._lib_settings_dir())}
        ignored = False
        if k in sd_paths and k not in {x.lower() for x in cfg["ignored"]}:
            cfg["ignored"].append(p)
            ignored = True
        if not removed and not ignored:
            return {"removed": False, "path": p,
                    "message": "Not a configured library path (see list_library_paths)."}
        LP.save_config(cfg_path, cfg)
        self._lib_invalidate()
        return {"removed": removed, "ignored_sd_path": ignored, "path": p,
                "config_file": cfg_path}

    def rescan_library(self):
        """Re-read every library folder now (normally automatic: changes are
        detected within a few seconds)."""
        self._lib_invalidate()
        t0 = time.time()
        self._lib_index()
        res = self.list_library_paths()
        res["seconds"] = round(time.time() - t0, 2)
        return res
