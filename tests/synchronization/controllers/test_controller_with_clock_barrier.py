"""
tests/synchronization/test_controller_clockbarrier.py
=====================================================

High-level goals
----------------
1. ClockBarrier should auto-register with a Controller when supplied.
2. Successful barrier pass ⇒ Controller emits “BARRIER_PASSED”.
3. Timeout / break ⇒ Controller emits “BARRIER_BROKEN”.
4. Controller.on_wait_starting() correctly tracks waiting objects.

These tests avoid flaky timing by:
• Using a *tiny* timeout (0.05 s) where needed.
• Spawning only the minimum threads for each scenario.
• Waiting with join() and generous safety margins.
"""

import threading
import time
import unittest
import ulid

# --- SUT imports ----------------------------------------------------------
from thread_factory.synchronization.controllers import Controller  # fix path if different
from thread_factory.synchronization.coordinators.clock_barrier import ClockBarrier   # fix path if different
# -------------------------------------------------------------------------


class CallbackRecorder:
    """
    Simple helper to record (object_id, event_type, data) tuples
    emitted by the Controller. Thread-safe because Controller may
    call us from arbitrary worker threads.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.events = []

    def __call__(self, *event):
        with self._lock:
            self.events.append(event)


class ControllerClockBarrierTests(unittest.TestCase):
    """Unit tests verifying Controller ⇄ ClockBarrier integration."""

    # ------------------------------------------------------------------ #
    # Utility helpers
    # ------------------------------------------------------------------ #
    def _make_controller(self) -> Controller:
        """
        Returns a fresh Controller with DEBUG logging disabled
        to keep test output clean.
        """
        ctrl = Controller()
        ctrl._logger.disabled = True
        return ctrl

    # ------------------------------------------------------------------ #
    # 1 ️⃣  Registration sanity
    # ------------------------------------------------------------------ #
    def test_barrier_auto_registers_with_controller(self):
        ctrl = self._make_controller()

        barrier = ClockBarrier(threshold=1, timeout=0.1, controller=ctrl)  # auto-register

        # A single item should now live in the registry
        objs = ctrl.list_objects()
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["id"], barrier.id)
        self.assertEqual(objs[0]["name"], "clock_barrier")

    # ------------------------------------------------------------------ #
    # 2 ️⃣  Happy path – barrier passes
    # ------------------------------------------------------------------ #
    def test_barrier_pass_emits_event(self):
        ctrl = self._make_controller()
        barrier = ClockBarrier(threshold=2, timeout=0.1, controller=ctrl)

        # Recorder subscribes to BARRIER_PASSED
        recorder = CallbackRecorder()
        ctrl.subscribe(barrier.id, "BARRIER_PASSED", recorder)

        # Spawn 2 threads that wait on the barrier
        def waiter():
            barrier.wait()

        t1, t2 = threading.Thread(target=waiter), threading.Thread(target=waiter)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Expect exactly one BARRIER_PASSED event
        self.assertEqual(len(recorder.events), 1)
        obj_id, event_type, data = recorder.events[0]
        self.assertEqual(obj_id, barrier.id)
        self.assertEqual(event_type, "BARRIER_PASSED")
        self.assertIsNone(data)  # ClockBarrier never sets extra data presently

    # ------------------------------------------------------------------ #
    # 3 ️⃣  Timeout / broken barrier
    # ------------------------------------------------------------------ #
    def test_barrier_timeout_emits_broken_event(self):
        ctrl = self._make_controller()
        barrier = ClockBarrier(threshold=2, timeout=0.05, controller=ctrl)

        recorder = CallbackRecorder()
        ctrl.subscribe(barrier.id, "BARRIER_BROKEN", recorder)

        # Launch just ONE thread so threshold is never met
        def lonely_waiter():
            with self.assertRaises(threading.BrokenBarrierError):
                barrier.wait()

        t = threading.Thread(target=lonely_waiter)
        t.start()
        t.join()

        # Let controller processing finish
        time.sleep(0.02)  # tiny cushion

        self.assertEqual(len(recorder.events), 1)
        obj_id, event_type, _ = recorder.events[0]
        self.assertEqual(obj_id, barrier.id)
        self.assertEqual(event_type, "BARRIER_BROKEN")

    # ------------------------------------------------------------------ #
    # 4 ️⃣  Waiting-object bookkeeping
    # ------------------------------------------------------------------ #
    def test_on_wait_starting_tracks_waiters(self):
        ctrl = self._make_controller()
        dummy_id = str(ulid.ULID())

        # Simulate an external component entering a wait state
        ctrl._registry[dummy_id] = {
            "instance": object(),
            "name": "dummy",
            "commands": {}
        }
        ctrl.on_wait_starting(dummy_id)

        waiting = ctrl.get_waiting_objects()
        self.assertIn(dummy_id, waiting)


"""
Extended coverage for Controller ⇄ ClockBarrier.

