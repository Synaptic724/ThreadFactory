# tests/synchronization/controllers/test_extra_controller_conductor.py
# -------------------------------------------------------------------
# Extra smoke + edge-case coverage for Conductor / SignalController /
# SignalBarrier / ClockBarrier / Dynaphore.
# -------------------------------------------------------------------
import threading, time, logging, unittest
from typing import List, Any, Dict, Optional
from thread_factory import Conductor, SignalController, SignalBarrier, Dynaphore, ClockBarrier


# ---------- helpers -------------------------------------------------
def _spawn(n: int, fn: callable, names: Optional[List[str]] = None):
    ts = []
    for i in range(n):
        t = threading.Thread(target=fn, daemon=True)
        if names and i < len(names):
            t.name = names[i]
        ts.append(t)
        t.start()
    return ts
# --------------------------------------------------------------------


class TestDynaphore(unittest.TestCase):
    def test_permit_scaling_and_release_all(self):
        d = Dynaphore(value=0)
        hit = {"ok": False}

        def waiter():
            if d.wait_for_permit(timeout=0.2):
                hit["ok"] = True
                d.release_permit()

        t = _spawn(1, waiter)[0]
        time.sleep(0.05)
        self.assertFalse(hit["ok"])
        d.increase_permits(1)
        t.join(0.5)
        self.assertTrue(hit["ok"])
        d.wait_for_permit(timeout=0.1)  # should succeed (permit returned)
        d.release_all()                 # smoke: no waiters, just ensure no crash
        d.dispose()


class TestSignalBarrierManual(unittest.TestCase):
    def test_manual_release_reusable(self):
        sb = SignalBarrier(threshold=2, reusable=True, manual_release=True)
        passed = {"count": 0}

        def waiter():
            if sb.wait(timeout=0.5):
                passed["count"] += 1

        _spawn(2, waiter)
        time.sleep(0.05)      # threshold hit but still blocked
        self.assertEqual(passed["count"], 0)
        sb.release()          # manual unblock
        time.sleep(0.05)
        self.assertEqual(passed["count"], 2)
        self.assertFalse(sb.is_spent())  # reusable: not spent
        sb.dispose()


class TestClockBarrier(unittest.TestCase):
    def test_global_timeout_breaks_barrier(self):
        cb = ClockBarrier(threshold=3, timeout=0.1)
        broken = {"flag": False}

        def waiter():
            try:
                cb.wait()
            except threading.BrokenBarrierError:
                broken["flag"] = True

        _spawn(2, waiter)      # < threshold
        time.sleep(0.25)       # exceeds timeout
        self.assertTrue(broken["flag"])
        self.assertTrue(cb.is_broken())
        cb.dispose()


class TestSignalControllerBroadcast(unittest.TestCase):
    def test_invoke_on_all_resets_conductors(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        c1 = Conductor(threshold=1, reusable=True, controller=ctrl)
        c2 = Conductor(threshold=1, reusable=True, controller=ctrl)

        _spawn(1, c1.start)[0].join()
        _spawn(1, c2.start)[0].join()
        self.assertTrue(c1._released and c2._released)

        ctrl.invoke_on_all("reset", name_filter="conductor")
        self.assertFalse(c1._released or c2._released)

        c1.dispose(); c2.dispose(); ctrl.dispose()


class TestConductorTimeoutBehaviour(unittest.TestCase):
    def test_raise_on_timeout_true_raises(self):
        c = Conductor(threshold=2, timeout=0.05, raise_on_timeout=True)
        with self.assertRaises(TimeoutError):
            c.start()
        self.assertTrue(c._broken)
        c.dispose()

    def test_raise_on_timeout_false_returns(self):
        c = Conductor(threshold=2, timeout=0.05, raise_on_timeout=False)
        self.assertIsNone(c.start())   # returns normally
        self.assertTrue(c._broken)
        c.dispose()


class TestControllerSubscribe(unittest.TestCase):
    def test_subscribe_and_notify_flow(self):
        """Controller should receive all lifecycle events when tasks exist."""
        ctrl   = SignalController(logger=logging.getLogger("silence"))
        events: List[str] = []

        def rec(_id, ev, _data): events.append(ev)

        # NOTE: provide a task so EXECUTION_* events fire
        c = Conductor(threshold=1, tasks=[lambda: "work"], controller=ctrl)

        ctrl.subscribe(c.id, "BARRIER_PASSED",        rec)
        ctrl.subscribe(c.id, "EXECUTION_STARTED",     rec)
        ctrl.subscribe(c.id, "EXECUTION_COMPLETED",   rec)

        _spawn(1, c.start)[0].join()

        self.assertEqual(events,
                         ["BARRIER_PASSED",
                          "EXECUTION_STARTED",
                          "EXECUTION_COMPLETED"])
        c.dispose(); ctrl.dispose()

if __name__ == "__main__":
    unittest.main(verbosity=2)
