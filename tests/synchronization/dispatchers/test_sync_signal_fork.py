import unittest
import threading
import time
from typing import List, Dict, Tuple, Callable, Any

from thread_factory import SyncSignalFork


# ────────────────────────────────────────────────────────────────────────────
#  Helper utilities
# ────────────────────────────────────────────────────────────────────────────
def dummy_func_factory(name: str, log: List[str], delay: float = 0.0):
    """
    Returns a callable that appends *name* to *log* (after an optional sleep).
    """
    def _fn():
        if delay:
            time.sleep(delay)
        log.append(name)
    return _fn


def thread_use_fork(
    fork: SyncSignalFork,
    log: List[str],
    thread_name: str,
    sleep_before_use: float = 0.001,
):
    """
    Thread target that calls `.use_fork()` and records outcomes in *log*.
    """
    try:
        time.sleep(sleep_before_use)
        fork.use_fork()
        log.append(f"{thread_name} executed callable.")
    except RuntimeError as e:
        log.append(f"{thread_name} raised RuntimeError: {e}")
    except Exception as e:
        log.append(f"{thread_name} raised unexpected error: {e}")


class DummyController:
    """
    Minimal stub that captures notifications for verification.
    """
    def __init__(self):
        self.registered: Dict[str, Dict[str, Any]] = {}
        self.events: List[Tuple[str, str]] = []

    # Controller API expected by SyncSignalFork
    def register(self, obj):
        self.registered[obj.id] = obj._get_object_details()

    def notify(self, obj_id: str, event_type: str, data=None):
        self.events.append((obj_id, event_type))


