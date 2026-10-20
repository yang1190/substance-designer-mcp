"""
Transport layer: Qt main-thread dispatch (Signal/Slot) and the
length-prefixed TCP server the MCP bridge talks to.
"""

import importlib as _importlib
import json
import os
import queue
import select
import socket
import struct
import sys
import threading
import time
import traceback
from .common import (
    ACCEPT_BACKLOG,
    CLIENT_TIMEOUT,
    COMMAND_TIMEOUT,
    DEFAULT_PORTS,
    HEADER_SIZE,
    MAX_MSG_SIZE,
    PLUGIN_VERSION,
    SDError,
    _log,
)

def _inject_sd_pyside_path():
    candidates = []
    try:
        import psutil
        for proc in psutil.process_iter(['name', 'exe']):
            name = (proc.info.get('name') or '').lower()
            if 'substance' in name and 'designer' in name:
                exe = proc.info.get('exe') or ''
                if exe:
                    candidates.append(os.path.dirname(exe))
    except SDError:
        pass

    try:
        exe_dir = os.path.dirname(sys.executable)
        for _ in range(4):
            site_pkg = os.path.join(exe_dir, 'Lib', 'site-packages')
            if os.path.isdir(os.path.join(site_pkg, 'PySide6')):
                candidates.append(exe_dir)
                break
            exe_dir = os.path.dirname(exe_dir)
    except SDError:
        pass

    try:
        for drive in ('C:', 'D:', 'E:', 'F:'):
            for base in (
                drive + '\\Program Files\\Adobe',
                drive + '\\Program Files (x86)\\Adobe',
                drive + '\\Create\\Build\\DCC\\SubstanceDesigner',
            ):
                if not os.path.isdir(base):
                    continue
                for item in os.listdir(base):
                    if 'substance' in item.lower() and 'designer' in item.lower():
                        candidates.append(os.path.join(base, item))
    except SDError:
        pass

    for sd_root in candidates:
        site_pkg = os.path.join(sd_root, 'plugins', 'pythonsdk', 'Lib', 'site-packages')
        if os.path.isdir(os.path.join(site_pkg, 'PySide6')):
            if site_pkg not in sys.path:
                sys.path.insert(0, site_pkg)
            return site_pkg
    return None

def _pyside6_importable():
    try:
        _importlib.import_module("PySide6.QtCore")  # SD 16 ships it on sys.path
        return True
    except SDError:
        return False

_pyside_path = None if _pyside6_importable() else _inject_sd_pyside_path()

_QTimer = None

_QT_BINDING_USED = None

for _qt_binding in ("PySide6.QtCore", "PySide2.QtCore"):
    try:
        _qtcore_mod = _importlib.import_module(_qt_binding)
        _QTimer = _qtcore_mod.QTimer
        _QT_BINDING_USED = _qt_binding
        break
    except SDError:
        pass

class _Invoker:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls._build()
        return cls._instance

    @staticmethod
    def _build():
        if not _QT_BINDING_USED:
            return None
        try:
            qtcore = _importlib.import_module(_QT_BINDING_USED)

            class Invoker(qtcore.QObject):
                invoke_signal = qtcore.Signal()

                def __init__(self):
                    super().__init__()
                    self._queue = queue.Queue()
                    self.invoke_signal.connect(self._execute, qtcore.Qt.QueuedConnection)

                def schedule(self, fn):
                    self._queue.put(fn)
                    self.invoke_signal.emit()

                def _execute(self):
                    try:
                        fn = self._queue.get_nowait()
                        fn()
                    except queue.Empty:
                        pass
                    except SDError as e:
                        _log("Invoker._execute error: {}".format(e))

            return Invoker()
        except SDError as e:
            _log("Warning: _Invoker build failed: {}".format(e))
            return None

class MainThreadDispatcher:
    def dispatch(self, fn, *args, **kwargs):
        if threading.current_thread() is threading.main_thread():
            try:
                return fn(*args, **kwargs), None
            except SDError as e:
                return None, (e if isinstance(e, Exception) else
                              RuntimeError("SD API error ({}): {}".format(type(e).__name__, e)))

        invoker = _Invoker.instance()
        if invoker is None:
            hint = (" injected: {}".format(_pyside_path)
                    if _pyside_path else " (pythonsdk not found)")
            return None, RuntimeError(
                "Qt invoker unavailable — cannot dispatch to main thread." + hint)

        result_holder = [None, None]
        done = threading.Event()

        def _call():
            try:
                result_holder[0] = fn(*args, **kwargs)
            except SDError as e:
                result_holder[1] = e if isinstance(e, Exception) else \
                    RuntimeError("SD API error ({}): {}".format(type(e).__name__, e))
            finally:
                done.set()

        invoker.schedule(_call)

        if not done.wait(timeout=COMMAND_TIMEOUT):
            return None, TimeoutError(
                "Main thread dispatch timed out after {}s".format(COMMAND_TIMEOUT))

        return result_holder[0], result_holder[1]

