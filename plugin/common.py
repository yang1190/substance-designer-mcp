"""
Shared imports, constants and pure helpers for the SD MCP plugin
(no SD state, no Qt). Imported by every other module.
"""

import re

import sd
from sd.api.sdproperty import SDPropertyCategory

try:
    # SD API errors derive from BaseException, NOT Exception: a bare
    # "except Exception" lets them escape, and the dispatcher used to turn them
    # into an empty "{}" result. Always catch SDError instead.
    from sd.api.apiexception import APIException
except Exception:  # pragma: no cover
    class APIException(Exception):
        pass

SDError = (Exception, APIException)

try:
    from sd.api.sdproperty import SDPropertyInheritanceMethod
except SDError:  # pragma: no cover
    SDPropertyInheritanceMethod = None
from sd.api.sdbasetypes import float2, float3, float4, ColorRGBA, int2, int3, int4
from sd.api.sdvaluefloat   import SDValueFloat
from sd.api.sdvalueint     import SDValueInt
from sd.api.sdvalueint2    import SDValueInt2
from sd.api.sdvalueint3    import SDValueInt3
from sd.api.sdvalueint4    import SDValueInt4
from sd.api.sdvaluebool    import SDValueBool
from sd.api.sdvaluestring  import SDValueString
from sd.api.sdvaluefloat2  import SDValueFloat2
from sd.api.sdvaluefloat3  import SDValueFloat3
from sd.api.sdvaluefloat4  import SDValueFloat4
from sd.api.sdvaluecolorrgba import SDValueColorRGBA
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph

try:  # output usages (baseColor, normal, ...) — confirmed working on SD 16.0.5
    from sd.api.sdusage      import SDUsage
    from sd.api.sdvalueusage import SDValueUsage
    from sd.api.sdvaluearray import SDValueArray
    from sd.api.sdtypeusage  import SDTypeUsage
except SDError:  # pragma: no cover
    SDUsage = SDValueUsage = SDValueArray = SDTypeUsage = None

DEFAULT_PORTS     = [9881]

PLUGIN_VERSION    = (3, 9, 0)

HEADER_SIZE       = 4

COMMAND_TIMEOUT   = 120

CLIENT_TIMEOUT    = 130

ACCEPT_BACKLOG    = 5

MAX_MSG_SIZE      = 100 * 1024 * 1024   # 100 MB

# System properties not valid as connection targets
_SYSTEM_PARAMS = frozenset({
    "$outputsize", "$format", "$pixelsize", "$pixelratio",
    "$tiling", "$randomseed", "$time"
})

