import unittest
import threading
import time
from typing import List
from thread_factory import SyncFork, Pack


# --- Helper Functions for Testing ---

def dummy_func_factory(name: str, log: List[str], delay: float = 0):
    """
    Creates a simple callable function that logs its name and optionally waits.
    """
    lock = threading.Lock()

    def func():
        with lock:
            if delay > 0:
                time.sleep(delay)
            log.append(name)

    return func


def thread_use_fork(fork: 'SyncFork', log: List[str], thread_name: str, sleep_before_use: float = 0.005):
    """
    Target function for threads to call use_fork().
    Includes a try-except block to catch the RuntimeError.
    """
    try:
        time.sleep(sleep_before_use)  # Give a small delay to ensure threads start
        fork.use_fork()
        log.append(f"{thread_name} executed callable.")
    except RuntimeError as e:
        log.append(f"{thread_name} raised RuntimeError: {e}")
    except Exception as e:
        log.append(f"{thread_name} raised unexpected error: {e}")


# --- Unit Test Class ---

class TestSyncFork(unittest.TestCase):

    def setUp(self):
        """Reset the logs before each test."""
        self.log = []

    def tearDown(self):
        # Clean up any SyncFork instances to avoid resource leaks in tests
        # This assumes test methods create their own 'fork' instance.
        # If a test method stores `self.fork`, it should be disposed here.
        pass

    # --- Existing Tests (Adjusted for removed 'reusable' and updated error messages) ---

    def test_massive_concurrency(self):
        callables = [(1, dummy_func_factory("A", self.log)) for _ in range(50)]
        fork = SyncFork(number_of_forks=50, callables=callables)
        total_cap = fork._route_count

        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}", 0.001)) for i in
                   range(total_cap)]  # Added small sleep
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive(), f"Thread {t.name} did not complete in time.")

        self.assertEqual(self.log.count("A"), 50)
        self.assertEqual(len([s for s in self.log if "executed callable" in s]), total_cap)
        fork.dispose()  # Clean up

    def test_selector_wraparound(self):
        callables = [(4, dummy_func_factory(f"U{i}", self.log)) for i in range(3)]
        fork = SyncFork(3, callables, selector_step=10)

        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"T{i}"))
                   for i in range(fork._route_count)]

        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        for t in threads:
            self.assertFalse(t.is_alive(), f"Thread {t.name} did not complete in time.")

        for i in range(3):
            self.assertEqual(self.log.count(f"U{i}"), 4)
        fork.dispose()  # Clean up

    def test_barrier_release_at_capacity(self):
        callables_list = [
            (3, dummy_func_factory("Worker_A", self.log)),
            (2, dummy_func_factory("Worker_B", self.log))
        ]

        fork = SyncFork(number_of_forks=2, callables=callables_list)
        total_capacity = sum(cap for cap, _ in callables_list)

        self.assertEqual(fork._route_count, total_capacity)

        num_threads = total_capacity
        threads = [
            threading.Thread(target=thread_use_fork, args=(fork, self.log, f"Thread-{i}"))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=5)  # Ensure all threads complete
            self.assertFalse(t.is_alive(), f"Thread {t.name} did not complete in time.")

        self.assertLessEqual(len([s for s in self.log if "Worker" in s]), total_capacity)  # Callable execs
        self.assertEqual(fork._blocked_thread_count, num_threads)
        self.assertTrue(fork._threading_event.is_set())

        self.assertEqual(len([s for s in self.log if "executed callable." in s]),
                         num_threads)  # Threads reporting completion

        worker_a_count = self.log.count("Worker_A")
        worker_b_count = self.log.count("Worker_B")
        self.assertEqual(worker_a_count, 3)
        self.assertEqual(worker_b_count, 2)
        self.assertEqual(worker_a_count + worker_b_count, total_capacity)

        self.assertTrue(fork._threading_event.is_set())
        for unit in fork._list_of_forks:
            self.assertTrue(unit.gate)
            self.assertEqual(unit.gate_uses, unit.usage_cap)
        fork.dispose()  # Clean up

    def test_callable_exception_does_not_deadlock(self):
        def boom():
            self.log.append("BOOM")
            raise ValueError("kaboom")

        callables = [(1, boom), (1, dummy_func_factory("SAFE", self.log))]
        fork = SyncFork(2, callables)

        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "T1"))
        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "T2"))
        t1.start();
        t2.start();
        t1.join(timeout=5);
        t2.join(timeout=5)
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())

        self.assertIn("BOOM", self.log)
        self.assertIn("SAFE", self.log)
        fork.dispose()  # Clean up

    def test_rapid_reset_cycles(self):
        callables = [(1, dummy_func_factory("C", self.log))]
        fork = SyncFork(1, callables)

        for _ in range(100):
            t = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Cycler"))
            t.start()
            t.join(timeout=5)
            self.assertFalse(t.is_alive())
            fork.reset()

        self.assertEqual(self.log.count("C"), 100)
        fork.dispose()  # Clean up

    def test_nested_forks(self):
        inner_calls = [(2, Pack(dummy_func_factory("INNER", self.log)))]
        inner_fork = SyncFork(1, inner_calls)

        def outer_job():
            inner_fork.use_fork()
            self.log.append("OUTER")

        outer_calls = [(2, Pack(outer_job))]
        outer_fork = SyncFork(1, outer_calls)

        threads = [threading.Thread(target=outer_fork.use_fork) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        #for t in threads: self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("OUTER"), 2)
        self.assertEqual(self.log.count("INNER"), 2)
        outer_fork.dispose()  # Clean up
        inner_fork.dispose()  # Clean up

    def test_fairness_variance(self):
        callables = [(5, dummy_func_factory(f"F{i}", self.log)) for i in range(4)]
        fork = SyncFork(4, callables, selector_step=3)

        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"T{i}"))
                   for i in range(fork._route_count)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        for t in threads: self.assertFalse(t.is_alive())

        counts = [self.log.count(f"F{i}") for i in range(4)]
        self.assertTrue(max(counts) - min(counts) <= 1,
                        msg=f"Unfair distribution: {counts}")
        fork.dispose()  # Clean up

    # Corrected the error message for exhaustion and behavior
    def test_fork_exhaustion_after_one_cycle(self):
        callables_list = [(1, dummy_func_factory("Single_Use", self.log))]
        fork = SyncFork(number_of_forks=1, callables=callables_list)

        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Thread-1"))
        t1.start()
        t1.join(timeout=5)
        self.assertFalse(t1.is_alive())

        self.assertIn("Thread-1 executed callable.", self.log)
        self.assertIn("Single_Use", self.log)
        self.assertEqual(fork._blocked_thread_count, 1)

        t2 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Thread-2"))
        t2.start()
        t2.join(timeout=5)
        self.assertFalse(t2.is_alive())

        self.assertIn("Thread-2 raised RuntimeError: All forks are at capacity or barrier has already closed.",
                      self.log)
        self.assertEqual(self.log.count("Single_Use"), 1)
        fork.dispose()  # Clean up

    def test_reusable_fork_with_reset_without_reusable_param(self):
        callables_list = [(2, dummy_func_factory("A", self.log)), (2, dummy_func_factory("B", self.log))]
        fork = SyncFork(number_of_forks=2, callables=callables_list)

        threads1 = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"R1-T{i}")) for i in range(4)]
        for t in threads1: t.start()
        for t in threads1: t.join(timeout=5)
        for t in threads1: self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("A"), 2)
        self.assertEqual(self.log.count("B"), 2)
        self.assertTrue(fork._forks_closed)
        self.assertTrue(fork._threading_event.is_set())

        self.log.clear()  # Clear for second round

        fork.reset()

        self.assertFalse(fork._forks_closed)
        self.assertEqual(fork._blocked_thread_count, 0)
        self.assertFalse(fork._threading_event.is_set())
        for unit in fork._list_of_forks:
            self.assertFalse(unit.gate)
            self.assertEqual(unit.gate_uses, 0)

        threads2 = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"R2-T{i}")) for i in range(4)]
        for t in threads2: t.start()
        for t in threads2: t.join(timeout=5)
        for t in threads2: self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("A"), 2)
        self.assertEqual(self.log.count("B"), 2)
        self.assertEqual(len([s for s in self.log if "executed callable" in s]), 4)
        fork.dispose()  # Clean up

    def test_single_fork_contention_barrier(self):
        callable_name = "Single_Fork"
        callables_list = [(10, dummy_func_factory(callable_name, self.log))]
        fork = SyncFork(number_of_forks=1, callables=callables_list)

        num_threads = 10
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count(callable_name), 10)
        self.assertEqual(len([s for s in self.log if "executed callable" in s]), num_threads)
        fork.dispose()  # Clean up

    def test_selector_step_distribution(self):
        callables_list = [(3, dummy_func_factory("F0", self.log)), (3, dummy_func_factory("F1", self.log)),
                          (3, dummy_func_factory("F2", self.log))]
        fork = SyncFork(number_of_forks=3, callables=callables_list, selector_step=1)

        num_threads = 9
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("F0"), 3)
        self.assertEqual(self.log.count("F1"), 3)
        self.assertEqual(self.log.count("F2"), 3)
        self.assertEqual(len([s for s in self.log if "executed callable" in s]), num_threads)
        fork.dispose()  # Clean up

    def test_selector_step_with_custom_stride(self):
        callables_list = [(2, dummy_func_factory("F0", self.log)), (2, dummy_func_factory("F1", self.log)),
                          (2, dummy_func_factory("F2", self.log)), (2, dummy_func_factory("F3", self.log))]
        fork = SyncFork(number_of_forks=4, callables=callables_list, selector_step=2)

        num_threads = 8
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("F0"), 2)
        self.assertEqual(self.log.count("F1"), 2)
        self.assertEqual(self.log.count("F2"), 2)
        self.assertEqual(self.log.count("F3"), 2)
        self.assertEqual(len([s for s in self.log if "executed callable" in s]), num_threads)
        fork.dispose()  # Clean up

    def test_race_condition_contention(self):
        callable_name = "Contended_Fork"
        callables_list = [(5, dummy_func_factory(callable_name, self.log))]
        fork = SyncFork(number_of_forks=1, callables=callables_list)

        num_threads = 20
        threads = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(num_threads)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        execution_count = self.log.count(callable_name)
        self.assertEqual(execution_count, 5)

        error_log_count = len([item for item in self.log if "raised RuntimeError" in item])
        self.assertEqual(error_log_count, num_threads - 5)

        self.assertEqual(fork._blocked_thread_count, 5)
        self.assertEqual(fork._list_of_forks[0].gate_uses, 5)
        fork.dispose()  # Clean up

    def test_improper_initialization(self):
        with self.assertRaises(ValueError):
            SyncFork(number_of_forks=2, callables=[(1, lambda: None)])

        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[lambda: None])

        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[(1.5, lambda: None)])

        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[(1, "not_callable")])

        async def async_callable(): pass

        with self.assertRaises(TypeError):
            SyncFork(number_of_forks=1, callables=[(1, async_callable)])

        with self.assertRaises(ValueError):
            SyncFork(number_of_forks=1, callables=[(1, lambda: None)], timeout_duration=-1)
        with self.assertRaises(ValueError):
            SyncFork(number_of_forks=1, callables=[(1, lambda: None)], timeout_duration="abc")

    # --- New Tests for Scout Integration and Timeout ---

    def test_barrier_timeout(self):
        # Define 2 slots, but only send 1 thread, ensuring a timeout
        callables_list = [(1, dummy_func_factory("Worker_A", self.log)),
                          (1, dummy_func_factory("Worker_B", self.log))]

        # Configure a short timeout
        fork = SyncFork(number_of_forks=2, callables=callables_list, timeout_duration=0.1)
        total_capacity = fork._route_count  # 2

        num_threads = 1  # Intentionally less than total_capacity
        threads = [
            threading.Thread(target=thread_use_fork, args=(fork, self.log, f"Thread-{i}", 0.001))  # Small sleep
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()

        # Give enough time for the timeout to occur
        time.sleep(0.2)

        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        # All threads (in this case, 1 thread) should raise a timeout error
        self.assertEqual(len(self.log), num_threads)  # Only error messages
        self.assertTrue(all("raised RuntimeError: SyncFork barrier timed out." in s for s in self.log))

        # No callables should have been executed
        self.assertEqual(self.log.count("Worker_A"), 0)
        self.assertEqual(self.log.count("Worker_B"), 0)

        # Verify internal flags
        self.assertTrue(fork._timed_out)
        self.assertTrue(fork._forks_closed)
        self.assertTrue(fork._threading_event.is_set())  # Event set by timeout handler
        fork.dispose()  # Clean up

    def test_barrier_success_with_timeout_configured(self):
        # Configure a timeout, but ensure barrier is met before it expires
        callables_list = [(1, dummy_func_factory("Worker_X", self.log)),
                          (1, dummy_func_factory("Worker_Y", self.log))]

        # Timeout is long enough to not be hit, but configured
        fork = SyncFork(number_of_forks=2, callables=callables_list, timeout_duration=1.0)
        total_capacity = fork._route_count  # 2

        num_threads = total_capacity  # Send enough threads to meet barrier
        threads = [
            threading.Thread(target=thread_use_fork, args=(fork, self.log, f"Thread-{i}", 0.001))  # Small sleep
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()

        # Give threads a moment to enter the fork and for the barrier to be met
        time.sleep(0.5)

        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        # All callables should have executed
        self.assertEqual(self.log.count("Worker_X"), 1)
        self.assertEqual(self.log.count("Worker_Y"), 1)
        self.assertEqual(len([s for s in self.log if "executed callable." in s]), num_threads)

        # Timeout flag should NOT be set
        self.assertFalse(fork._timed_out)
        self.assertTrue(fork._forks_closed)  # Fork should still close after meeting barrier
        self.assertTrue(fork._threading_event.is_set())
        fork.dispose()  # Clean up

    def test_dispose_syncfork(self):
        callables_list = [(1, dummy_func_factory("A", self.log))]
        # Use a timeout duration to ensure Scout is initialized by use_fork
        fork = SyncFork(number_of_forks=1, callables=callables_list, timeout_duration=0.1)

        self.assertFalse(fork._disposed)

        # Trigger Scout initialization by getting the first thread in.
        # This thread will block in scout.monitor() if timeout_duration is active.
        t_init_scout = threading.Thread(target=thread_use_fork,
                                        args=(fork, self.log, "ScoutInitThread", 0.001))  # Small sleep
        t_init_scout.start()

        # Give a moment for Scout to be initialized and its monitor method entered
        time.sleep(0.01)  # Increased sleep slightly

        # At this point, fork._scout should exist, and it should be active in monitor()
        self.assertIsNotNone(fork._scout)
        self.assertTrue(fork._scout.is_active())
        self.assertFalse(fork._scout._disposed)  # Scout should not be disposed yet

        # Capture the Scout instance before SyncFork disposes it
        captured_scout = fork._scout

        fork.dispose()  # Dispose the SyncFork, which should also dispose the Scout
        self.assertTrue(fork._disposed)

        # Verify the captured Scout instance is now disposed
        self.assertTrue(captured_scout._disposed)
        # And that SyncFork's reference to it is cleared
        self.assertIsNone(fork._scout)

        # Attempt to use SyncFork after dispose
        t_after_dispose = threading.Thread(target=thread_use_fork, args=(fork, self.log, "DisposedThread"))
        t_after_dispose.start()
        t_after_dispose.join(timeout=5)
        self.assertFalse(t_after_dispose.is_alive())

        self.assertIn("DisposedThread raised RuntimeError: Cannot use a disposed SyncFork.", self.log)
        # We might have a timeout error from the scout init thread if it timed out before dispose,
        # but no 'A' should be in the log from the callable.
        self.assertEqual(self.log.count("A"), 0)

        # Attempt to reset after dispose
        with self.assertRaises(RuntimeError):
            fork.reset()

        t_init_scout.join(timeout=5)  # Join the thread that initiated the scout.
        self.assertFalse(t_init_scout.is_alive())


    # ------------------------------------------------------------------ #
    #                    ✨  Additional Edge-Case Tests  ✨               #
    # ------------------------------------------------------------------ #

    def test_multiple_timeout_reset_cycles(self):
        """
        Reproduce a timeout → reset → reuse loop several times to be sure
        Scout and SyncFork state never leak across cycles.
        """
        fork = SyncFork(
            number_of_forks=2,
            callables=[(1, dummy_func_factory("A", self.log)),
                       (1, dummy_func_factory("B", self.log))],
            timeout_duration=0.05   # intentionally short
        )

        for cycle in range(3):
            # Fire only one thread so the barrier must time-out
            t = threading.Thread(target=thread_use_fork,
                                 args=(fork, self.log, f"C{cycle}", 0.001))
            t.start(); t.join(timeout=5); self.assertFalse(t.is_alive())

            # Every cycle should produce *exactly one* timeout log line
            self.assertTrue(any("barrier timed out" in s for s in self.log),
                            f"Cycle {cycle} produced no timeout log.")
            self.assertEqual(self.log.count("A"), 0)
            self.assertEqual(self.log.count("B"), 0)

            # Reset and verify clean state
            fork.reset()
            self.assertFalse(fork._timed_out)
            self.assertFalse(fork._forks_closed)
            self.assertFalse(fork._threading_event.is_set())

            self.log.clear()

        fork.dispose()

    def test_threads_arriving_after_timeout(self):
        """
        After a timeout fires, any *late* threads should wake immediately
        and raise RuntimeError — never executing a callable.
        """
        callables = [(1, dummy_func_factory("LATE_A", self.log)),
                     (1, dummy_func_factory("LATE_B", self.log))]
        fork = SyncFork(2, callables, timeout_duration=0.05)

        # Launch only one thread -> will cause timeout
        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Early", 0.001))
        t1.start(); t1.join(timeout=5)

        # Give timeout time to propagate
        time.sleep(0.08)

        # Now launch *extra* threads after timeout
        late_threads = [threading.Thread(target=thread_use_fork,
                                         args=(fork, self.log, f"Late-{i}", 0.0))
                        for i in range(3)]
        for t in late_threads: t.start()
        for t in late_threads: t.join(timeout=5)

        self.assertTrue(all("barrier timed out" in s for s in self.log))
        self.assertEqual(self.log.count("LATE_A"), 0)
        self.assertEqual(self.log.count("LATE_B"), 0)
        fork.dispose()

    def test_dispose_while_threads_wait(self):
        """
        Dispose the SyncFork while threads are blocked at the barrier and
        verify all threads exit quickly with RuntimeError.
        """
        callables = [(2, dummy_func_factory("D", self.log))]
        fork = SyncFork(1, callables, timeout_duration=None)

        # Start just one of two required threads -> it will block
        t_blocked = threading.Thread(target=thread_use_fork, args=(fork, self.log, "Blocked"))
        t_blocked.start()
        time.sleep(0.02)  # ensure it's inside use_fork() waiting

        fork.dispose()    # nuke while barrier isn't full

        t_blocked.join(timeout=5)
        self.assertFalse(t_blocked.is_alive())
        self.assertIn("Blocked raised RuntimeError: Cannot use a disposed SyncFork.", self.log)
        self.assertEqual(self.log.count("D"), 0)

    def test_near_timeout_race_success(self):
        """
        Start second thread just before the timeout should fire; barrier
        must succeed (no timeout triggered).
        """
        callables = [(1, dummy_func_factory("Race_A", self.log)),
                     (1, dummy_func_factory("Race_B", self.log))]
        fork = SyncFork(2, callables, timeout_duration=0.1)

        # First thread starts Scout at t≈0
        t_first = threading.Thread(target=thread_use_fork,
                                   args=(fork, self.log, "R1", 0.001))
        t_first.start()

        # Second thread sneaks in at t≈0.09 (just shy of the timeout)
        time.sleep(0.09)
        t_second = threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, "R2", 0.0))
        t_second.start()

        for t in (t_first, t_second):
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(self.log.count("Race_A"), 1)
        self.assertEqual(self.log.count("Race_B"), 1)
        # No timeout messages should exist
        self.assertFalse(any("timed out" in s for s in self.log))
        fork.dispose()

    def test_non_uniform_capacity_distribution(self):
        """
        Very unbalanced capacities: ensure selector still finds available
        units and executes them exactly as many times as allowed.
        """
        callables = [(1, dummy_func_factory("Tiny", self.log)),
                     (10, dummy_func_factory("Huge", self.log))]
        fork = SyncFork(2, callables, selector_step=3)

        num_threads = 11
        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"NU-{i}", 0.0))
                   for i in range(num_threads)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)

        self.assertEqual(self.log.count("Tiny"), 1)
        self.assertEqual(self.log.count("Huge"), 10)
        self.assertEqual(len([s for s in self.log if "executed callable" in s]), 11)
        fork.dispose()

    def test_reset_clears_timeout_state(self):
        # Configured for 2 slots, so sending 1 thread will cause timeout
        callables_list = [(1, dummy_func_factory("A", self.log)), (1, dummy_func_factory("B", self.log))]
        fork = SyncFork(number_of_forks=2, callables=callables_list, timeout_duration=0.1)

        # First cycle: force timeout by sending only one thread when route_count is 2
        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "T1", 0.001))
        t1.start()
        t1.join(timeout=5)
        self.assertFalse(t1.is_alive())

        self.assertIn("T1 raised RuntimeError: SyncFork barrier timed out.", self.log)
        self.assertTrue(fork._timed_out)
        self.assertTrue(fork._forks_closed)
        self.assertIsNotNone(fork._scout)  # Scout should have been initialized
        self.assertTrue(fork._scout.is_latched())  # Scout should be latched after timeout

        self.log.clear()  # Clear logs for next cycle

        # Reset the fork
        fork.reset()
        self.assertFalse(fork._timed_out)  # Timeout state must be cleared
        self.assertFalse(fork._forks_closed)  # Fork must be open again
        self.assertFalse(fork._threading_event.is_set())  # Event must be clear
        self.assertFalse(fork._scout.is_latched())  # Scout must be reset too

        # Second cycle: normal success (send enough threads for barrier to complete)
        num_threads_for_success = fork._route_count
        threads_for_success = [
            threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T_Success-{i}", 0.001))
            for i in range(num_threads_for_success)
        ]

        for t in threads_for_success:
            t.start()

        # Give threads a moment to enter the fork and for the barrier to be met
        time.sleep(0.05)

        for t in threads_for_success:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertIn("T_Success-0 executed callable.", self.log)  # At least one success
        self.assertEqual(self.log.count("A"), 1)  # Callable A should execute
        self.assertEqual(self.log.count("B"), 1)  # Callable B should execute
        self.assertFalse(fork._timed_out)  # No timeout this time
        self.assertTrue(fork._forks_closed)  # Should be closed due to natural completion
        self.assertTrue(fork._threading_event.is_set())  # Event should be set
        fork.dispose()  # Clean up

if __name__ == '__main__':
    unittest.main()