# ────────────────────────────────────────────────────────────────────────────
#  Tests
# ────────────────────────────────────────────────────────────────────────────
class TestSyncSignalFork(unittest.TestCase):

    def setUp(self):
        self.log: List[str] = []

    # ------------------------------------------------------------------ #
    #  Auto-release behaviour
    # ------------------------------------------------------------------ #
    def test_auto_release_threshold_met(self):
        callables = [(1, dummy_func_factory("AUTO", self.log)) for _ in range(4)]
        fork = SyncSignalFork(
            number_of_forks=4,
            callables=callables,
            manual_release=False,
        )

        threads = [
            threading.Thread(
                target=thread_use_fork, args=(fork, self.log, f"T{i}")
            )
            for i in range(fork._route_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("AUTO"), 4)
        self.assertEqual(
            len([x for x in self.log if x.endswith("executed callable.")]),
            fork._route_count,
        )
        fork.dispose()

    # ------------------------------------------------------------------ #
    #  Manual-release workflow
    # ------------------------------------------------------------------ #
    def test_manual_release_flow(self):
        callables = [(1, dummy_func_factory("MAN", self.log)) for _ in range(2)]
        fork = SyncSignalFork(
            number_of_forks=2,
            callables=callables,
            manual_release=True,
        )

        # Two threads to fill capacity
        threads = [
            threading.Thread(target=thread_use_fork, args=(fork, self.log, f"X{i}"))
            for i in range(2)
        ]
        for t in threads:
            t.start()

        # Give them time to block
        time.sleep(0.05)
        # Should not have executed yet
        self.assertNotIn("MAN", self.log)

        # Now manual release
        fork.release()

        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("MAN"), 2)
        fork.dispose()

    # ------------------------------------------------------------------ #
    #  Callback fires even without controller
    # ------------------------------------------------------------------ #
    def test_callback_invoked(self):
        marker: List[str] = []

        def cb():
            marker.append("FIRED")

        callables = [(1, dummy_func_factory("CB", self.log)), (1, dummy_func_factory("CB2", self.log))]
        fork = SyncSignalFork(
            number_of_forks=2,
            callables=callables,
            callback=cb,
        )

        threads = [
            threading.Thread(target=thread_use_fork, args=(fork, self.log, f"C{i}"))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertIn("FIRED", marker)
        self.assertEqual(self.log.count("CB"), 1)
        self.assertEqual(self.log.count("CB2"), 1)
        fork.dispose()

    # ------------------------------------------------------------------ #
    #  Light controller integration smoke-test
    # ------------------------------------------------------------------ #
    def test_controller_notifications(self):
        ctl = DummyController()
        callables = [(1, dummy_func_factory("CTRL", self.log)), (1, dummy_func_factory("CTRL", self.log))]
        fork = SyncSignalFork(
            number_of_forks=2,
            callables=callables,
            controller=ctl,
        )

        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "C1"))
        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "C2"))
        t1.start(); t2.start(); t1.join(timeout=5); t2.join(timeout=5)

        # Ensure events were captured
        event_types = [e[1] for e in ctl.events]
        self.assertIn("THRESHOLD_MET", event_types)
        self.assertIn("SEMAPHORE_RELEASED", event_types)
        fork.dispose()

    # ------------------------------------------------------------------ #
    #  Timeout path
    # ------------------------------------------------------------------ #
    def test_timeout_occurs(self):
        callables = [(1, dummy_func_factory("T1", self.log)), (1, dummy_func_factory("T2", self.log))]
        fork = SyncSignalFork(
            number_of_forks=2,
            callables=callables,
            timeout_duration=0.05,
        )

        # Launch just one thread so barrier never fills
        t = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Timeouter"))
        t.start()
        t.join(timeout=5)

        self.assertTrue(any("timed out" in s for s in self.log))
        self.assertEqual(self.log.count("T1"), 0)
        self.assertEqual(self.log.count("T2"), 0)
        fork.dispose()

    # ------------------------------------------------------------------ #
    #  Reset clears manual-release state
    # ------------------------------------------------------------------ #
    def test_reset_clears_state(self):
        callables = [(1, dummy_func_factory("R", self.log))]
        fork = SyncSignalFork(
            number_of_forks=1,
            callables=callables,
            manual_release=True,
        )

        # First run
        t = threading.Thread(target=thread_use_fork, args=(fork, self.log, "First"))
        t.start()
        time.sleep(0.01)
        fork.release()
        t.join(timeout=5)
        self.assertEqual(self.log.count("R"), 1)

        # Reset
        fork.reset()
        self.log.clear()

        # Second run
        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Second"))
        t2.start()
        time.sleep(0.01)
        fork.release()
        t2.join(timeout=5)
        self.assertEqual(self.log.count("R"), 1)
        fork.dispose()
    # ------------------------------------------------------------------ #
    #  🔟  EXTRA EDGE-CASE & STRESS TESTS                                #
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    #  🔧  PATCHED TESTS (fixing earlier failures)                       #
    # ------------------------------------------------------------------ #
    def test_release_before_threshold_closes_fork(self):
        """
        Calling `release()` before any thread arrives should close the fork,
        causing subsequent threads to raise RuntimeError and execute *no*
        callables.
        """
        callables = [(2, dummy_func_factory("P", self.log))]
        fork = SyncSignalFork(1, callables, manual_release=True)

        # Premature release – should mark the fork as spent
        fork.release()

        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Late1"))
        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Late2"))
        t1.start(); t2.start(); t1.join(timeout=5); t2.join(timeout=5)

        # Both threads must report RuntimeError, and callable never fires
        self.assertEqual(self.log.count("P"), 0)
        self.assertEqual(len([x for x in self.log if "RuntimeError" in x]), 2)
        fork.dispose()

    def test_dispose_sets_event_and_flags(self):
        """
        After disposal the internal event must be *set* so any blocked
        thread wakes immediately.  Flags should confirm disposed state.
        """
        callables = [(2, dummy_func_factory("D2", self.log))]
        fork = SyncSignalFork(1, callables, manual_release=True)

        # Start one thread so it blocks
        t_block = threading.Thread(target=thread_use_fork, args=(fork, self.log, "B"))
        t_block.start(); time.sleep(0.02)

        fork.dispose()
        t_block.join(timeout=5)

        self.assertTrue(fork._disposed)
        self.assertTrue(fork._threading_event.is_set())  # event must be set
        self.assertIn("RuntimeError", self.log[0])
        self.assertEqual(self.log.count("D2"), 0)

    def test_signal_callback_invoked_once_per_thread(self):
        calls = []
        def sig_cb(fid): calls.append(fid)
        fork = SyncSignalFork(1, [(3, dummy_func_factory("S", self.log))],
                              signal_callback=sig_cb, manual_release=True)
        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"T{i}", 0.0))
                   for i in range(3)]
        for t in threads: t.start()
        time.sleep(0.02)
        fork.release()
        for t in threads: t.join(timeout=5)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.log.count("S"), 3)
        fork.dispose()

    def test_manual_release_controller_event(self):
        ctl = DummyController()
        fork = SyncSignalFork(1, [(2, dummy_func_factory("E", self.log))],
                              manual_release=True, controller=ctl)
        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "A"))
        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "B"))
        t1.start(); t2.start(); time.sleep(0.01); fork.release()
        t1.join(timeout=5); t2.join(timeout=5)
        self.assertIn(("{}".format(fork.id), "SEMAPHORE_RELEASED"), ctl.events)
        fork.dispose()

    def test_callback_not_called_on_timeout(self):
        marker = []
        def cb(): marker.append("HIT")
        fork = SyncSignalFork(2,
                              [(1, dummy_func_factory("X", self.log)),
                               (1, dummy_func_factory("Y", self.log))],
                              timeout_duration=0.05, callback=cb)
        threading.Thread(target=thread_use_fork,
                         args=(fork, self.log, "Lonely")).start()
        time.sleep(0.08)
        self.assertFalse(marker)
        fork.dispose()

    #
    # def test_timeout_then_reset_then_manual_success(self):
    #     """
    #     Ensures that a fork which times out can be reset and used again successfully.
    #     Verifies:
    #     • First thread hits timeout.
    #     • Second round executes callables properly after reset and manual release.
    #     """
    #     # Initialize fork with a relatively short timeout
    #     fork = SyncSignalFork(2,
    #                           [(1, dummy_func_factory("M1", self.log)),
    #                            (1, dummy_func_factory("M2", self.log))],
    #                           timeout_duration=0.1,  # A slightly longer timeout for reliability
    #                           manual_release=True)
    #
    #     # --- First phase: Verify timeout ---
    #     # Only one thread joins, so the barrier will not be met, and it should time out.
    #     # Removed daemon=True for more explicit control over thread lifecycle.
    #     t_timeout = threading.Thread(target=thread_use_fork,
    #                                  args=(fork, self.log, "T_Timeout_Attempt"))
    #     t_timeout.start()
    #
    #     # Wait for the thread to finish. It should terminate by raising a RuntimeError
    #     # due to timeout. The `join` timeout should be significantly longer than
    #     # the fork's timeout_duration to ensure the fork's timeout logic fires.
    #     t_timeout.join(timeout=2) # Ample time for the 0.1s timeout to occur and thread to terminate
    #
    #     # Assert that the thread is no longer alive, meaning it completed its execution path (likely by raising an error)
    #     self.assertFalse(t_timeout.is_alive(), "Timeout thread should have terminated.")
    #
    #     # Assert that the log contains the timeout error message
    #     self.assertTrue(any("T_Timeout_Attempt raised RuntimeError: SyncSignalFork barrier timed out." in msg for msg in self.log),
    #                     f"Expected timeout error message not found in log. Log: {self.log}")
    #     # Assert that the fork itself is marked as timed out
    #     self.assertTrue(fork._timed_out, "Fork's internal timed_out flag should be True.")
    #
    #     # Clear the log for the next phase of the test
    #     self.log.clear()
    #
    #     # --- Second phase: Reset and verify successful manual release ---
    #     fork.reset()
    #     # After reset, _timed_out should be False again
    #     self.assertFalse(fork._timed_out, "Fork's internal timed_out flag should be False after reset.")
    #
    #
    #     # Spawn two threads to fill slots and block (manual release required)
    #     t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "M1_Thread"))
    #     t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "M2_Thread"))
    #     t1.start()
    #     t2.start()
    #
    #     # Give them some time to enter use_fork and block before manual release
    #     time.sleep(0.05)
    #     # Verify they haven't executed their callables yet
    #     self.assertNotIn("M1", self.log, "M1 callable should not have executed yet.")
    #     self.assertNotIn("M2", self.log, "M2 callable should not have executed yet.")
    #
    #     # Manual release the barrier
    #     fork.release()
    #
    #     # Wait for both threads to finish their execution
    #     t1.join(timeout=5)
    #     t2.join(timeout=5)
    #
    #     # Assert that both threads completed successfully
    #     self.assertFalse(t1.is_alive(), "Thread M1 did not complete after release.")
    #     self.assertFalse(t2.is_alive(), "Thread M2 did not complete after release.")
    #
    #     # Assert that the callables were executed exactly once each
    #     self.assertEqual(self.log.count("M1"), 1, "M1 callable should have executed once.")
    #     self.assertEqual(self.log.count("M2"), 1, "M2 callable should have executed once.")
    #     self.assertTrue(any("M1_Thread executed callable." in msg for msg in self.log), "Expected M1_Thread execution log missing.")
    #     self.assertTrue(any("M2_Thread executed callable." in msg for msg in self.log), "Expected M2_Thread execution log missing.")
    #
    #     # Dispose the fork for cleanup
    #     fork.dispose()

    def test_nested_forks(self):
        inner_calls = [(2, dummy_func_factory("INNER", self.log))]
        inner_fork = SyncSignalFork(1, inner_calls)


        def outer_job():
            inner_fork.use_fork()
            self.log.append("OUTER")

        outer_calls = [(2, outer_job)]
        outer_fork = SyncSignalFork(1, outer_calls)

        threads = [threading.Thread(target=outer_fork.use_fork) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        #for t in threads: self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("OUTER"), 2)
        self.assertEqual(self.log.count("INNER"), 2)
        outer_fork.dispose()  # Clean up
        inner_fork.dispose()  # Clean up


    def test_high_contention_small_slots(self):
        fork = SyncSignalFork(1, [(3, dummy_func_factory("HC", self.log))])
        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"C{i}", 0.0))
                   for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        self.assertEqual(self.log.count("HC"), 3)
        self.assertEqual(len([x for x in self.log if "RuntimeError" in x]), 17)
        fork.dispose()

    def test_reset_clears_controller_event_log(self):
        ctl = DummyController()
        fork = SyncSignalFork(1, [(1, dummy_func_factory("Z", self.log))],
                              controller=ctl)
        threading.Thread(target=thread_use_fork,
                         args=(fork, self.log, "Run1")).start()
        time.sleep(0.02)
        fork.reset()
        ctl.events.clear()
        threading.Thread(target=thread_use_fork,
                         args=(fork, self.log, "Run2")).start()
        time.sleep(0.02)
        self.assertTrue(any(e[1] == "THRESHOLD_MET" for e in ctl.events))
        fork.dispose()

    def test_interleaved_reset_and_use(self):
        fork = SyncSignalFork(1, [(1, dummy_func_factory("INT", self.log))])
        for _ in range(5):
            t = threading.Thread(target=thread_use_fork,
                                 args=(fork, self.log, "Loop"))
            t.start(); t.join(timeout=5)
            fork.reset()
        self.assertEqual(self.log.count("INT"), 5)
        fork.dispose()



    def test_selector_stride_variation_fair(self):
        callables = [(4, dummy_func_factory(f"S{i}", self.log)) for i in range(5)]
        fork = SyncSignalFork(5, callables, selector_step=7)
        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"Th{i}"))
                   for i in range(fork._route_count)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        counts = [self.log.count(f"S{i}") for i in range(5)]
        self.assertLessEqual(max(counts) - min(counts), 1)
        fork.dispose()

    # ------------------------------------------------------------------ #
    #  Dispose while waiting
    # ------------------------------------------------------------------ #
    def test_dispose_while_threads_wait(self):
        callables = [(2, dummy_func_factory("D", self.log))]
        fork = SyncSignalFork(
            number_of_forks=1,
            callables=callables,
            manual_release=True,
        )

        t_block = threading.Thread(
            target=thread_use_fork,
            args=(fork, self.log, "Blocker"),
        )
        t_block.start()
        time.sleep(0.02)  # ensure it's blocking
        fork.dispose()

        t_block.join(timeout=5)
        self.assertIn("Blocker raised RuntimeError", self.log[0])
        self.assertEqual(self.log.count("D"), 0)

    # ------------------------------------------------------------------ #
    #  Mis-configuration defensives
    # ------------------------------------------------------------------ #
    def test_invalid_init_params(self):
        with self.assertRaises(ValueError):
            SyncSignalFork(2, [(1, lambda: None)])

        with self.assertRaises(TypeError):
            SyncSignalFork(1, [(1.5, lambda: None)])

        async def coro(): pass
        with self.assertRaises(TypeError):
            SyncSignalFork(1, [(1, coro)])

        with self.assertRaises(ValueError):
            SyncSignalFork(1, [(1, lambda: None)], timeout_duration=-1.0)


if __name__ == '__main__':
    unittest.main()
