"""Local peer election between the Print Agent instances on the clinic LAN.

Exactly one peer is Active at a time; the rest are Standby. Election is a UDP
broadcast on the local subnet -- no central coordinator, no Odoo involvement.

Rule: among all instances seen broadcasting within the last
`missed_beats_before_failover` intervals, the one with the lowest `priority`
value is Active (ties broken by hostname, alphabetically first wins). If the
current Active goes silent, the remaining Standbys re-elect within a few
seconds.

Known trade-off (documented in the design spec, section 6): during failover
there's a brief window where the outgoing Active could still be mid-print when
a new Active starts polling, risking a duplicate label. Accepted as low-severity
for label printing rather than engineered away with distributed consensus.
"""
import json
import socket
import threading
import time
import logging

log = logging.getLogger("print_agent.election")

ACTIVE = "ACTIVE"
STANDBY = "STANDBY"


class ElectionState:
    def __init__(self, hostname, priority, udp_port, broadcast_interval, missed_beats):
        self.hostname = hostname
        self.base_priority = priority
        self.udp_port = udp_port
        self.broadcast_interval = broadcast_interval
        self.stale_after = broadcast_interval * missed_beats

        # RLock, not Lock: _evaluate_loop() calls effective_priority() while
        # already holding this lock. A plain Lock would self-deadlock the first
        # time the evaluation loop ran -- caught during verification testing.
        self._lock = threading.RLock()
        self._peers = {}
        self._role = STANDBY
        self._force_active = False
        self._stop = threading.Event()

    @property
    def role(self):
        with self._lock:
            return self._role

    def peers_snapshot(self):
        with self._lock:
            return dict(self._peers)

    def force_active(self, enabled=True):
        with self._lock:
            self._force_active = enabled
        log.info("Force-active set to %s", enabled)

    def effective_priority(self):
        with self._lock:
            return -1 if self._force_active else self.base_priority

    def start(self):
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._evaluate_loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        while not self._stop.is_set():
            msg = json.dumps({
                "hostname": self.hostname,
                "priority": self.effective_priority(),
                "role": self.role,
                "ts": time.time(),
            }).encode("utf-8")
            try:
                sock.sendto(msg, ("255.255.255.255", self.udp_port))
            except OSError as exc:
                log.warning("Election broadcast failed: %s", exc)
            time.sleep(self.broadcast_interval)

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.udp_port))
        while not self._stop.is_set():
            try:
                data, _addr = sock.recvfrom(2048)
                packet = json.loads(data.decode("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if packet.get("hostname") == self.hostname:
                continue
            with self._lock:
                self._peers[packet["hostname"]] = {
                    "priority": packet["priority"],
                    "role": packet.get("role", STANDBY),
                    "last_seen": time.time(),
                }

    def _evaluate_loop(self):
        while not self._stop.is_set():
            now = time.time()
            with self._lock:
                stale = [h for h, p in self._peers.items() if now - p["last_seen"] > self.stale_after]
                for h in stale:
                    log.info("Peer %s timed out -- removing from election", h)
                    del self._peers[h]

                candidates = [(self.effective_priority(), self.hostname)]
                candidates += [(p["priority"], h) for h, p in self._peers.items()]
                candidates.sort()
                winner_host = candidates[0][1]

                new_role = ACTIVE if winner_host == self.hostname else STANDBY
                if new_role != self._role:
                    log.info("Role change: %s -> %s (winner=%s, candidates=%s)",
                              self._role, new_role, winner_host, candidates)
                self._role = new_role
            time.sleep(1)
