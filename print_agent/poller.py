"""The polling loop. Only does anything when this instance's role is ACTIVE --
Standby instances skip straight to the printer-connectivity check so their own
status window still stays accurate, without touching the Odoo queue."""
import logging
import threading
import time

from . import printers
from .election import ACTIVE
from .odoo_client import OdooClientError

log = logging.getLogger("print_agent.poller")


class Poller:
    def __init__(self, odoo_client, election_state, agent_state, printer_registry, poll_interval):
        self.odoo = odoo_client
        self.election = election_state
        self.state = agent_state
        self.printer_registry = printer_registry
        self.poll_interval = poll_interval
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._printer_check_loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            if self.election.role == ACTIVE:
                self._poll_once()
            time.sleep(self.poll_interval)

    def _poll_once(self):
        try:
            jobs = self.odoo.get_pending_jobs()
            self.state.set_server_status(True)
        except Exception as exc:
            log.warning("Could not reach Odoo: %s", exc)
            self.state.set_server_status(False)
            return

        for job in jobs:
            printer_key = job["printer_key"]
            printer_config = self.printer_registry.get(printer_key)
            if printer_config is None:
                self.odoo.mark_failed(job["id"], f"No printer configured locally for key '{printer_key}'")
                self.state.record_job(job["label_type"], printer_key, "failed",
                                       f"Unknown printer_key '{printer_key}'")
                continue
            try:
                printers.dispatch(printer_config, job["command_language"], job["payload"])
                self.odoo.mark_done(job["id"])
                self.state.record_job(job["label_type"], printer_key, "done")
                self.state.set_printer_status(printer_key, True)
            except printers.PrintError as exc:
                self.odoo.mark_failed(job["id"], str(exc))
                self.state.record_job(job["label_type"], printer_key, "failed", str(exc))
                self.state.set_printer_status(printer_key, False, str(exc))

    def _printer_check_loop(self):
        while not self._stop.is_set():
            for key, cfg in self.printer_registry.items():
                ok, error = printers.test_connection(cfg)
                self.state.set_printer_status(key, ok, error)
            try:
                self.state.set_server_status(self.odoo.ping())
            except Exception:
                self.state.set_server_status(False)
            time.sleep(15)