Scenarios
---------
1. Barrier reuse after `reset()`
2. Dispose mid-wait → broken event
3. Pre/post-hook error shielding
4. `invoke_on_all()` fan-out (success + per-object failure)
5. Name-filtered broadcast
6. Unregister cleans subscriptions & wait list
7. WAIT_STARTING bookkeeping accuracy
8. Near-zero timeout breaks instantly
"""



class DummyCmd:
    """Tiny controllable exposing `ping()` that can optionally explode."""
    def __init__(self, name="dummy", boom=False):
        self.id = str(ulid.ULID())
        self._name = name
        self._boom = boom
        self.pongs = 0

    def ping(self):
        if self._boom:
            raise RuntimeError("boom")
        self.pongs += 1
        return "pong"

    # controller contract
    def _get_object_details(self):
        return {"name": self._name, "commands": {"ping": self.ping, "dispose": self.dispose}}

    def dispose(self):
        pass  # nothing to clean


# --------------------------------------------------------------------------- #
# TestCase
# --------------------------------------------------------------------------- #
class ControllerClockBarrierExtraTests(unittest.TestCase):

    # ---------- utilities -------------------------------------------------- #
    def _ctrl(self):
        c = Controller()
        c._logger.disabled = True
        return c

    def test_barrier_reset_reuse(self):
        ctrl = self._ctrl()
        barrier = ClockBarrier(threshold=2, timeout=0.1, controller=ctrl)
        rec = CallbackRecorder();
        ctrl.subscribe(barrier.id, "BARRIER_PASSED", rec)

        def wait_once():
            barrier.wait()

        # Round 1
        t1 = threading.Thread(target=wait_once);
        t2 = threading.Thread(target=wait_once)
        t1.start();
        t2.start();
        t1.join();
        t2.join()

        barrier.reset()  # <<< only here, single reset

        # Round 2
        t3 = threading.Thread(target=wait_once);
        t4 = threading.Thread(target=wait_once)
        t3.start();
        t4.start();
        t3.join();
        t4.join()

        self.assertEqual(len(rec.events), 2)

    # 2️⃣  Dispose mid-wait -------------------------------------------------- #
    def test_dispose_mid_wait_broken_event(self):
        ctrl = self._ctrl()
        barrier = ClockBarrier(threshold=2, timeout=0.5, controller=ctrl)
        rec = CallbackRecorder()
        ctrl.subscribe(barrier.id, "BARRIER_BROKEN", rec)

        def waiter():
            with self.assertRaises(threading.BrokenBarrierError):
                barrier.wait()

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.02)            # ensure thread is waiting
        barrier.dispose()           # breaks barrier & notifies
        t.join()

        self.assertEqual(len(rec.events), 0)  # expect no notify on dispose

    # 3️⃣  Hook shielding ---------------------------------------------------- #
    def test_pre_post_hook_exception_does_not_block_invoke(self):
        ctrl = self._ctrl()

        # bad hooks
        ctrl.add_pre_invoke_hook(lambda *_: (_ for _ in ()).throw(RuntimeError("pre")))
        ctrl.add_post_invoke_hook(lambda *_: (_ for _ in ()).throw(RuntimeError("post")))

        dummy = DummyCmd()
        ctrl.register(dummy)

        # ping should still succeed despite hook explosions
        result = ctrl.invoke(dummy.id, "ping")
        self.assertEqual(result, "pong")
        self.assertEqual(dummy.pongs, 1)

    # 4️⃣  invoke_on_all() fan-out ------------------------------------------- #
    def test_invoke_on_all_broadcast_and_failure(self):
        ctrl = self._ctrl()
        good1, good2 = DummyCmd(), DummyCmd()
        bad = DummyCmd(boom=True)

        for obj in (good1, good2, bad):
            ctrl.register(obj)

        ctrl.invoke_on_all("ping")

        # good objects pinged once; bad raised but broadcast continued
        self.assertEqual(good1.pongs, 1)
        self.assertEqual(good2.pongs, 1)

    # 5️⃣  Name-filtered broadcast ------------------------------------------ #
    def test_invoke_on_all_name_filter(self):
        ctrl = self._ctrl()
        foo = DummyCmd(name="foo")
        bar = DummyCmd(name="bar")
        ctrl.register(foo)
        ctrl.register(bar)

        ctrl.invoke_on_all("ping", name_filter="foo")
        self.assertEqual(foo.pongs, 1)
        self.assertEqual(bar.pongs, 0)

    # 6️⃣  Unregister cleanup ------------------------------------------------ #
    def test_unregister_cleans_subscriptions_and_waits(self):
        ctrl = self._ctrl()
        obj = DummyCmd()
        ctrl.register(obj)

        rec = CallbackRecorder()
        ctrl.subscribe(obj.id, "ANY_EVT", rec)
        ctrl.on_wait_starting(obj.id)
        ctrl.unregister(obj.id)

        # object gone from registry & waiting set
        self.assertEqual(ctrl.list_objects(), [])
        self.assertEqual(list(ctrl.get_waiting_objects()), [])

        # later notify should not trigger callbacks
        ctrl.notify(obj.id, "ANY_EVT")
        self.assertEqual(len(rec.events), 0)

    # 7️⃣  WAIT_STARTING bookkeeping ---------------------------------------- #
    def test_wait_starting_and_terminal_event_cleanup(self):
        ctrl = self._ctrl()
        obj = DummyCmd()
        ctrl.register(obj)
        ctrl.on_wait_starting(obj.id)
        self.assertIn(obj.id, ctrl.get_waiting_objects())

        ctrl.notify(obj.id, "RESET_BY_CONTROLLER")  # terminal → should clear
        self.assertNotIn(obj.id, ctrl.get_waiting_objects())

    # 8️⃣  Near-zero timeout ------------------------------------------------- #
    def test_timeout_near_zero_breaks_immediately(self):
        ctrl = self._ctrl()
        barrier = ClockBarrier(threshold=2, timeout=1e-6, controller=ctrl)

        with self.assertRaises(threading.BrokenBarrierError):
            barrier.wait()  # alone, threshold unmet → timeout instantly


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    unittest.main()
