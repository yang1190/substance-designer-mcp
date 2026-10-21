"""
Library search paths: where the plugin looks for .sbs packages.

Pure Python (no `sd` import) so it can be unit-tested offline.

Sources, merged in this order (duplicates removed, first one wins):

  builtin        <SD>/resources/packages (top level only, as before)
  sd_project     the Library "watched paths" SD itself uses, read from the
                 project files in SD's settings folder:
                   %LOCALAPPDATA%/Adobe/Adobe Substance 3D Designer/<major.minor>/
                     default_project.sbsprj   (sbs://, sd-3dview-maps://)
                     user_project.sbsprj      (Preferences > Projects > Library)
                     + any project listed in default_configuration.sbscfg
                 so a folder added to SD's Library is picked up automatically
  plugin_config  folders added with the add_library_path tool, stored in
                   <settings base>/sd_mcp/library_paths.json
                 (outside the plugin folder: survives plugin updates and SD
                 version upgrades)
  env            SD_MCP_LIBRARY_PATHS (os.pathsep-separated; append '*' to a
                 folder to scan it recursively, e.g. D:/libs/rocks*)
"""

import fnmatch
import json
import os
import re
import xml.etree.ElementTree as ET

try:
    from urllib.parse import unquote
except ImportError:  # pragma: no cover
    from urllib import unquote

ENV_VAR = "SD_MCP_LIBRARY_PATHS"
ENV_CONFIG_DIR = "SD_MCP_CONFIG_DIR"
APP_FOLDER = "Adobe Substance 3D Designer"
CONFIG_NAME = "library_paths.json"
MAX_DEPTH = 8
_SKIP_DIRS = {".git", ".svn", "__pycache__", ".autosave", "autosave"}

__all__ = [
    "ENV_VAR", "settings_base_dirs", "sd_settings_dir", "config_file_path",
    "file_url_to_path", "parse_project_file", "configured_project_files",
    "sd_project_watched_paths", "load_config", "save_config", "env_paths",
    "collect_library_roots", "iter_sbs_files", "norm_path", "scan_sbs_bytes",
    "split_ref",
]


# ── paths ──────────────────────────────────────────────────────────────────
def norm_path(p):
    """Absolute, forward slashes, no trailing slash (case kept)."""
    if not p:
        return ""
    p = os.path.expanduser(os.path.expandvars(p))
    if not (os.name != "nt" and re.match(r"^[A-Za-z]:[/\\]", p)):
        p = os.path.abspath(p)  # (a Windows drive path stays as is elsewhere)
    p = p.replace("\\", "/")
    return p.rstrip("/") if len(p) > 3 else p


def _key(p):
    return norm_path(p).lower()


def settings_base_dirs(environ=None, home=None):
    """Candidate '<...>/Adobe/Adobe Substance 3D Designer' folders, best first."""
    env = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    out = []
    if env.get("LOCALAPPDATA"):
        out.append(os.path.join(env["LOCALAPPDATA"], "Adobe", APP_FOLDER))
    out.append(os.path.join(home, "Library", "Application Support", "Adobe", APP_FOLDER))
    out.append(os.path.join(home, ".local", "share", "Adobe", APP_FOLDER))
    out.append(os.path.join(home, ".config", "Adobe", APP_FOLDER))
    return out


def _version_key(name):
    try:
        return tuple(int(x) for x in name.split("."))
    except ValueError:
        return None


def sd_settings_dir(version=None, bases=None):
    """SD's per-version settings folder ('.../16.0'). With a version string
    ('16.0.5') the matching major.minor folder is used, otherwise the newest."""
    want = None
    if version:
        parts = str(version).split(".")
        want = ".".join(parts[:2])
    for base in (bases if bases is not None else settings_base_dirs()):
        if not os.path.isdir(base):
            continue
        if want and os.path.isdir(os.path.join(base, want)):
            return norm_path(os.path.join(base, want))
        vers = [d for d in os.listdir(base)
                if _version_key(d) and os.path.isdir(os.path.join(base, d))]
        if vers:
            return norm_path(os.path.join(base, max(vers, key=_version_key)))
    return None


