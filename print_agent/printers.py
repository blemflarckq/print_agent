"""Dispatches a rendered job payload to a physical printer.

Deliberately dumb: this module knows nothing about label sizes or content --
that's all baked into the payload by Odoo's bahmni.label.template before the
job ever reaches the agent. This module's only job is "get these bytes to
that printer."

Four printer types are supported:
  - raw_socket: TSC MB240 (TSPL2), network-connected, raw command bytes
    streamed directly over TCP (port 9100).
  - windows_raw: Epson TM-T88V receipt printer (ESC/POS), USB-attached to one
    specific PC. Installed as a normal Windows printer (any driver -- it's
    irrelevant, we bypass it), then sent raw ESC/POS bytes through the
    Windows print spooler's RAW datatype via pywin32. IMPORTANT: unlike the
    other printer types, a USB-attached printer is only reachable from the
    one PC it's physically plugged into -- see the routing note in poller.py
    and the design spec's Section 14 (Open Questions) for the implication
    this has on the Active/Standby model.
  - sumatra_pdf: HP LaserJet (or any Windows-installed printer) via SumatraPDF's
    silent command-line print mode. This is the Windows-native path -- no CUPS
    involved, no dialog shown. SumatraPDF is a free, portable single .exe; it
    is NOT a pip package, so it must be downloaded once per PC and pointed to
    via sumatra_path in config.json. https://www.sumatrapdfreader.org/download-free-pdf-viewer
  - cups: kept for completeness if this agent is ever run on Linux/macOS
    instead of Windows -- not usable on a plain Windows install.
"""
import base64
import os
import socket
import subprocess
import tempfile
import logging

log = logging.getLogger("print_agent.printers")


class PrintError(Exception):
    pass


def dispatch(printer_config, command_language, payload):
    ptype = printer_config.get("type")
    if ptype == "raw_socket":
        _send_raw_socket(printer_config, payload)
    elif ptype == "windows_raw":
        _send_windows_raw(printer_config, command_language, payload)
    elif ptype == "sumatra_pdf":
        _send_sumatra_pdf(printer_config, payload)
    elif ptype == "cups":
        _send_cups(printer_config, command_language, payload)
    else:
        raise PrintError(f"Unknown printer type: {ptype!r}")


def test_connection(printer_config, timeout=3):
    ptype = printer_config.get("type")
    if ptype == "raw_socket":
        try:
            with socket.create_connection((printer_config["host"], printer_config["port"]), timeout=timeout):
                return True, None
        except OSError as exc:
            return False, str(exc)
    elif ptype == "windows_raw":
        return _windows_printer_status(printer_config["printer_name"])
    elif ptype == "sumatra_pdf":
        return _sumatra_test_connection(printer_config)
    elif ptype == "cups":
        try:
            import cups
            conn = cups.Connection()
            printers = conn.getPrinters()
            name = printer_config["queue_name"]
            if name not in printers:
                return False, f"CUPS queue '{name}' not found on this machine"
            return True, None
        except Exception as exc:
            return False, str(exc)
    return False, f"Unknown printer type: {ptype!r}"


def _send_raw_socket(printer_config, payload):
    host, port = printer_config["host"], printer_config["port"]
    data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(data)
    except OSError as exc:
        raise PrintError(f"Cannot reach {host}:{port} -- {exc}") from exc


def _write_pdf_tempfile(payload):
    pdf_bytes = base64.b64decode(payload)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(pdf_bytes)
    return path


