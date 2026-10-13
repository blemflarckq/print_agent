"""Thin wrapper around Odoo's standard external API (XML-RPC).

No custom Odoo controller is required -- because exactly one Print Agent instance
is ever Active at a time (see election.py), there is no multi-writer race on the
queue, so plain search_read/write calls are sufficient. Point this at a dedicated
API user restricted (via the print_agent_security.xml group) to bahmni.print.job
and bahmni.label.template only.
"""
import xmlrpc.client
import logging

log = logging.getLogger("print_agent.odoo")


class OdooClientError(Exception):
    pass


class OdooClient:
    def __init__(self, url, db, username, api_key):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.api_key = api_key
        self._uid = None
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def authenticate(self):
        self._uid = self._common.authenticate(self.db, self.username, self.api_key, {})
        if not self._uid:
            raise OdooClientError("Authentication failed -- check db/username/api_key")
        return self._uid

    def _ensure_auth(self):
        if self._uid is None:
            self.authenticate()

    def ping(self):
        try:
            self._common.version()
            return True
        except Exception as exc:
            log.debug("Odoo ping failed: %s", exc)
            return False

    def get_pending_jobs(self, limit=20):
        self._ensure_auth()
        return self._models.execute_kw(
            self.db, self._uid, self.api_key,
            "bahmni.print.job", "search_read",
            [[["state", "=", "pending"]]],
            {"fields": ["id", "label_type", "printer_key", "command_language", "payload"],
             "order": "create_date asc", "limit": limit},
        )

    def mark_done(self, job_id):
        self._ensure_auth()
        self._models.execute_kw(
            self.db, self._uid, self.api_key,
            "bahmni.print.job", "write", [[job_id], {"state": "done"}],
        )

    def mark_failed(self, job_id, error_message):
        self._ensure_auth()
        self._models.execute_kw(
            self.db, self._uid, self.api_key,
            "bahmni.print.job", "write",
            [[job_id], {"state": "failed", "error_message": str(error_message)[:2000]}],
        )