def config_file_path(environ=None, bases=None):
    """Persistent plugin config: <settings base>/sd_mcp/library_paths.json."""
    env = os.environ if environ is None else environ
    if env.get(ENV_CONFIG_DIR):
        return norm_path(os.path.join(env[ENV_CONFIG_DIR], CONFIG_NAME))
    bases = bases if bases is not None else settings_base_dirs(env)
    for base in bases:
        if os.path.isdir(base):
            return norm_path(os.path.join(base, "sd_mcp", CONFIG_NAME))
    return norm_path(os.path.join(os.path.expanduser("~"), ".sd_mcp", CONFIG_NAME))


def file_url_to_path(url, aliases=None, project_dir=None):
    """file:///C:/x -> C:/x ; sbs://sub -> <alias sbs>/sub ;
    $(PROJECT_DIR)://x -> <project_dir>/x ; plain paths pass through.
    Returns None for unresolvable URLs."""
    if not url:
        return None
    url = url.strip()
    if url.lower().startswith("file:"):
        rest = url[5:]
        while rest.startswith("/"):
            rest = rest[1:]
        rest = unquote(rest)
        # Windows drive ("C:/x") vs POSIX ("home/x" -> "/home/x")
        if re.match(r"^[A-Za-z]:", rest):
            return norm_path(rest)
        return norm_path("/" + rest)
    m = re.match(r"^(\$\(PROJECT_DIR\)|[A-Za-z0-9_.\-]+)://(.*)$", url)
    if m:
        name, rest = m.group(1), unquote(m.group(2))
        if name == "$(PROJECT_DIR)":
            base = project_dir
        else:
            base = (aliases or {}).get(name)
        if not base:
            return None
        return norm_path(os.path.join(base, rest)) if rest else norm_path(base)
    if re.match(r"^[A-Za-z]+:(?![/\\])", url) and not re.match(r"^[A-Za-z]:", url):
        return None  # 'environment:X' and similar
    return norm_path(url)


# ── SD project files ───────────────────────────────────────────────────────
def _bool(text, default):
    if text is None:
        return default
    t = text.strip().lower()
    if t in ("true", "1", "yes"):
        return True
    if t in ("false", "0", "no"):
        return False
    return default


def _items(parent):
    """SD stores lists as <size>N</size><_N prefix="_">...</_N>..."""
    if parent is None:
        return []
    items = [c for c in parent if re.match(r"^_\d+$", c.tag)]
    items.sort(key=lambda c: int(c.tag[1:]))
    return items


def parse_project_file(path, aliases=None):
    """Parse an SD .sbsprj file.

    Returns {"path", "label", "aliases": {name: dir},
             "watched": [{"url", "path", "recursive", "enabled",
                          "exclude_pattern", "exclude_filter"}]}.
    Aliases defined in the file are merged with `aliases` (file wins) and used
    to resolve watched URLs. Unreadable files give an empty result + "error".
    """
    res = {"path": norm_path(path), "label": "", "aliases": {}, "watched": []}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        res["error"] = str(e)
        return res
    project_dir = os.path.dirname(path)
    label = root.find("projectinfo/label")
    res["label"] = (label.text or "").strip() if label is not None else ""
    al = dict(aliases or {})
    for it in _items(root.find("preferences/resources/urlaliases")):
        name, p = it.findtext("name"), it.findtext("path")
        resolved = file_url_to_path(p, al, project_dir) if p else None
        if name and resolved:
            al[name.strip()] = resolved
            res["aliases"][name.strip()] = resolved
    for it in _items(root.find("preferences/library/watchedpaths")):
        url = (it.findtext("url") or "").strip()
        if not url:
            continue
        res["watched"].append({
            "url":             url,
            "path":            file_url_to_path(url, al, project_dir),
            "recursive":       _bool(it.findtext("isrecursive"), False),
            "enabled":         _bool(it.findtext("isenabled"), True),
            "exclude_pattern": (it.findtext("excludepattern") or "").strip(),
            "exclude_filter":  (it.findtext("excludefilter") or "").strip(),
        })
    return res


