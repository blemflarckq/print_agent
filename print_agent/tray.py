"""Entry point: wires config -> odoo client -> election -> poller -> tray icon
+ status window together.

Deliberately a visible, user-restartable tray application, not a Windows
Service -- normal staff need to be able to see it's running and quit/restart
it themselves.
"""
import logging
import socket
import threading
import time

import pystray
import webview

from .config import Config
from .odoo_client import OdooClient
from .election import ElectionState
from .state import AgentState
from .poller import Poller
from .icons import make_icon, overall_color
from .ui.api import Api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("print_agent.tray")


def build_app(config_path=None):
    cfg = Config(config_path)

    odoo = OdooClient(**cfg.odoo)
    election_cfg = cfg.election
    election = ElectionState(
        hostname=socket.gethostname(),
        priority=election_cfg.get("priority", 10),
        udp_port=election_cfg.get("udp_port", 47990),
        broadcast_interval=election_cfg.get("broadcast_interval_seconds", 2),
        missed_beats=election_cfg.get("missed_beats_before_failover", 3),
    )
    state = AgentState()
    poller = Poller(odoo, election, state, cfg.printers, cfg.poll_interval)
    api = Api(state, election, odoo, cfg.printers)

    return cfg, odoo, election, state, poller, api


def run():
    cfg, odoo, election, state, poller, api = build_app()

    election.start()
    poller.start()

    window = webview.create_window(
        "Bahmni Print Agent", "print_agent/ui/status.html", js_api=api,
        width=520, height=640, hidden=True,
    )

    def icon_updater(icon):
        while True:
            snap = api.get_snapshot()
            icon.icon = make_icon(overall_color(snap))
            time.sleep(5)

    def on_open(icon, item):
        window.show()

    def on_quit(icon, item):
        icon.stop()
        window.destroy()

    menu = pystray.Menu(
        pystray.MenuItem("Open Status", on_open, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    tray_icon = pystray.Icon("bahmni_print_agent", make_icon("gray"), "Bahmni Print Agent", menu)

    threading.Thread(target=icon_updater, args=(tray_icon,), daemon=True).start()
    threading.Thread(target=tray_icon.run, daemon=True).start()

    webview.start()


if __name__ == "__main__":
    run()
