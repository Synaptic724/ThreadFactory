# tests/synchronization/controllers/test_conductor_controller_extra.py
# -------------------------------------------------------------------
# 5 focused unit-tests covering Conductor <---> SignalController paths
# -------------------------------------------------------------------
import threading, time, unittest, logging
from typing import List, Any, Dict, Optional

from thread_factory.synchronization.coordinators.conductor        import Conductor
from thread_factory.synchronization.controllers.signal_controller import SignalController


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


class TestConductorControllerFocus(unittest.TestCase):

    # --------------------------------------------------------------
    # 1. Event ordering end-to-end
    # --------------------------------------------------------------
    def test_event_sequence(self):
        ctrl   = SignalController(logger=logging.getLogger("silence"))
        events: List[str] = []

        def rec(_i, ev, _d): events.append(ev)

        c = Conductor(threshold=2,
                      tasks=[lambda: "work"],
                      controller=ctrl)

        for ev in ("BARRIER_PASSED",
                   "EXECUTION_STARTED",
                   "EXECUTION_COMPLETED"):
            ctrl.subscribe(c.id, ev, rec)

        _spawn(2, c.start)
        time.sleep(0.2)
        self.assertEqual(events,
                         ["BARRIER_PASSED",
                          "EXECUTION_STARTED",
                          "EXECUTION_COMPLETED"])
        c.dispose(); ctrl.dispose()

    # --------------------------------------------------------------
    # 2. Broadcast reset over multiple conductors
    # --------------------------------------------------------------
    def test_broadcast_reset(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        c1   = Conductor(threshold=1, reusable=True, controller=ctrl)
        c2   = Conductor(threshold=1, reusable=True, controller=ctrl)

        _spawn(1, c1.start)[0].join()
        _spawn(1, c2.start)[0].join()

        self.assertTrue(c1._released and c2._released)
        ctrl.invoke_on_all("reset", name_filter="conductor")
        self.assertFalse(c1._released or c2._released)

        c1.dispose(); c2.dispose(); ctrl.dispose()

    # --------------------------------------------------------------
    # 3. Manual release path via controller
    # --------------------------------------------------------------
    def test_manual_release_flow(self):
        ctrl  = SignalController(logger=logging.getLogger("silence"))
        done  = threading.Event()

        c = Conductor(threshold=2,
                      manual_release=True,
                      controller=ctrl)

        def waiter(): c.start(); done.set()
        _spawn(2, waiter)
        time.sleep(0.05)
        self.assertFalse(done.is_set())          # still blocked
        ctrl.invoke(c.id, "release")             # controller issues release
        self.assertTrue(done.wait(0.5))          # now unblocked

        c.dispose(); ctrl.dispose()

    # --------------------------------------------------------------
    # 4. Unregister removes subscriptions & object entry
    # --------------------------------------------------------------
    def test_unregister_flow(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        c    = Conductor(threshold=1, controller=ctrl)

        ctrl.unregister(c.id, dispose_object=False)
        self.assertEqual(ctrl.list_objects(name_filter="conductor"), [])
        self.assertEqual(ctrl.get_waiting_objects(), [])

        c.dispose(); ctrl.dispose()

    # --------------------------------------------------------------
    # 5. Timeout raises + event emission
    # --------------------------------------------------------------
    def test_timeout_raises_and_emits_event(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        events: List[str] = []

        def rec(_i, ev, _d): events.append(ev)

        c = Conductor(threshold=2,
                      timeout=0.05,
                      raise_on_timeout=True,
                      controller=ctrl)

        ctrl.subscribe(c.id, "BARRIER_BROKEN", rec)

        with self.assertRaises(TimeoutError):
            c.start()

        self.assertTrue(c._broken)
        self.assertEqual(events, ["BARRIER_BROKEN"])

        c.dispose(); ctrl.dispose()


    # 1 ─ Pre/Post-invoke hook execution order --------------------------------
    def test_pre_post_invoke_hook_order(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        order: List[str] = []

        ctrl.add_pre_invoke_hook (lambda _i, _c: order.append("pre1"))
        ctrl.add_pre_invoke_hook (lambda _i, _c: order.append("pre2"))
        ctrl.add_post_invoke_hook(lambda _i, _c, _r, _e: order.append("post1"))
        ctrl.add_post_invoke_hook(lambda _i, _c, _r, _e: order.append("post2"))

        c = Conductor(threshold=1, reusable=True, controller=ctrl)
        ctrl.invoke(c.id, "reset")              # any exposed command is fine

        self.assertEqual(order, ["pre1", "pre2", "post1", "post2"])
        c.dispose(); ctrl.dispose()

    # 2 ─ Duplicate registration rejected ------------------------------------
    def test_duplicate_registration_rejected(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        c    = Conductor(threshold=1, controller=ctrl)
        with self.assertRaises(ValueError):
            ctrl.register(c)                    # same object → duplicate ID
        c.dispose(); ctrl.dispose()

    def test_unregister_during_active_wait(self):
        ctrl     = SignalController(logger=logging.getLogger("silence"))
        finished = threading.Event()
        c        = Conductor(threshold=2, controller=ctrl)

        def waiter():
            try:
                c.start()
            except Exception:
                pass
            finally:
                finished.set()

        _spawn(1, waiter)
        time.sleep(0.05)                        # ensure thread is waiting
        ctrl.unregister(c.id)                   # default dispose_object=True
        self.assertTrue(finished.wait(0.5))     # thread must unblock

        # Conductor should be gone, but internal barriers may still be registered.
        ids = [obj['id'] for obj in ctrl.list_objects()]
        self.assertNotIn(c.id, ids)

        ctrl.dispose()                          # c already disposed

    # 4 ─ Controller override unblocks waiters -------------------------------
    def test_controller_override_unblocks_waiters(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        done = threading.Event()

        c = Conductor(threshold=3, controller=ctrl)

        # 2 of 3 threads start and block at the barrier
        _spawn(2, c.start)

        def waiter():
            c.start()
            done.set()

        # Third thread will be started only *after* override
        late_thread = threading.Thread(target=waiter, daemon=True)
        time.sleep(0.05)                  # ensure first 2 are waiting
        ctrl.invoke(c.id, "notify_all_override")  # break the barrier
        late_thread.start()
        self.assertTrue(done.wait(0.5))   # thread ran through without hanging
        self.assertTrue(c._broken)

        c.dispose(); ctrl.dispose()

    # 5 ─ Reset invoked mid-execution on reusable conductor ------------------
    def test_reset_mid_execution_safe(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        slow = lambda: time.sleep(0.2)
        c    = Conductor(threshold=2, tasks=[slow], reusable=True, controller=ctrl)

        _spawn(2, c.start)
        time.sleep(0.05)                        # tasks still running
        # Should not raise or corrupt state
        ctrl.invoke(c.id, "reset")
        self.assertFalse(c._broken)
        c.dispose(); ctrl.dispose()

    # 6 ─ Manual release via controller fires callback once ------------------
    def test_manual_release_with_callback(self):
        hits = {"n": 0}
        def cb(): hits["n"] += 1

        ctrl = SignalController(logger=logging.getLogger("silence"))
        c    = Conductor(threshold=2,
                         manual_release=True,
                         tasks=[lambda: "ok"],
                         callback=cb,
                         controller=ctrl)

        _spawn(2, c.start)
        time.sleep(0.05)                        # still waiting
        ctrl.invoke(c.id, "release")            # unblock
        time.sleep(0.05)
        self.assertEqual(hits["n"], 1)          # one task → one callback
        c.dispose(); ctrl.dispose()

    # 7 ─ Subscriber misbehaves – controller continues -----------------------
    def test_bad_subscriber_does_not_break_controller(self):
        ctrl   = SignalController(logger=logging.getLogger("silence"))
        good   = {"called": False}

        def bad_sub(_i, _e, _d): 1 / 0
        def good_sub(_i, _e, _d): good["called"] = True

        c = Conductor(threshold=1, tasks=[lambda: "x"], controller=ctrl)
        for ev in ("BARRIER_PASSED", "EXECUTION_COMPLETED"):
            ctrl.subscribe(c.id, ev, bad_sub)
            ctrl.subscribe(c.id, ev, good_sub)

        _spawn(1, c.start)[0].join()
        self.assertTrue(good["called"])         # bad sub didn't block good sub
        self.assertFalse(ctrl.is_disposed)
        c.dispose(); ctrl.dispose()

    # 8 ─ Concurrent `.invoke()` stress test ---------------------------------
    def test_concurrent_invoke_thread_safety(self):
        ctrl = SignalController(logger=logging.getLogger("silence"))
        c    = Conductor(threshold=1, reusable=True, controller=ctrl)
        errors: List[Any] = []

        def invoker():
            try:
                for _ in range(10):
                    ctrl.invoke(c.id, "reset")
            except Exception as e:
                errors.append(e)

        _spawn(20, invoker)
        time.sleep(0.5)
        self.assertEqual(errors, [])            # no races / KeyErrors
        c.dispose(); ctrl.dispose()


if __name__ == "__main__":
    unittest.main(verbosity=2)