_dispatcher = MainThreadDispatcher()

def _run_on_main(fn, *args, **kwargs):
    result, exc = _dispatcher.dispatch(fn, *args, **kwargs)
    if exc is not None:
        raise exc
    return result

def _recv_exact(sock, n, timeout=COMMAND_TIMEOUT):
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            raise socket.timeout("Timed out reading {} bytes (got {})".format(n, len(buf)))
        if not chunk:
            return None
        buf += chunk
    return buf

def _recv_framed(sock, timeout=COMMAND_TIMEOUT):
    header = _recv_exact(sock, HEADER_SIZE, timeout)
    if not header:
        return None
    msg_len = struct.unpack(">I", header)[0]
    if msg_len == 0:
        return None
    if msg_len > MAX_MSG_SIZE:
        raise ValueError("Message too large: {} bytes".format(msg_len))
    payload = _recv_exact(sock, msg_len, timeout)
    if not payload:
        return None
    return payload

def _send_framed(sock, data):
    sock.sendall(struct.pack(">I", len(data)) + data)

class SDMCPServer:
    def __init__(self, ports=None):
        self.host = 'localhost'
        self.ports = ports or DEFAULT_PORTS
        self.running = False
        self.listeners = {}
        self._thread = None
        from .handler import CommandHandler  # lazy: handler imports the mixins
        self._handler = CommandHandler()

    def start(self):
        self.running = True
        for port in self.ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((self.host, port))
                sock.listen(ACCEPT_BACKLOG)
                sock.setblocking(False)
                self.listeners[port] = sock
                _log("Listening on {}:{}".format(self.host, port))
            except SDError as e:
                _log("Failed to bind port {}: {}".format(port, e))

        if not self.listeners:
            _log("ERROR: No ports could be opened!")
            return

        self._thread = threading.Thread(
            target=self._serve_loop, daemon=True, name="SD-MCP-Serve")
        self._thread.start()
        _log("v{} running on ports: {}".format(
            ".".join(map(str, PLUGIN_VERSION)), list(self.listeners.keys())))

    def stop(self):
        self.running = False
        for sock in self.listeners.values():
            try:
                sock.close()
            except SDError:
                pass
        self.listeners.clear()
        _log("Server stopped")

    def _serve_loop(self):
        while self.running:
            readable = list(self.listeners.values())
            if not readable:
                time.sleep(0.1)
                continue
            try:
                ready, _, _ = select.select(readable, [], [], 0.1)
            except (OSError, ValueError):
                if not self.running:
                    break
                time.sleep(0.1)
                continue

            for listener in ready:
                port = next((p for p, s in self.listeners.items() if s is listener), None)
                if port is None:
                    continue
                try:
                    client, addr = listener.accept()
                except (BlockingIOError, OSError):
                    continue
                try:
                    self._handle_client(client, addr, port)
                except SDError as e:
                    _log("Unexpected error: {}".format(e))

    def _handle_client(self, client, addr, port):
        try:
            client.setblocking(True)
            client.settimeout(CLIENT_TIMEOUT)
            _log("Client on port {}: {}".format(port, addr))

            payload = _recv_framed(client, timeout=CLIENT_TIMEOUT)
            if payload is None:
                return

            try:
                command = json.loads(payload.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                _send_framed(client, json.dumps(
                    {"status": "error", "message": "Invalid JSON: {}".format(e)}
                ).encode("utf-8"))
                return

            response = self._execute_safe(command)
            _send_framed(client, json.dumps(response, default=_json_safe).encode("utf-8"))

        except socket.timeout:
            _log("Timeout from client on port {}".format(port))
        except ConnectionResetError:
            pass
        except SDError as e:
            _log("Error handling client on port {}: {}".format(port, e))
        finally:
            try:
                client.close()
            except SDError:
                pass

    def _execute_safe(self, command):
        try:
            cmd_type = command.get("type")
            params   = command.get("params", {})
            _log("Executing: {}".format(cmd_type))
            result = _run_on_main(self._handler.dispatch, cmd_type, params)
            _log("Done: {}".format(cmd_type))
            return {"status": "success", "result": result if result is not None else {}}
        except SDError as e:
            _log("Error in {}: {}".format(command.get("type", "?"), e))
            try:
                traceback.print_exc()
            except SDError:
                pass
            return {"status": "error", "message": str(e)}

def _json_safe(obj):
    if isinstance(obj, float):
        if obj != obj:
            return None
        if obj == float('inf'):
            return 1e308
        if obj == float('-inf'):
            return -1e308
    return str(obj)
