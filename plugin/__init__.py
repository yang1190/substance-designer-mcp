"""
Substance Designer MCP Plugin
=============================
Fork of matthieuhuguet/substance-designer-mcp (Matthieu Huguet / ZenRay),
maintained by yang1190 with Substance 3D Designer 16.0.x support.

ARCHITECTURE
  LLM -> stdio -> server/sd_mcp_bridge.py (FastMCP) -> TCP :9881 -> this plugin -> sd.api
  Protocol: [4-byte big-endian length][JSON], one fresh socket per command.
  Threading: every sd.api call runs on the Qt main thread (Signal/Slot dispatch).

MODULES
  common.py           shared imports, constants, pure helpers, SDError
  transport.py        Qt main-thread dispatcher + length-prefixed TCP server
  handler.py          CommandHandler: command table, composed from the mixins below
  core.py             SD helpers (lookup, values, parameters, usages, material model)
  library.py          Library node resolution (resources/packages, non-legacy first)
  scene_tools.py      scene / package / graph tools, diagnostic
  node_tools.py       node / connection / parameter tools, arrange_nodes
  builders.py         batch graph builder, recipe builders
  function_graphs.py  function graphs on parameters, SDF, Shape splatter v2 (SD 16)
  render.py           render_outputs / export_outputs / validate_library
  recipes.py          79 material recipes + 8 heightmap styles (pure data)
  sd_documentation.py embedded knowledge base (list_documentation)

RULES (SD API facts)
  - One SD call at a time; the bridge serialises commands.
  - SD API errors (APIException) derive from BaseException: catch SDError.
  - SD 15: newNode(unknown definition) and SDUsage.sNew() hang SD; the plugin
    validates definitions and only sets usages on SD 16+.
  - Library node outputs are named per graph (never "unique_filter_output").
  - directionalwarp warp map input = "inputintensity".

VERSION HISTORY: see CHANGELOG.md
"""

import traceback
from .common import (
    DEFAULT_PORTS,
    PLUGIN_VERSION,
    SDError,
    _log,
)
from .transport import (
    SDMCPServer,
    _Invoker,
    _QT_BINDING_USED,
    _pyside_path,
)
from .handler import CommandHandler

__all__ = ["initializeSDPlugin", "uninitializeSDPlugin", "CommandHandler", "PLUGIN_VERSION"]
_server = None


def initializeSDPlugin():
    global _server
    _log("Initializing v{}".format(".".join(map(str, PLUGIN_VERSION))))

    if _pyside_path:
        _log("PySide path injected: {}".format(_pyside_path))
    else:
        _log("PySide6 importable natively (no path injection)")

    if _QT_BINDING_USED:
        _log("Qt binding: {}".format(_QT_BINDING_USED))
    else:
        _log("FATAL: No Qt binding. All MCP calls will fail.")

    inv = _Invoker.instance()
    if inv is not None:
        _log("Qt invoker ready (Signal/Slot dispatch)")
    else:
        _log("FATAL: Qt invoker creation failed")

    try:
        _server = SDMCPServer(ports=DEFAULT_PORTS)
        _server.start()
        _log("Plugin v{} ready! Port: {}".format(
            ".".join(map(str, PLUGIN_VERSION)), DEFAULT_PORTS))
    except SDError as e:
        _log("FATAL: Failed to start server: {}".format(e))
        traceback.print_exc()

def uninitializeSDPlugin():
    global _server
    _log("Uninitializing")
    if _server:
        _server.stop()
        _server = None
