"""
Library node resolution: graph identifiers -> <SD>/resources/packages,
loaded on demand, preferring the version visible in SD's Library.
"""

import os
import re
from .common import (
    SDError,
    _log,
    float2,
)


class LibraryMixin(object):
    """Mixed into CommandHandler."""

    _LIB_GRAPH_RE = re.compile(rb'<graph>\s*<identifier v="([^"]+)"')

    @staticmethod
    def _lib_identifier_from_ref(ref):
        ref = (ref or "").strip()
        if ref.startswith("pkg:///"):
            ref = ref[len("pkg:///"):]
        return ref.split("?", 1)[0].strip("/")

    def _lib_packages_dirs(self):
        dirs = []
        try:
            from sd.api.sdapplication import SDApplicationPath
            rd = self._app().getPath(SDApplicationPath.DefaultResourcesDir)
            if rd:
                dirs.append(os.path.join(rd, "packages"))
        except SDError as e:
            _log("Warning: cannot read resources dir: {}".format(e))
        return [d for d in dirs if os.path.isdir(d)]

    def _lib_index(self):
        """identifier -> sorted list of absolute .sbs paths (built once per session)."""
        if self._lib_file_index is not None:
            return self._lib_file_index
        index, hidden_set = {}, set()
        for d in self._lib_packages_dirs():
            try:
                names = os.listdir(d)
            except SDError:
                continue
            for fn in names:
                if not fn.lower().endswith(".sbs"):
                    continue
                fp = os.path.join(d, fn).replace("\\", "/")
                try:
                    with open(fp, "rb") as fh:
                        data = fh.read()
                except SDError:
                    continue
                matches = list(self._LIB_GRAPH_RE.finditer(data))
                for i, m in enumerate(matches):
                    try:
                        ident = m.group(1).decode("utf-8")
                    except SDError:
                        continue
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(data)
                    a_end = data.find(b"</attributes>", m.end(), end)
                    hidden = a_end >= 0 and \
                        data.find(b'<hideInLibrary v="1"/>', m.end(), a_end) >= 0
                    index.setdefault(ident, []).append(fp)
                    if hidden:
                        hidden_set.add((ident, fp))
        self._lib_file_index = index
        self._lib_hidden = hidden_set
        _log("Library index: {} graphs".format(len(index)))
        return index

    def _rank_lib_file(self, identifier, path):
        """Lower is better. The same identifier often exists in several files,
        e.g. clouds_2 in clouds_2.sbs (Legacy, hidden, output 'Clouds_2'),
        noise_clouds_2.sbs (hidden) and noise_clouds_2_v2.sbs (current, output
        'output'). Prefer the version SD shows in its Library (no hideInLibrary),
        then a file named after the identifier, then the newest '_vN'."""
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
        return (1 if hidden else 0, name_score, -ver, len(stem), stem)

    def _resolve_lib_identifier(self, keyword):
        """Map a keyword / identifier / pkg URL to an exact library graph identifier."""
        ident = self._lib_identifier_from_ref(keyword)
        key = ident.lower()
        if key in self._lib_url_cache:
            return self._lib_url_cache[key]
        index = self._lib_index()
        by_lower = {}
        for k in index:
            by_lower.setdefault(k.lower(), k)
        found = by_lower.get(key)
        if not found:
            cands = [k for k in by_lower if k.startswith(key)] or \
                    [k for k in by_lower if key in k]
            if cands:
                cands.sort(key=lambda k: (len(k), k))
                found = by_lower[cands[0]]
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
        return None

    def _get_library_resource(self, ref):
        """Return (resource, temp_package_or_None). Caller should pass the temp
        package to _release_temp_lib_package() after instancing."""
        pkg_mgr = self._pkg_mgr()
        loaded = list(pkg_mgr.getPackages())
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
        ident = self._resolve_lib_identifier(ref)
        if not ident:
            return None, None
        files = sorted(self._lib_index().get(ident, []),
                       key=lambda f: self._rank_lib_file(ident, f))
        # 2. identifier inside an already-loaded package. For built-in library
        #    graphs only accept the preferred file: a hidden Legacy copy may
        #    already be loaded as a dependency and has different port names.
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
                "Use get_library_nodes(filter_text=...) to search.".format(ref))
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

    def get_library_nodes(self, filter_text="", limit=200):
        """Search SD's built-in library (resources/packages) plus graphs in
        loaded packages. Returned URLs are portable 'pkg:///<identifier>'."""
        ft = (filter_text or "").lower()
        results, seen = [], set()
        index = self._lib_index()
        for ident in sorted(index, key=lambda k: (len(k), k)):
            if ft and ft not in ident.lower():
                continue
            files = sorted(index[ident], key=lambda f: self._rank_lib_file(ident, f))
            results.append({
                "identifier": ident,
                "url":        "pkg:///{}".format(ident),
                "package":    os.path.basename(files[0]),
                "source":     "library",
            })
            seen.add(ident.lower())
            if len(results) >= limit:
                break
        if len(results) < limit:
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
        }
