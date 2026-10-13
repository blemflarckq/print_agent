"""JS-facing API exposed to the pywebview status window. Kept thin -- it only
reads from AgentState / ElectionState and delegates actions to the printers
module or Odoo client; no business logic lives here."""
import logging

from .. import printers

log = logging.getLogger("print_agent.ui")


class Api:
    def __init__(self, agent_state, election_state, odoo_client, printer_registry):
        self.agent_state = agent_state
        self.election_state = election_state
        self.odoo = odoo_client
        self.printer_registry = printer_registry

    def get_snapshot(self):
        snap = self.agent_state.snapshot()
        snap["role"] = self.election_state.role
        snap["peers"] = self.election_state.peers_snapshot()
        return snap

    def force_active(self):
        self.election_state.force_active(True)
        return True

    def test_connection(self, printer_key):
        cfg = self.printer_registry.get(printer_key)
        if not cfg:
            return {"ok": False, "error": "not configured"}
        ok, error = printers.test_connection(cfg)
        self.agent_state.set_printer_status(printer_key, ok, error)
        return {"ok": ok, "error": error}

    def test_print(self, printer_key):
        cfg = self.printer_registry.get(printer_key)
        if not cfg:
            return {"ok": False, "error": "not configured"}
        try:
            printers.test_print(cfg)
            self.agent_state.set_printer_status(printer_key, True)
            return {"ok": True}
        except printers.PrintError as exc:
            self.agent_state.set_printer_status(printer_key, False, str(exc))
            return {"ok": False, "error": str(exc)}

    def retry_failed(self, label_type):
        try:
            self.odoo._ensure_auth()
            jobs = self.odoo._models.execute_kw(
                self.odoo.db, self.odoo._uid, self.odoo.api_key,
                "bahmni.print.job", "search",
                [[["state", "=", "failed"], ["label_type", "=", label_type]]],
                {"order": "create_date desc", "limit": 1},
            )
            if jobs:
                self.odoo._models.execute_kw(
                    self.odoo.db, self.odoo._uid, self.odoo.api_key,
                    "bahmni.print.job", "action_requeue", [jobs],
                )
            return {"ok": True}
        except Exception as exc:
            log.warning("Retry failed: %s", exc)
            return {"ok": False, "error": str(exc)}