def configured_project_files(settings_dir):
    """Extra project files listed in default_configuration.sbscfg."""
    cfg = os.path.join(settings_dir, "default_configuration.sbscfg")
    out = []
    try:
        root = ET.parse(cfg).getroot()
    except (OSError, ET.ParseError):
        return out
    for it in _items(root.find("projects/projectfiles")):
        texts = [it.text or ""] + [c.text or "" for c in it.iter()]
        for t in texts:
            t = t.strip()
            if t.lower().endswith(".sbsprj"):
                p = file_url_to_path(t, None, settings_dir)
                if p and _key(p) not in {_key(x) for x in out}:
                    out.append(p)
                break
    return out


def sd_project_watched_paths(settings_dir):
    """Library watched paths of every SD project (default, user, configured).

    Aliases from default_project.sbsprj (e.g. sbs:// -> resources/packages)
    are visible to the later projects, like in SD."""
    if not settings_dir or not os.path.isdir(settings_dir):
        return []
    files = [os.path.join(settings_dir, "default_project.sbsprj"),
             os.path.join(settings_dir, "user_project.sbsprj")]
    files += configured_project_files(settings_dir)
    aliases, out = {}, []
    for f in files:
        if not os.path.isfile(f):
            continue
        info = parse_project_file(f, aliases)
        aliases.update(info["aliases"])
        for w in info["watched"]:
            w = dict(w)
            w["project"] = os.path.basename(f)
            w["project_label"] = info["label"]
            out.append(w)
    return out


# ── plugin config / env ────────────────────────────────────────────────────
def _default_config():
    return {"version": 1, "use_sd_project_paths": True, "paths": [], "ignored": []}


def load_config(path):
    cfg = _default_config()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in cfg})
    except (OSError, ValueError):
        pass
    paths = []
    for p in cfg.get("paths") or []:
        if isinstance(p, str):
            p = {"path": p}
        if isinstance(p, dict) and p.get("path"):
            paths.append({"path": norm_path(p["path"]),
                          "recursive": bool(p.get("recursive", True)),
                          "enabled": bool(p.get("enabled", True)),
                          "label": p.get("label", "")})
    cfg["paths"] = paths
    cfg["ignored"] = [norm_path(p) for p in (cfg.get("ignored") or []) if isinstance(p, str)]
    return cfg


def save_config(path, cfg):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def env_paths(environ=None):
    env = os.environ if environ is None else environ
    out = []
    for part in (env.get(ENV_VAR) or "").split(os.pathsep):
        part = part.strip().strip('"')
        if not part:
            continue
        rec = part.endswith("*")
        out.append({"path": norm_path(part.rstrip("*").rstrip("/\\")), "recursive": rec})
    return out


def collect_library_roots(builtin_dirs, settings_dir, config, environ=None):
    """Merge every source into a list of root dicts:
    {"path", "recursive", "enabled", "source", "exists", "exclude", ...}.
    The first occurrence of a folder wins (builtin > sd_project > plugin_config
    > env), except that a later source may turn on recursion."""
    roots, by_key = [], {}
    ignored = {_key(p) for p in (config or {}).get("ignored", [])}
    builtin_keys = {_key(b) for b in builtin_dirs}

    def add(path, recursive, source, enabled=True, **extra):
        if not path:
            return
        k = _key(path)
        if k in by_key:
            r = by_key[k]
            if source != "builtin" and r["source"] != "builtin" and recursive:
                r["recursive"] = True
            r.setdefault("also_in", []).append(source)
            return
        r = {"path": norm_path(path), "recursive": bool(recursive),
             "enabled": bool(enabled) and k not in ignored, "source": source,
             "exists": os.path.isdir(path), "exclude": []}
        if k in ignored:
            r["ignored"] = True
        r.update(extra)
        by_key[k] = r
        roots.append(r)

    for b in builtin_dirs:
        add(b, False, "builtin")
    if (config or {}).get("use_sd_project_paths", True):
        for w in sd_project_watched_paths(settings_dir):
            if not w.get("path"):
                continue
            k = _key(w["path"])
            # sbs:// (and its sub-folders) is SD's own library, already covered
            # by the builtin root (top level, like before); other folders of
            # SD's install (sd-3dview-maps://...) hold no graphs: skip both.
            if any(k == b or k.startswith(b + "/") or k.startswith(os.path.dirname(b) + "/")
                   for b in builtin_keys):
                continue
            excl = [x for x in re.split(r"[;,\s]+", w.get("exclude_pattern", "") +
                                        " " + w.get("exclude_filter", "")) if x]
            add(w["path"], w["recursive"], "sd_project", w["enabled"],
                project=w.get("project"), url=w.get("url"), exclude=excl)
    for p in (config or {}).get("paths", []):
        add(p["path"], p.get("recursive", True), "plugin_config", p.get("enabled", True),
            label=p.get("label", ""))
    for p in env_paths(environ):
        add(p["path"], p["recursive"], "env")
    return roots