def _send_sumatra_pdf(printer_config, payload):
    """Silent, dialog-free PDF printing on Windows via SumatraPDF's
    command-line switches -- no CUPS, no Windows print dialog, no app window
    ever becomes visible. -exit-when-done makes Sumatra quit as soon as the
    print job is handed to the spooler rather than staying resident."""
    sumatra = printer_config.get("sumatra_path", "SumatraPDF.exe")
    printer_name = printer_config["printer_name"]
    path = _write_pdf_tempfile(payload)
    try:
        result = subprocess.run(
            [sumatra, "-print-to", printer_name, "-silent", "-exit-when-done", path],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="ignore") if result.stderr else ""
            raise PrintError(
                f"SumatraPDF exited with code {result.returncode} printing to "
                f"'{printer_name}': {stderr or 'no error output'}"
            )
    except FileNotFoundError as exc:
        raise PrintError(
            f"SumatraPDF executable not found at '{sumatra}' -- download it from "
            f"sumatrapdfreader.org and set sumatra_path in config.json"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PrintError(f"SumatraPDF did not finish printing within 30s") from exc
    finally:
        os.unlink(path)


def _sumatra_test_connection(printer_config):
    """Cheap reachability check for the status window. Two layers: does the
    Sumatra executable exist, and (if pywin32 is installed) is the named
    Windows printer actually present and not in an error/offline state.
    pywin32 is optional here -- without it we can only confirm Sumatra
    itself is where config.json says it is."""
    sumatra = printer_config.get("sumatra_path", "SumatraPDF.exe")
    if not os.path.isfile(sumatra) and not _on_path(sumatra):
        return False, f"SumatraPDF not found at '{sumatra}' (and not on PATH)"

    try:
        import win32print  # noqa: F401 -- import-checked here only
    except ImportError:
        return True, None  # can't verify printer state without pywin32; Sumatra path is OK
    return _windows_printer_status(printer_config["printer_name"])


def _windows_printer_status(printer_name):
    """Shared pywin32 check: is `printer_name` installed on this Windows
    machine and not offline/paused/erroring. Used by both the sumatra_pdf
    and windows_raw printer types, since both ultimately go through a
    Windows-installed printer object.

    Always returns a (bool, error) tuple, never raises -- test_connection()
    and _sumatra_test_connection() both expect that contract. (Caught by
    testing: an earlier version raised PrintError here on missing pywin32,
    which would have crashed the status-check loop instead of showing a
    clean "pywin32 not installed" message.)"""
    try:
        import win32print
    except ImportError:
        return False, "pywin32 is required for windows_raw printers -- pip install pywin32"

    try:
        installed = [p[2] for p in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        )]
        if printer_name not in installed:
            return False, f"Printer '{printer_name}' is not installed on this PC"
        handle = win32print.OpenPrinter(printer_name)
        try:
            info = win32print.GetPrinter(handle, 2)
            if info["Status"] != 0:
                return False, f"Printer '{printer_name}' reports status code {info['Status']} (offline, paused, or in an error state)"
        finally:
            win32print.ClosePrinter(handle)
        return True, None
    except Exception as exc:
        return False, str(exc)


def _send_windows_raw(printer_config, command_language, payload):
    """Sends raw ESC/POS bytes straight through the Windows print spooler's
    RAW datatype -- no driver rendering, no dialog. This is the standard
    way to do raw command-language printing (ESC/POS, but also PCL/PostScript
    if it ever comes up) to a printer on Windows, USB-attached or not, as
    long as it's installed as a Windows printer object.

    ESC/POS payloads arrive base64-encoded (see bahmni.label.template.
    create_print_job on the Odoo side) -- control bytes like ESC (0x1B)
    can't survive as plain XML-RPC string content, same reason PDF payloads
    are base64 too."""
    try:
        import win32print
    except ImportError as exc:
        raise PrintError("pywin32 is required for windows_raw printers -- pip install pywin32") from exc

    printer_name = printer_config["printer_name"]
    if command_language == "escpos":
        data = base64.b64decode(payload)
    else:
        data = payload if isinstance(payload, bytes) else payload.encode("utf-8")

    try:
        handle = win32print.OpenPrinter(printer_name)
    except Exception as exc:
        raise PrintError(f"Cannot open Windows printer '{printer_name}' -- {exc}") from exc

    try:
        job = win32print.StartDocPrinter(handle, 1, ("print_agent job", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    except Exception as exc:
        raise PrintError(f"Raw print to '{printer_name}' failed -- {exc}") from exc
    finally:
        win32print.ClosePrinter(handle)


def _on_path(executable_name):
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    return any(os.path.isfile(os.path.join(d, executable_name)) for d in path_dirs)


def _send_cups(printer_config, command_language, payload):
    try:
        import cups
    except ImportError as exc:
        raise PrintError("pycups is not installed on this platform") from exc

    queue_name = printer_config["queue_name"]
    conn = cups.Connection()

    pdf_bytes = base64.b64decode(payload) if command_language == "pdf" else payload.encode("utf-8")
    fd, path = tempfile.mkstemp(suffix=".pdf" if command_language == "pdf" else ".raw")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_bytes)
        options = {"raw": "true"} if command_language != "pdf" else {}
        conn.printFile(queue_name, path, "print_agent job", options)
    except Exception as exc:
        raise PrintError(f"CUPS print to '{queue_name}' failed -- {exc}") from exc
    finally:
        os.unlink(path)


SAMPLE_TSPL = (
    'SIZE 50 mm, 25 mm\nGAP 3 mm, 0 mm\nCLS\n'
    'TEXT 20,20,"3",0,1,1,"PRINT AGENT TEST"\n'
    'TEXT 20,60,"2",0,1,1,"Connection OK"\nPRINT 1\n'
)


def test_print(printer_config):
    if printer_config.get("type") == "sumatra_pdf":
        raise PrintError("Test Print isn't implemented for PDF printers yet -- use Test Connection")
    dispatch(printer_config, "tspl", SAMPLE_TSPL)
