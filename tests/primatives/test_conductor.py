import unittest
import threading
import time
from typing import List, Any
from thread_factory.primitives.conductor import Conductor

class TestConductor(unittest.TestCase):
    # ==================================================================
    # Original Test Suite (Verified)
    # ==================================================================
    def test_task_execution_and_result_capture(self):
        conductor = Conductor(threshold=2, tasks=lambda: "done")
        def worker(): self.assertTrue(conductor.wait(timeout=1))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(conductor.results, ["done"])
        self.assertTrue(conductor.is_spent())

    def test_failing_task_captures_exception(self):
        class MyException(Exception): pass
        def failing_task(): raise MyException("failure")
        conductor = Conductor(threshold=1, tasks=failing_task)
        self.assertTrue(conductor.wait(timeout=1))
        self.assertEqual(len(conductor.exceptions), 1)
        self.assertIsInstance(conductor.exceptions[0], MyException)

    def test_reusable_mode_resets_correctly(self):
        counter = [0]
        def task(): counter[0] += 1
        conductor = Conductor(threshold=2, tasks=task, reusable=True)
        def run_cycle():
            threads = [threading.Thread(target=lambda: conductor.wait(timeout=1)) for _ in range(2)]
            for t in threads: t.start()
            for t in threads: t.join()
        run_cycle()
        self.assertEqual(counter[0], 1)
        run_cycle()
        self.assertEqual(counter[0], 2)

    def test_manual_release(self):
        conductor = Conductor(threshold=2, tasks=lambda: "task_done", manual_release=True)
        worker_finished = threading.Event()
        def worker():
            conductor.wait(timeout=1)
            worker_finished.set()
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads: t.start()
        time.sleep(0.1)
        self.assertEqual(conductor.results, ["task_done"])
        self.assertFalse(worker_finished.is_set())
        conductor.release()
        self.assertTrue(worker_finished.wait(timeout=1))
        for t in threads: t.join()

    def test_timeout_and_break(self):
        conductor = Conductor(threshold=3, timeout=0.1)
        results: List[bool] = []
        def worker(): results.append(conductor.wait())
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(results, [False, False])
        self.assertTrue(conductor._broken)

    def test_initialization_rejects_coroutines(self):
        async def my_coro(): pass
        with self.assertRaises(TypeError): Conductor(threshold=1, tasks=my_coro)

    def test_dispose_releases_waiting_threads(self):
        conductor = Conductor(threshold=2)
        results = []
        def worker(): results.append(conductor.wait(timeout=1))
        t1 = threading.Thread(target=worker)
        t1.start()
        time.sleep(0.1)
        conductor.dispose()
        self.assertTrue(conductor.disposed)
        t1.join()
        self.assertEqual(results, [False])

    # ==================================================================
    # 10 Additional Tests (Now with fixes)
    # ==================================================================

    def test_timeout_raises_exception(self):
        conductor = Conductor(threshold=2, timeout=0.1, raise_on_timeout=True)
        with self.assertRaises(TimeoutError):
            conductor.wait()

    def test_notify_all_override_releases_threads(self):
        conductor = Conductor(threshold=5)
        results = []
        def worker(): results.append(conductor.wait(timeout=1))
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads: t.start()
        time.sleep(0.1)
        self.assertEqual(len(results), 0)
        conductor.notify_all_override()
        for t in threads: t.join()
        self.assertEqual(results, [False, False, False])

    def test_notify_all_override_in_reusable_mode(self):
        conductor = Conductor(threshold=5, reusable=True)
        results_cycle1 = []
        def worker1(): results_cycle1.append(conductor.wait(timeout=1))
        threads1 = [threading.Thread(target=worker1) for _ in range(2)]
        for t in threads1: t.start()
        conductor.notify_all_override()
        for t in threads1: t.join()
        self.assertEqual(results_cycle1, [False, False])
        results_cycle2 = []
        def worker2(): results_cycle2.append(conductor.wait(timeout=1))
        threads2 = [threading.Thread(target=worker2) for _ in range(5)]
        for t in threads2: t.start()
        for t in threads2: t.join()
        self.assertEqual(results_cycle2, [True, True, True, True, True])

    def test_wait_on_already_spent_conductor(self):
        conductor = Conductor(threshold=1)
        self.assertTrue(conductor.wait(timeout=1))
        self.assertTrue(conductor.is_spent())
        self.assertTrue(conductor.wait(timeout=0))

    def test_is_spent_property_lifecycle(self):
        conductor = Conductor(threshold=1, reusable=False)
        self.assertFalse(conductor.is_spent())
        conductor.wait(timeout=1)
        self.assertTrue(conductor.is_spent())
        reusable_conductor = Conductor(threshold=1, reusable=True)
        self.assertFalse(reusable_conductor.is_spent())
        reusable_conductor.wait(timeout=1)
        self.assertFalse(reusable_conductor.is_spent())

    def test_no_tasks_provided(self):
        conductor = Conductor(threshold=2, tasks=None)
        def worker(): self.assertTrue(conductor.wait(timeout=1))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(conductor.results, [])
        self.assertTrue(conductor.is_spent())

    def test_multiple_tasks_with_mixed_outcomes(self):
        class MixedOutcomeException(Exception): pass
        def task_that_raises(): raise MixedOutcomeException()
        tasks = [ lambda: "Success 1", lambda: 1/0, lambda: "Success 2", task_that_raises]
        conductor = Conductor(threshold=1, tasks=tasks)
        conductor.wait()
        self.assertCountEqual(conductor.results, ["Success 1", "Success 2"])
        self.assertEqual(len(conductor.exceptions), 2)
        self.assertTrue(any(isinstance(e, ZeroDivisionError) for e in conductor.exceptions))
        self.assertTrue(any(isinstance(e, MixedOutcomeException) for e in conductor.exceptions))

    def test_manual_release_behavior_before_threshold(self):
        conductor = Conductor(threshold=3, manual_release=True)
        worker_finished = threading.Event()
        def worker(): conductor.wait(timeout=0.2); worker_finished.set()
        t1 = threading.Thread(target=worker)
        t1.start()
        conductor.release()
        self.assertTrue(worker_finished.wait(timeout=1), "Worker should have timed out, proving release() had no effect")
        t1.join()

    def test_dispose_idempotency(self):
        conductor = Conductor(threshold=1)
        try:
            conductor.dispose()
            conductor.dispose()
        except Exception as e:
            self.fail(f"dispose() raised an unexpected exception: {e}")
        self.assertTrue(conductor.disposed)

    def test_wait_with_zero_timeout(self):
        conductor = Conductor(threshold=2)
        start_time = time.monotonic()
        released = conductor.wait(timeout=0)
        duration = time.monotonic() - start_time
        self.assertFalse(released)
        self.assertLess(duration, 0.05)

if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)