# Source: Adobe SD docs + empirical testing. Prevents wrong-port crashes.
ATOMIC_PORTS = {
    "sbs::compositing::blend": {
        "inputs":  ["source", "destination", "opacity"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::levels": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::curve": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::hsl": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::blur": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::sharpen": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::warp": {
        "inputs":  ["input1", "inputgradient"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::directionalwarp": {
        "inputs":  ["input1", "inputintensity"],   # NOT inputgradient !
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::normal": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::transformation": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::distance": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::grayscaleconversion": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::shuffle": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::emboss": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::passthrough": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::uniform": {
        "inputs":  [],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::output": {
        "inputs":  ["inputNodeOutput"],
        "outputs": [],
    },
    "sbs::compositing::input_color": {
        "inputs":  [],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::input_grayscale": {
        "inputs":  [],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::gradient": {
        "inputs":  ["input1", "gradient"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::pixelprocessor": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
    "sbs::compositing::fxmaps": {
        "inputs":  ["input1"],
        "outputs": ["unique_filter_output"],
    },
}

def _log(msg):
    print("[SD-MCP] {}".format(msg))

# CRITICAL: bare int scalars → "float" because almost all SD node params are float.
# Only explicit {"value": x, "type": "int"} should produce SDValueInt.
# Sending SDValueInt to a float param CRASHES SD 15 silently.
def _infer_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "float"   # int scalar → float (avoids SDValueInt crash on float params)
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        n = len(value)
        # CRITICAL: SD 15 silently crashes on SDValueInt2/3/4 applied to float params.
        # Always use float vectors — int vector params MUST use explicit {"value":..., "type":"int2"}
        if n == 2:
            return "float2"
        if n == 3:
            return "float3"
        if n == 4:
            return "float4"
    return "float"

def _coerce_type(inferred_type, value, sd_type_id):
    """Coerce the inferred Python type to match the actual SD property type.
    Prevents SD 15 silent crashes caused by wrong SDValue types.
    sd_type_id: the getId() string of the property's SDType.
    """
    if not sd_type_id:
        return inferred_type
    tid = sd_type_id.lower()

    # Exact primitive types
    if tid == "int":        return "int"
    if tid == "float":      return "float"
    if tid == "bool":       return "bool"
    if tid == "string":     return "string"
    if tid == "float2":     return "float2"
    if tid == "float3":     return "float3"
    if tid == "float4":     return "float4"
    if tid == "int2":       return "int2"
    if tid == "int3":       return "int3"
    if tid == "int4":       return "int4"
    if tid == "colorrgba":  return "color"
    if tid == "colorrgb":   return "float3"

    # SD enum types (sbs::compositing::blendingmode, sbs::compositing::format, etc.)
    # Enums are integer-based — any non-primitive sd type that accepts an int value
    # SD enum types accept SDValueInt. Coerce float → int for these.
    if tid.startswith("sbs::") or "::" in tid:
        if inferred_type in ("float",):
            # Only coerce scalar floats that represent enum/int values
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return "int"
        return inferred_type

    # Fallback: check for int/float keywords in type name
    if "int" in tid and "float" not in tid:
        if inferred_type == "float":
            return "int"
        if inferred_type == "float4" and isinstance(value, (list, tuple)):
            return "int4"
        if inferred_type == "float2" and isinstance(value, (list, tuple)):
            return "int2"

    return inferred_type

def _sd_version_tuple():
    """(major, minor, patch) of the running Substance Designer, (0,0,0) if unknown."""
    try:
        v = sd.getContext().getSDApplication().getVersion()
        parts = [int(x) for x in re.findall(r"\d+", str(v))[:3]]
        return tuple(parts + [0] * (3 - len(parts)))
    except SDError:
        return (0, 0, 0)

def _sd_major():
    return _sd_version_tuple()[0]

# Standard PBR output usages: name -> (components, color space)
# Legacy PBR output usages (Adobe Standard Material / metallic-roughness):
#   key -> (identifier, usage name). SD's own templates use components RGBA and
#   an empty color space for every usage, so we do the same.
OUTPUT_USAGES = {
    "basecolor":        ("basecolor",        "baseColor"),
    "diffuse":          ("diffuse",          "diffuse"),
    "normal":           ("normal",           "normal"),
    "roughness":        ("roughness",        "roughness"),
    "metallic":         ("metallic",         "metallic"),
    "height":           ("height",           "height"),
    "ambientocclusion": ("ambientocclusion", "ambientOcclusion"),
    "ao":               ("ambientocclusion", "ambientOcclusion"),
    "emissive":         ("emissive",         "emissive"),
    "opacity":          ("opacity",          "opacity"),
    "specular":         ("specular",         "specular"),
    "specularlevel":    ("specularlevel",    "specularLevel"),
    "glossiness":       ("glossiness",       "glossiness"),
    "anisotropylevel":  ("anisotropylevel",  "anisotropyLevel"),
    "anisotropyangle":  ("anisotropyangle",  "anisotropyAngle"),
    "ior":              ("ior",              "IOR"),
}

# OpenPBR outputs exactly as in SD 16's 01_01_openpbr_metalness_roughness.sbs
# ("complete" graph): identifier -> [usages] (OpenPBR name first, legacy alias second)
OPENPBR_OUTPUTS = [
    ("base_weight",                         ["baseWeight"]),
    ("base_color",                          ["baseColor"]),
    ("base_metalness",                      ["metalness", "metallic"]),
    ("base_diffuse_roughness",              ["baseDiffuseRoughness"]),
    ("specular_weight",                     ["specularWeight"]),
    ("specular_color",                      ["specularColor", "specularEdgeColor"]),
    ("specular_roughness",                  ["specularRoughness", "roughness"]),
    ("specular_roughness_anisotropy",       ["specularRoughnessAnisotropy", "anisotropyLevel"]),
    ("specular_ior",                        ["specularIOR", "IOR"]),
    ("transmission_weight",                 ["transmissionWeight"]),
    ("transmission_color",                  ["transmissionColor", "absorptionColor"]),
    ("transmission_depth",                  ["transmissionDepth", "absorptionDistance"]),
    ("transmission_scatter",                ["transmissionScatter"]),
    ("transmission_scatter_anisotropy",     ["transmissionScatterAnisotropy"]),
    ("transmission_dispersion_scale",       ["transmissionDispersionScale"]),
    ("transmission_dispersion_abbe_number", ["transmissionDispersionAbbeNumber"]),
    ("subsurface_weight",                   ["subsurfaceWeight", "translucency"]),
    ("subsurface_color",                    ["subsurfaceColor", "scatteringColor"]),
    ("subsurface_radius",                   ["subsurfaceRadius", "scatteringDistance"]),
    ("subsurface_radius_scale",             ["subsurfaceRadiusScale", "scatteringDistanceScale"]),
    ("subsurface_scatter_anisotropy",       ["subsurfaceScatterAnisotropy"]),
    ("coat_weight",                         ["coatWeight", "coatOpacity"]),
    ("coat_color",                          ["coatColor"]),
    ("coat_roughness",                      ["coatRoughness"]),
    ("coat_roughness_anisotropy",           ["coatRoughnessAnisotropy"]),
    ("coat_ior",                            ["coatIOR"]),
    ("coat_darkening",                      ["coatDarkening"]),
    ("fuzz_weight",                         ["fuzzWeight", "sheenOpacity"]),
    ("fuzz_color",                          ["fuzzColor", "sheenColor"]),
    ("fuzz_roughness",                      ["fuzzRoughness", "sheenRoughness"]),
    ("emission_luminance",                  ["emissionLuminance"]),
    ("emission_color",                      ["emissionColor", "emissive"]),
    ("thin_film_weight",                    ["thinFilmWeight"]),
    ("thin_film_thickness",                 ["thinFilmThickness"]),
    ("thin_film_ior",                       ["thinFilmIOR"]),
    ("opacity",                             ["opacity"]),
    ("thin_walled",                         ["thinWalled"]),
    ("height",                              ["height"]),
    ("normal",                              ["normal"]),
    ("tangent",                             ["tangent"]),
    ("coat_normal",                         ["coatNormal"]),
    ("coat_tangent",                        ["coatTangent"]),
    ("ambient_occlusion",                   ["ambientOcclusion"]),
]

def _usage_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

# any usage name / identifier (OpenPBR or legacy) -> OpenPBR identifier
OPENPBR_ALIAS = {}

for _ident, _usages in OPENPBR_OUTPUTS:
    OPENPBR_ALIAS[_usage_key(_ident)] = _ident
    for _u in _usages:
        OPENPBR_ALIAS.setdefault(_usage_key(_u), _ident)

OPENPBR_ALIAS.update({"ao": "ambient_occlusion", "diffuse": "base_color",
                      "albedo": "base_color", "emissive": "emission_color"})

OPENPBR_USAGES = dict(OPENPBR_OUTPUTS)

DEFAULT_MATERIAL_MODEL_SD16 = "openpbr_v1_1"

def _sanitize_identifier(name):
    if not name:
        return "MCP_Graph"
    sanitized = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if sanitized and not sanitized[0].isalpha():
        sanitized = "G_" + sanitized
    return sanitized or "MCP_Graph"


# Everything above is shared with the other plugin modules.
__all__ = [
    'SDPropertyCategory',
    'APIException',
    'SDError',
    'SDPropertyInheritanceMethod',
    'float2',
    'float3',
    'float4',
    'ColorRGBA',
    'int2',
    'int3',
    'int4',
    'SDValueFloat',
    'SDValueInt',
    'SDValueInt2',
    'SDValueInt3',
    'SDValueInt4',
    'SDValueBool',
    'SDValueString',
    'SDValueFloat2',
    'SDValueFloat3',
    'SDValueFloat4',
    'SDValueColorRGBA',
    'SDSBSCompGraph',
    'SDUsage',
    'SDValueUsage',
    'SDValueArray',
    'SDTypeUsage',
    'DEFAULT_PORTS',
    'PLUGIN_VERSION',
    'HEADER_SIZE',
    'COMMAND_TIMEOUT',
    'CLIENT_TIMEOUT',
    'ACCEPT_BACKLOG',
    'MAX_MSG_SIZE',
    '_SYSTEM_PARAMS',
    'ATOMIC_PORTS',
    '_log',
    '_infer_type',
    '_coerce_type',
    '_sd_version_tuple',
    '_sd_major',
    'OUTPUT_USAGES',
    'OPENPBR_OUTPUTS',
    '_usage_key',
    'OPENPBR_ALIAS',
    'OPENPBR_USAGES',
    'DEFAULT_MATERIAL_MODEL_SD16',
    '_sanitize_identifier',
]