def _excluded(name, rel, patterns):
    for pat in patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
        try:
            if re.search(pat, rel):
                return True
        except re.error:
            pass
    return False


def iter_sbs_files(root):
    """Yield absolute .sbs paths under a root dict (see collect_library_roots)."""
    base = root["path"]
    if not root.get("enabled", True) or not os.path.isdir(base):
        return
    patterns = root.get("exclude") or []
    stack = [(base, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for name in entries:
            fp = os.path.join(d, name)
            rel = os.path.relpath(fp, base).replace("\\", "/")
            if patterns and _excluded(name, rel, patterns):
                continue
            if os.path.isdir(fp):
                if root.get("recursive") and depth < MAX_DEPTH and \
                        name not in _SKIP_DIRS and not name.startswith("."):
                    stack.append((fp, depth + 1))
            elif name.lower().endswith(".sbs"):
                yield norm_path(fp)


# ── .sbs scanning ──────────────────────────────────────────────────────────
_ENTRY_RE = re.compile(rb'<(graph|function)>\s*<identifier v="([^"]*)"')
_HEADER_END_RE = re.compile(rb'<(paraminputs|graphOutputs|compNodes|nodes|paramValue|root|graph|function)\b')
_ATTR_RE = re.compile(rb'<(category|label|description|author|tags|hideInLibrary) v="([^"]*)"')


def _xml_unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&apos;", "'").replace("&amp;", "&"))


def scan_sbs_bytes(data):
    """Parse the content of a .sbs file (bytes) without an XML parser.

    Returns [{"kind": "graph"|"function", "identifier", "hidden", "label",
              "category", "description", "author", "tags"}] — only the
    graph-level <attributes> block is read (not those of its parameters)."""
    out = []
    matches = list(_ENTRY_RE.finditer(data))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(data)
        try:
            ident = m.group(2).decode("utf-8")
        except UnicodeDecodeError:
            continue
        entry = {"kind": m.group(1).decode(), "identifier": ident, "hidden": False}
        h = _HEADER_END_RE.search(data, m.end(), end)
        header_end = h.start() if h else end
        a0 = data.find(b"<attributes>", m.end(), header_end)
        if a0 >= 0:
            a1 = data.find(b"</attributes>", a0, end)
            for am in _ATTR_RE.finditer(data, a0, a1 if a1 >= 0 else header_end):
                k = am.group(1).decode()
                v = _xml_unescape(am.group(2).decode("utf-8", "replace"))
                if k == "hideInLibrary":
                    entry["hidden"] = v == "1"
                else:
                    entry[k] = v
        out.append(entry)
    return out


def split_ref(ref):
    """'pkg:///id?dependency=1' -> (None, 'id');
    'FloodFills.sbs#FloodFills' / 'D:/lib/x.sbs#id' -> ('FloodFills.sbs', 'FloodFills')."""
    ref = (ref or "").strip()
    pkg = None
    if "#" in ref and not ref.startswith("pkg:///"):
        pkg, ref = ref.rsplit("#", 1)
        pkg = pkg.strip() or None
    if ref.startswith("pkg:///"):
        ref = ref[len("pkg:///"):]
    return pkg, ref.split("?", 1)[0].strip("/")
