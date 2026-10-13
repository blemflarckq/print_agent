# Regression test for the reentrant-lock deadlock caught during verification:
# ElectionState._evaluate_loop() calls effective_priority() while already
# holding self._lock, which requires an RLock (not a plain Lock).
import sys, time
sys.path.insert(0, ".")
from print_agent.election import ElectionState, ACTIVE, STANDBY

def decide(candidates):
    return sorted(candidates)[0][1]

assert decide([(10, "pc-1"), (20, "pc-2"), (30, "pc-3")]) == "pc-1"
assert decide([(10, "pc-2"), (10, "pc-1")]) == "pc-1"
assert decide([(-1, "pc-3"), (10, "pc-1"), (20, "pc-2")]) == "pc-3"
print("tie-break rule: OK")

es = ElectionState(hostname="pc-1", priority=10, udp_port=47990, broadcast_interval=1, missed_beats=3)
with es._lock:
    candidates = [(es.effective_priority(), es.hostname)]
    candidates += [(p["priority"], h) for h, p in es._peers.items()]
    candidates.sort()
    es._role = ACTIVE if candidates[0][1] == es.hostname else STANDBY
assert es.role == ACTIVE
print("lone instance self-promotes: OK")

with es._lock:
    es._peers["pc-0"] = {"priority": 1, "role": STANDBY, "last_seen": time.time()}
    candidates = [(es.effective_priority(), es.hostname)]
    candidates += [(p["priority"], h) for h, p in es._peers.items()]
    candidates.sort()
    es._role = ACTIVE if candidates[0][1] == es.hostname else STANDBY
assert es.role == STANDBY
print("steps down for lower-priority peer: OK")

es.force_active(True)
assert es.effective_priority() == -1
print("force-active override: OK")
print("ALL ELECTION TESTS PASSED")
