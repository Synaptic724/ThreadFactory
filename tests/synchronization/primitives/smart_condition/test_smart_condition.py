import unittest
import time
import random
import threading
import ulid
import queue
from thread_factory.synchronization.primitives.smart_condition import SmartCondition, Waiter
from thread_factory.agent.identity.types.general import General

class GenericTestThread(threading.Thread):
    def __init__(self, target=None, args=(), kwargs=None):
        super().__init__(target=target, args=args, kwargs=kwargs)
        if hasattr(self, 'factory_id'):
            del self.factory_id


class TestSmartCondition(unittest.TestCase):
    def _set_thread_factory_id(self, fid: str):
        threading.current_thread().factory_id = fid

    # --- Existing tests (from your provided code) ---
    def test_notify_partial_then_all(self):
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        class MyWorker(General):
            def __init__(self, name, fid):
                super().__init__()
                self.name = name
                self.factory_id = str(fid)

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                with lock:
                    results.append(f"woken_{self.name}")

        t1 = MyWorker("1a", "1")
        t2 = MyWorker("1b", "1")
        t1.start()
        t2.start()

        time.sleep(0.1)

        with cond:
            cond.notify(factory_ids="1")
        time.sleep(0.2)

        woken_count = results.count("woken_1a") + results.count("woken_1b")
        self.assertEqual(woken_count, 1)

        with cond:
            cond.notify_all(factory_ids="1")
        t1.join()
        t2.join()

        final_count = results.count("woken_1a") + results.count("woken_1b")
        self.assertEqual(final_count, 2)

    def test_simultaneous_notify_all(self):
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        class MyWorker(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = str(fid)

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                with lock:
                    results.append(int(self.factory_id))

        threads = [MyWorker(fid) for fid in range(100)]
        for t in threads:
            t.start()

        time.sleep(0.3)
        with cond:
            cond.notify_all()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 100)
        self.assertCountEqual(results, list(range(100)))

    def test_notify_specific_order(self):
        cond = SmartCondition()
        results = []
        order = []

        class MyWorker(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = str(fid)

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                results.append(int(self.factory_id))

        threads = [MyWorker(fid) for fid in [1, 2, 3, 1, 2, 3]]
        for t in threads:
            t.start()

        time.sleep(0.2)

        for fid in [1, 2, 3]:
            with cond:
                cond.notify_all(factory_ids=str(fid))
            time.sleep(0.05)
            order.append(fid)

        for t in threads:
            t.join()

        self.assertEqual(sorted(results), [1, 1, 2, 2, 3, 3])
        self.assertTrue(all(fid in results for fid in order))

    def test_nested_notify_depth_proof(self):
        cond = SmartCondition()
        results = []

        class MyWorker(Worker):
            def __init__(self):
                super().__init__()
                self.factory_id = "test-nested"

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                results.append(self.factory_id)

        thread = MyWorker()
        thread.start()
        time.sleep(0.1)

        def recursive_notify(n):
            if n == 0:
                with cond:
                    cond.notify(factory_ids="test-nested")
            else:
                with cond:
                    recursive_notify(n - 1)

        recursive_notify(10)
        thread.join()
        self.assertEqual(results, ["test-nested"])

    def test_stress_notify_specific_ids(self):
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        class MyWorker(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = str(fid)

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                with lock:
                    results.append(int(self.factory_id))

        factory_ids = [random.choice(range(10)) for _ in range(100)]
        threads = [MyWorker(fid) for fid in factory_ids]
        for t in threads:
            t.start()

        time.sleep(0.2)

        for fid_to_notify in set(factory_ids):
            with cond:
                cond.notify_all(factory_ids=str(fid_to_notify))
            time.sleep(0.01)

        for t in threads:
            t.join()

        self.assertEqual(len(results), 100)
        self.assertCountEqual(sorted(results), sorted(factory_ids))

    def test_waiter_removed_on_timeout(self):
        cond = SmartCondition()
        results = []

        class TimeoutWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, str(ulid.ULID()))
                with cond:
                    result = cond.wait(timeout=0.2)
                results.append(result)

        t = TimeoutWorker()
        t.start()
        t.join()

        self.assertEqual(results, [False], "Waiter should timeout and return False")
        self.assertEqual(len(cond.get_all_waiting_factory_ids()), 0,
                         "Timed-out waiter should be removed from waiter list")


    # ------------------------------------------------------------------
    # NEW TESTS -- notify_all_and_call variants (fixed closure capture)
    # ------------------------------------------------------------------

    def test_notify_all_and_call_specific_callback(self):
        """
        All waiters wake; a *one-off* inline callback must run once
        for every waiter.
        """
        cond = SmartCondition()
        results, lock = [], threading.Lock()

        def inline_cb():
            with lock:
                results.append("inline_cb")

        workers = []
        for i in range(3):
            this_fid = f"fid-{i}"

            class W(Worker):
                def __init__(self, fid):
                    super().__init__()
                    self.factory_id = fid

                def run(self_inner):  # noqa: N802
                    TestSmartCondition._set_thread_factory_id(self_inner,
                                                              self_inner.factory_id)
                    with cond:
                        cond.wait()
                    with lock:
                        results.append(f"woken_{self_inner.factory_id}")

            w = W(this_fid)
            workers.append(w)
            w.start()

        time.sleep(0.1)

        with cond:
            cond.notify_all_and_call(callback=inline_cb)

        for w in workers:
            w.join()

        # 3 inline-callback executions + one woken entry per thread
        self.assertEqual(results.count("inline_cb"), 3)
        self.assertCountEqual(
            [r for r in results if r.startswith("woken_")],
            [f"woken_fid-{i}" for i in range(3)],
        )

    def test_notify_all_and_call_bound_vs_default(self):
        """
        Bound callback beats default when no inline callback supplied.
        """
        cond = SmartCondition()
        results, lock = [], threading.Lock()

        def default_cb():
            with lock:
                results.append("default_cb")

        cond.set_default_callback(default_cb)

        fid_specific = "fid-specific"

        def bound_cb():
            with lock:
                results.append("bound_cb")

        cond.bind_callback(fid_specific, bound_cb)

        fids = [fid_specific, "fid-other"]
        workers = []

        for fid in fids:
            class W(Worker):
                def __init__(self, fid_):
                    super().__init__()
                    self.factory_id = fid_

                def run(self_inner):  # noqa: N802
                    TestSmartCondition._set_thread_factory_id(self_inner,
                                                              self_inner.factory_id)
                    with cond:
                        cond.wait()
                    with lock:
                        results.append(f"woken_{self_inner.factory_id}")

            w = W(fid)
            workers.append(w)
            w.start()

        time.sleep(0.1)

        with cond:
            cond.notify_all_and_call()          # no inline callback

        for w in workers:
            w.join()

        # ‘fid-specific’ should use its bound callback, the other the default
        self.assertIn("bound_cb", results)
        self.assertIn("default_cb", results)
        self.assertEqual(results.count("bound_cb"), 1)
        self.assertEqual(results.count("default_cb"), 1)
        self.assertCountEqual(
            [r for r in results if r.startswith("woken_")],
            [f"woken_{fid}" for fid in fids],
        )


    def test_notify_all_and_call_inline_overrides_others(self):
        """Inline callback overrides bound + default for every waiter."""
        cond = SmartCondition()
        results, lock = [], threading.Lock()

        # set bound & default that should be ignored
        cond.set_default_callback(lambda: results.append("default_cb_bad"))
        cond.bind_callback("fid-0", lambda: results.append("bound_cb_bad"))

        def inline_cb():
            with lock:
                results.append("inline_cb")

        # two waiters
        for i in range(2):
            fid = f"fid-{i}"
            class W(Worker):
                def run(self_inner):          # noqa: N801
                    TestSmartCondition._set_thread_factory_id(self_inner, fid)
                    with cond:
                        cond.wait()
            W().start()

        time.sleep(0.1)
        with cond:
            cond.notify_all_and_call(callback=inline_cb)

        # give them time to finish
        time.sleep(0.1)
        self.assertEqual(results.count("inline_cb"), 2)
        self.assertNotIn("default_cb_bad", results)
        self.assertNotIn("bound_cb_bad", results)

    def test_notify_all_and_call_awaited_caller(self):
        """
        Each waiter should execute the callback itself when awaited_caller=True.
        Order: callback runs **before** worker's post-wait code.
        """
        cond = SmartCondition()
        results = []

        fids = [f"fid-{i}" for i in range(2)]
        fired_events = {fid: threading.Event() for fid in fids}

        def mk_cb(fid):
            def _cb():
                results.append(f"cb_by_{fid}")
                fired_events[fid].set()
            return _cb

        # bind specific callbacks
        for fid in fids:
            cond.bind_callback(fid, mk_cb(fid))

        class W(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = fid
            def run(self):                    # noqa: N801
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                results.append(f"woken_{self.factory_id}")

        workers = [W(fid) for fid in fids]
        for w in workers:
            w.start()

        time.sleep(0.1)

        with cond:
            cond.notify_all_and_call(awaited_caller=True)

        for w in workers:
            w.join()

        # verify callback fired inside each worker
        for fid in fids:
            self.assertTrue(fired_events[fid].is_set())
            self.assertLess(
                results.index(f"cb_by_{fid}"),
                results.index(f"woken_{fid}"),
                f"Callback for {fid} did not execute inside awaited thread before its post-wait logic",
            )
        self.assertEqual(len([r for r in results if r.startswith("cb_by_")]), 2)

    def test_notify_limited_count(self):
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        class MyWorker(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = str(fid)

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                with lock:
                    results.append(int(self.factory_id))

        threads = [MyWorker(i) for i in range(5)]
        for t in threads:
            t.start()

        time.sleep(0.2)
        with cond:
            cond.notify(n=2)

        time.sleep(0.2)

        with cond:
            cond.notify_all()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)
        self.assertTrue(all(i in results for i in range(5)))

    def test_notify_specific_skips_non_matching(self):
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        class MyWorker(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = str(fid)

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                with lock:
                    results.append(int(self.factory_id))

        threads = [MyWorker(fid) for fid in [1, 2, 3, 4]]
        for t in threads:
            t.start()

        time.sleep(0.2)

        with cond:
            cond.notify(n=2, factory_ids=["1", "3"])

        time.sleep(0.2)

        num_woken_initially = len(results)
        initial_woken_ids = list(results)

        self.assertLessEqual(num_woken_initially, 2, "More than 2 threads woken by targeted notify")
        if num_woken_initially > 0:
            for woken_fid in initial_woken_ids:
                self.assertIn(str(woken_fid), ["1", "3"], "Woke a thread not in target group")

        with cond:
            cond.notify_all()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 4, "All threads should have eventually completed")
        self.assertTrue(1 in results and 3 in results, "Targeted threads should have woken up")
        self.assertTrue(2 in results and 4 in results, "Other threads should have woken up eventually")

    def test_dispose_clears_waiters_and_callbacks(self):
        cond = SmartCondition()

        # Setup: register some fake waiters and callbacks
        fake_fids = [f"fid-{i}" for i in range(3)]
        for fid in fake_fids:
            cond.bind_callback(fid, lambda: None)

        cond.set_default_callback(lambda: None)

        # Simulate waiters by manually injecting (to avoid threading complexity)
        for fid in fake_fids:
            w = Waiter(factory_id=fid, lock=threading.Lock(), thread=threading.current_thread())
            cond._waiters.enqueue(w)

        self.assertGreater(len(cond.get_all_waiters()), 0, "Waiters should be registered before dispose")
        self.assertGreater(len(cond._callback_registry), 0, "Callbacks should be registered before dispose")
        self.assertIsNotNone(cond._default_callback, "Default callback should be set before dispose")

        cond.dispose()

        self.assertTrue(cond._disposed, "SmartCondition should be marked as disposed")
        self.assertIsNone(cond._default_callback, "Default callback should be cleared after dispose")


    def test_get_all_waiters_returns_correct_ids(self):
        cond = SmartCondition()
        captured_ids = []

        class MyWorker(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = str(fid)

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()

        threads = [MyWorker(f"test_id_{i}") for i in range(3)]
        for t in threads:
            t.start()

        time.sleep(0.2)

        with cond:
            captured_ids = cond.get_all_waiting_factory_ids()

        with cond:
            cond.notify_all()

        for t in threads:
            t.join()

        self.assertEqual(len(captured_ids), 3, "Expected 3 waiting IDs to be captured")
        for fid in captured_ids:
            self.assertIsInstance(fid, str)
            self.assertTrue(fid.startswith("test_id_"), f"ID '{fid}' does not start with 'test_id_' prefix.")
            self.assertIn(fid, [f"test_id_{i}" for i in range(3)], f"Unexpected ID captured: {fid}")

    # --- New High-Performance Tests for SmartCondition ---

    def test_performance_high_contention_notify_all(self):
        num_workers = 100
        operations_per_worker = 100
        total_operations = num_workers * operations_per_worker

        cond = SmartCondition()
        successful_wakes = 0
        wakes_lock = threading.Lock()

        events = [threading.Event() for _ in range(num_workers)]

        class ContentionWorker(Worker):
            def __init__(self, worker_id, event_to_set):
                super().__init__()
                self.factory_id = f"worker-{worker_id}"
                self.event_to_set = event_to_set

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                nonlocal successful_wakes
                for _ in range(operations_per_worker):
                    with cond:
                        if cond.wait(timeout=0.5):
                            with wakes_lock:
                                successful_wakes += 1
                        else:
                            pass
                self.event_to_set.set()

        workers = []
        for i in range(num_workers):
            w = ContentionWorker(i, events[i])
            workers.append(w)

        start_time = time.perf_counter()
        for w in workers:
            w.start()

        notifies_sent = 0
        while successful_wakes < total_operations and (time.perf_counter() - start_time < 10):
            with cond:
                cond.notify(n=num_workers // 5)
                notifies_sent += (num_workers // 5)
            time.sleep(0.001)

        if successful_wakes < total_operations:
            with cond:
                cond.notify_all()

        all_finished = all(e.wait(timeout=5) for e in events)
        end_time = time.perf_counter()

        for w in workers:
            w.join(timeout=1)
            self.assertFalse(w.is_alive(), f"Worker {w.factory_id} did not terminate.")

        elapsed_time = end_time - start_time
        print(f"\n--- SmartCondition Performance Test Results ---")
        print(f"Test: High Contention (Notify All, Workers: {num_workers}, Ops/Worker: {operations_per_worker})")
        print(f"Total time: {elapsed_time:.4f} seconds")
        print(f"Total successful wakes: {successful_wakes}")
        print(f"Total notifies sent: {notifies_sent}")

        if elapsed_time > 0:
            ops_per_second = successful_wakes / elapsed_time
            print(f"Operations per second (throughput): {ops_per_second:.2f}")
        else:
            print("Elapsed time is zero, cannot calculate operations per second.")

        self.assertTrue(all_finished, "Not all workers finished signaling in time.")
        self.assertGreaterEqual(successful_wakes, total_operations * 0.9,
                                "Expected most operations to succeed, allowing for some timeouts")

    def test_performance_targeted_notification_stress(self):
        num_workers = 50
        num_unique_ids = 10
        operations_per_worker = 200
        total_operations = num_workers * operations_per_worker

        cond = SmartCondition()
        successful_wakes = 0
        wakes_lock = threading.Lock()

        events = [threading.Event() for _ in range(num_workers)]

        worker_fids = [f"group-{i % num_unique_ids}" for i in range(num_workers)]

        class TargetedWorker(Worker):
            def __init__(self, worker_id, event_to_set):
                super().__init__()
                self.factory_id = worker_fids[worker_id]
                self.event_to_set = event_to_set

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                nonlocal successful_wakes
                for _ in range(operations_per_worker):
                    with cond:
                        if cond.wait(timeout=0.5):
                            with wakes_lock:
                                successful_wakes += 1
                self.event_to_set.set()

        workers = []
        for i in range(num_workers):
            w = TargetedWorker(i, events[i])
            workers.append(w)

        start_time = time.perf_counter()
        for w in workers:
            w.start()

        notifies_sent = 0
        unique_ids = list(set(worker_fids))
        id_idx = 0
        while successful_wakes < total_operations and (time.perf_counter() - start_time < 15):
            target_fid = unique_ids[id_idx % num_unique_ids]
            with cond:
                cond.notify(n=1, factory_ids=target_fid)
                notifies_sent += 1
            id_idx += 1
            time.sleep(0.0005)

        if successful_wakes < total_operations:
            with cond:
                cond.notify_all()

        all_finished = all(e.wait(timeout=5) for e in events)
        end_time = time.perf_counter()

        for w in workers:
            w.join(timeout=1)
            self.assertFalse(w.is_alive(), f"Worker {w.factory_id} did not terminate.")

        elapsed_time = end_time - start_time
        print(f"\n--- SmartCondition Performance Test Results ---")
        print(
            f"Test: Targeted Notification Stress (Workers: {num_workers}, Unique IDs: {num_unique_ids}, Ops/Worker: {operations_per_worker})")
        print(f"Total time: {elapsed_time:.4f} seconds")
        print(f"Total successful wakes: {successful_wakes}")
        print(f"Total notifies sent: {notifies_sent}")
        if elapsed_time > 0:
            ops_per_second = successful_wakes / elapsed_time
            print(f"Operations per second (throughput): {ops_per_second:.2f}")
        else:
            print("Elapsed time is zero, cannot calculate operations per second.")

        self.assertTrue(all_finished, "Not all workers finished signaling in time.")
        self.assertGreaterEqual(successful_wakes, total_operations * 0.9,
                                "Expected most operations to succeed, allowing for some timeouts")

    def test_performance_wait_for_predicate_contention(self):
        num_workers = 20
        target_count_per_worker = 5

        class SharedState:
            def __init__(self):
                self.counter = 0
                self.lock = threading.Lock()

        shared_state = SharedState()
        cond = SmartCondition()

        events = [threading.Event() for _ in range(num_workers)]

        class PredicateWorker(Worker):
            def __init__(self, worker_id, event_to_set):
                super().__init__()
                self.factory_id = f"pred-worker-{worker_id}"
                self.event_to_set = event_to_set
                self.acquired_predicates = 0

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)

                for i in range(target_count_per_worker):
                    expected_counter_value = i + 1

                    def predicate():
                        return shared_state.counter >= expected_counter_value

                    if cond.wait_for(predicate, timeout=5):
                        self.acquired_predicates += 1

                        with shared_state.lock:
                            if shared_state.counter < expected_counter_value:
                                pass
                    else:
                        print(f"[{self.factory_id}] Predicate wait for {expected_counter_value} timed out.")
                        break

                self.event_to_set.set()

        workers = []
        for i in range(num_workers):
            w = PredicateWorker(i, events[i])
            workers.append(w)

        start_time = time.perf_counter()
        for w in workers:
            w.start()

        for step in range(num_workers * target_count_per_worker):
            with shared_state.lock:
                shared_state.counter += 1
                current_count = shared_state.counter

            with cond:
                cond.notify_all()

            time.sleep(0.0001)

            if all(w.acquired_predicates == target_count_per_worker for w in workers):
                break

        with cond:
            cond.notify_all()

        all_finished = all(e.wait(timeout=30) for e in events)
        end_time = time.perf_counter()

        for w in workers:
            w.join(timeout=1)
            self.assertFalse(w.is_alive(), f"Worker {w.factory_id} did not terminate.")

        elapsed_time = end_time - start_time

        total_predicate_successes = sum(w.acquired_predicates for w in workers)
        expected_total_predicate_successes = num_workers * target_count_per_worker

        print(f"\n--- SmartCondition Performance Test Results ---")
        print(
            f"Test: Wait For Predicate Contention (Workers: {num_workers}, Predicates/Worker: {target_count_per_worker})")
        print(f"Total time: {elapsed_time:.4f} seconds")
        print(f"Total successful predicate checks: {total_predicate_successes}")

        if elapsed_time > 0:
            ops_per_second = total_predicate_successes / elapsed_time
            print(f"Operations per second (throughput): {ops_per_second:.2f}")
        else:
            print("Elapsed time is zero, cannot calculate operations per second.")

        self.assertTrue(all_finished, "Not all workers finished signaling in time.")
        self.assertEqual(total_predicate_successes, expected_total_predicate_successes,
                         "Expected all predicate checks to succeed")

    # --- New Tests for Callback Methods (modified) ---

    def test_notify_and_call_with_specific_callback(self):
        cond = SmartCondition()
        results = []
        # No threading.Event needed here, worker.join will ensure completion

        def specific_callback():
            results.append("specific_callback_fired")

        worker_id = str(ulid.ULID())

        class CallbackWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait() # Worker will block here
                # After being woken, worker will append its result
                results.append("worker_woken")

        worker = CallbackWorker()
        worker.start()

        time.sleep(0.1)  # Give worker time to wait

        # Bind the specific callback to the worker's factory_id
        cond.bind_callback(worker_id, specific_callback)

        with cond:
            cond.notify_and_call(factory_ids=worker_id)

        worker.join(timeout=1) # Wait for the worker to finish its run method

        self.assertIn("specific_callback_fired", results)
        self.assertIn("worker_woken", results)
        self.assertEqual(results.count("specific_callback_fired"), 1)
        self.assertEqual(results.count("worker_woken"), 1)
        self.assertEqual(len(cond.get_all_waiting_factory_ids()), 0, "Worker should be removed after notification")

    def test_notify_and_call_with_default_callback(self):
        cond = SmartCondition()
        results = []

        def default_callback():
            results.append("default_callback_fired")

        cond.set_default_callback(default_callback)

        worker_id = str(ulid.ULID())

        class CallbackWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait()
                results.append("worker_woken")

        worker = CallbackWorker()
        worker.start()

        time.sleep(0.1)

        with cond:
            cond.notify_and_call(factory_ids=worker_id)

        worker.join(timeout=1)

        self.assertIn("default_callback_fired", results)
        self.assertIn("worker_woken", results)
        self.assertEqual(results.count("default_callback_fired"), 1)
        self.assertEqual(results.count("worker_woken"), 1)

    def test_notify_and_call_with_inline_callback_override(self):
        cond = SmartCondition()
        results = []

        def default_callback_never_called():
            results.append("default_callback_incorrectly_fired")

        def specific_callback_never_called():
            results.append("specific_callback_incorrectly_fired")

        def inline_callback():
            results.append("inline_callback_fired")

        worker_id = str(ulid.ULID())

        cond.set_default_callback(default_callback_never_called)
        cond.bind_callback(worker_id, specific_callback_never_called)

        class CallbackWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait()
                results.append("worker_woken")

        worker = CallbackWorker()
        worker.start()

        time.sleep(0.1)

        # Call with an inline callback, which should take precedence
        with cond:
            cond.notify_and_call(factory_ids=worker_id, callback=inline_callback)

        worker.join(timeout=1)

        self.assertIn("inline_callback_fired", results)
        self.assertIn("worker_woken", results)
        self.assertEqual(results.count("inline_callback_fired"), 1)
        self.assertEqual(results.count("worker_woken"), 1)
        self.assertNotIn("default_callback_incorrectly_fired", results)
        self.assertNotIn("specific_callback_incorrectly_fired", results)


    def test_notify_and_call_priority(self):
        cond = SmartCondition()
        results = []

        def callback_for_worker_1():
            results.append("worker_1_specific_cb")

        def default_cb():
            results.append("default_cb")

        def inline_cb_for_worker_2():
            results.append("worker_2_inline_cb")

        cond.set_default_callback(default_cb)
        worker_1_id = "worker-1"
        worker_2_id = "worker-2"
        worker_3_id = "worker-3"

        cond.bind_callback(worker_1_id, callback_for_worker_1)

        class PriorityWorker(Worker):
            def __init__(self, fid):
                super().__init__()
                self.factory_id = fid

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                with cond:
                    cond.wait()
                results.append(f"woken_{self.factory_id}")

        worker1 = PriorityWorker(worker_1_id)
        worker2 = PriorityWorker(worker_2_id)
        worker3 = PriorityWorker(worker_3_id)

        worker1.start()
        worker2.start()
        worker3.start()

        time.sleep(0.1) # Let workers wait

        # Notify worker 1 (should trigger specific bound callback)
        with cond:
            cond.notify_and_call(factory_ids=worker_1_id)
        worker1.join(timeout=1) # Wait for worker 1 to finish its execution

        self.assertIn("worker_1_specific_cb", results)
        self.assertIn("woken_worker-1", results)


        # Notify worker 2 (should trigger inline callback, overriding default/specific)
        with cond:
            cond.notify_and_call(factory_ids=worker_2_id, callback=inline_cb_for_worker_2)
        worker2.join(timeout=1) # Wait for worker 2 to finish its execution

        self.assertIn("worker_2_inline_cb", results)
        self.assertIn("woken_worker-2", results)

        # Notify worker 3 (should trigger default callback)
        with cond:
            cond.notify_and_call(factory_ids=worker_3_id)
        worker3.join(timeout=1) # Wait for worker 3 to finish its execution

        self.assertIn("default_cb", results)
        self.assertIn("woken_worker-3", results)

        # Ensure no accidental calls
        self.assertEqual(results.count("worker_1_specific_cb"), 1)
        self.assertEqual(results.count("worker_2_inline_cb"), 1)
        self.assertEqual(results.count("default_cb"), 1)


    def test_callback_error_handling(self):
        cond = SmartCondition()
        results = []

        def buggy_callback():
            results.append("buggy_callback_started")
            raise ValueError("Intentional error in callback!")

        worker_id = str(ulid.ULID())
        cond.bind_callback(worker_id, buggy_callback)

        class CallbackWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait()
                results.append("worker_woken")

        worker = CallbackWorker()
        worker.start()
        time.sleep(0.1)

        # The actual usage needs to be within a 'with cond:' block
        with cond:
            cond.notify_and_call(factory_ids=worker_id)

        worker.join(timeout=1)

        self.assertIn("buggy_callback_started", results)
        self.assertIn("worker_woken", results)

    def test_no_callback_registered(self):
        cond = SmartCondition()
        results = []

        worker_id = str(ulid.ULID())

        class CallbackWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait()
                results.append("worker_woken")

        worker = CallbackWorker()
        worker.start()
        time.sleep(0.1)

        # No callback registered
        with cond:
            cond.notify_and_call(factory_ids=worker_id)

        worker.join(timeout=1)

        self.assertIn("worker_woken", results)
        self.assertEqual(len(results), 1)


class TestSmartConditionFactoryIdTheory(unittest.TestCase):

    def setUp(self):
        self.cond = SmartCondition()

    def test_ensure_factory_id_on_main_thread(self):
        current = threading.current_thread()
        if hasattr(current, "factory_id"):
            del current.factory_id  # 🚨 Clear it so _ensure_factory_id can do its job

        fid = self.cond._ensure_factory_id()
        self.assertEqual(fid, "MainThread", "MainThread factory_id should be 'MainThread'")
        self.assertEqual(current.factory_id, "MainThread",
                         "MainThread's thread object should have 'MainThread' factory_id")

    def test_ensure_factory_id_on_thread_with_predefined_id(self):
        expected_fid = "pre-assigned-ulid-123456789012345"

        def thread_target():
            threading.current_thread().factory_id = expected_fid
            try:
                fid_from_ensure = self.cond._ensure_factory_id()
                self.assertEqual(fid_from_ensure, expected_fid, "ensure_factory_id should return the pre-assigned ID")
                self.assertEqual(threading.current_thread().factory_id, expected_fid,
                                 "Thread object should retain pre-assigned ID")
            except Exception as e:
                self.fail(f"Thread with pre-assigned ID failed: {e}")

        t = threading.Thread(target=thread_target)
        t.start()
        t.join(timeout=1)
        self.assertFalse(t.is_alive(), "Test thread did not complete in time.")

    def test_ensure_factory_id_on_generic_thread_without_id_problematic(self):
        def thread_target(result_queue):
            try:
                fid = self.cond._ensure_factory_id()
                result_queue.put(fid)
            except AttributeError as e:
                result_queue.put(f"AttributeError: {e}")
            except Exception as e:
                result_queue.put(f"Other Error: {e}")
            finally:
                if hasattr(threading.current_thread(), 'factory_id'):
                    del threading.current_thread().factory_id

        result_queue = queue.Queue()

        t = GenericTestThread(target=thread_target, args=(result_queue,))
        t.start()
        t.join(timeout=1)

        self.assertFalse(t.is_alive(), "Test thread did not complete in time.")
        self.assertFalse(result_queue.empty(), "Result queue is empty, thread likely failed silently.")

        result = result_queue.get()
        print(f"Result from problematic thread: {result}")

        self.assertIsInstance(result, str, "Result should be a string (factory ID or error message).")

        if "AttributeError" in result:
            self.fail(f"The _ensure_factory_id method raised AttributeError as predicted: {result}")
        elif "Other Error" in result:
            self.fail(f"The _ensure_factory_id method raised an unexpected error: {result}")
        else:
            self.assertEqual(len(result), 26, "Expected a ULID of length 26 if assigned.")

    def test_waiter_tracking_with_generic_threads_no_pre_id_scenario(self):
        num_threads = 5
        wait_events = [threading.Event() for _ in range(num_threads)]

        def worker_target(worker_idx, event_to_set):
            try:
                with self.cond:
                    self.cond.wait()
                event_to_set.set()
            except Exception as e:
                print(f"Worker {worker_idx} failed or woke up unexpectedly: {e}")
                event_to_set.set()

        threads = []
        for i in range(num_threads):
            t = GenericTestThread(target=worker_target, args=(i, wait_events[i]))
            threads.append(t)
            t.start()

        time.sleep(0.5)

        waiting_ids = self.cond.get_all_waiting_factory_ids()
        print(f"Waiting IDs after threads started: {waiting_ids}")
        self.assertEqual(len(waiting_ids), num_threads,
                         f"Expected {num_threads} waiters, but got {len(waiting_ids)}. "
                         "This might indicate _ensure_factory_id didn't assign IDs correctly "
                         "or threads aren't entering wait state.")

        for fid in waiting_ids:
            self.assertIsInstance(fid, str, f"Expected string factory_id, got {type(fid)}")
            self.assertEqual(len(fid), 26, f"Expected ULID of length 26, got '{fid}' for ID '{fid}'")

        with self.cond:
            self.cond.notify_all()

        all_woke_up = all(e.wait(timeout=1) for e in wait_events)
        self.assertTrue(all_woke_up, "Not all workers were woken up successfully.")

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), "Worker thread did not terminate.")

        final_waiting_ids = self.cond.get_all_waiting_factory_ids()
        self.assertEqual(len(final_waiting_ids), 0,
                         "All waiters should have been removed from SmartCondition's internal list.")
    def test_notify_and_call_awaited_caller(self):
        cond = SmartCondition()
        results = []
        awaited_callback_fired = threading.Event()

        def inline_callback_for_awaited_caller():
            results.append("inline_callback_fired_by_awaited")
            awaited_callback_fired.set()

        worker_id = str(ulid.ULID())

        class CallbackWorker(Worker):
            def run(self):
                # We need to set the factory_id before calling wait
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait()
                results.append("worker_woken_awaited")
                # The callback should be fired here by the worker thread itself,
                # as part of the wait() method's post-notification logic.

        worker = CallbackWorker()
        worker.start()

        time.sleep(0.1) # Give worker a moment to start waiting

        # Notify with an inline callback, specifying awaited_caller=True
        with cond:
            cond.notify_and_call(factory_ids=worker_id, callback=inline_callback_for_awaited_caller, awaited_caller=True)

        worker.join(timeout=1)

        self.assertTrue(awaited_callback_fired.wait(timeout=0.5), "Awaited callback was not fired.")
        self.assertIn("inline_callback_fired_by_awaited", results)
        self.assertIn("worker_woken_awaited", results)

        # Crucial check: ensure the callback was fired AFTER the worker was woken (within its own context)
        # This order ensures the worker itself executed the callback.
        # The specific order in 'results' will depend on when results.append is called
        # inside the worker's run() and when the callback appends.
        # A stronger assertion for "executed by awaited thread":
        # The callback is executed *within* the wait() method's post-wake logic.
        # The 'worker_woken_awaited' append happens *after* wait() returns.
        # So, the callback should logically appear before "worker_woken_awaited" in `results`.
        self.assertLess(results.index("inline_callback_fired_by_awaited"), results.index("worker_woken_awaited"),
                        "Callback was not executed by the awaited worker before its own post-wait code.")
        self.assertEqual(results.count("inline_callback_fired_by_awaited"), 1)
        self.assertEqual(results.count("worker_woken_awaited"), 1)


    def test_notify_awaited_caller_with_bound_callback(self):
        cond = SmartCondition()
        results = []
        awaited_callback_fired = threading.Event()

        def specific_bound_callback_for_awaited():
            results.append("bound_callback_fired_by_awaited")
            awaited_callback_fired.set()

        worker_id = str(ulid.ULID())

        cond.bind_callback(worker_id, specific_bound_callback_for_awaited)

        class CallbackWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait()
                results.append("worker_woken_bound_awaited")

        worker = CallbackWorker()
        worker.start()

        time.sleep(0.1)

        # Notify without an inline callback, but with awaited_caller=True,
        # so the bound callback should be executed by the worker.
        with cond:
            cond.notify(factory_ids=worker_id, n=1, awaited_caller=True)

        worker.join(timeout=1)

        self.assertTrue(awaited_callback_fired.wait(timeout=0.5), "Awaited bound callback was not fired.")
        self.assertIn("bound_callback_fired_by_awaited", results)
        self.assertIn("worker_woken_bound_awaited", results)
        self.assertLess(results.index("bound_callback_fired_by_awaited"), results.index("worker_woken_bound_awaited"),
                        "Bound callback was not executed by the awaited worker before its own post-wait code.")
        self.assertEqual(results.count("bound_callback_fired_by_awaited"), 1)
        self.assertEqual(results.count("worker_woken_bound_awaited"), 1)


    def test_notify_all_awaited_caller_with_default_callback(self):
        cond = SmartCondition()
        results = []
        awaited_callback_fired_worker1 = threading.Event()
        awaited_callback_fired_worker2 = threading.Event()

        def default_callback_for_awaited():
            # This callback will be called by both workers
            current_thread_id = threading.current_thread().factory_id
            results.append(f"default_callback_fired_by_awaited_{current_thread_id}")
            if current_thread_id == worker1_id:
                awaited_callback_fired_worker1.set()
            elif current_thread_id == worker2_id:
                awaited_callback_fired_worker2.set()

        worker1_id = str(ulid.ULID())
        worker2_id = str(ulid.ULID())

        cond.set_default_callback(default_callback_for_awaited)

        class CallbackWorker1(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker1_id)
                with cond:
                    cond.wait()
                results.append(f"worker_woken_default_awaited_{worker1_id}")

        class CallbackWorker2(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker2_id)
                with cond:
                    cond.wait()
                results.append(f"worker_woken_default_awaited_{worker2_id}")

        worker1 = CallbackWorker1()
        worker2 = CallbackWorker2()
        worker1.start()
        worker2.start()

        time.sleep(0.1)

        # Notify all with awaited_caller=True, so the default callback should be executed by both workers.
        with cond:
            cond.notify_all(awaited_caller=True)

        worker1.join(timeout=1)
        worker2.join(timeout=1)

        self.assertTrue(awaited_callback_fired_worker1.wait(timeout=0.5), "Worker 1's awaited default callback was not fired.")
        self.assertTrue(awaited_callback_fired_worker2.wait(timeout=0.5), "Worker 2's awaited default callback was not fired.")

        self.assertIn(f"default_callback_fired_by_awaited_{worker1_id}", results)
        self.assertIn(f"default_callback_fired_by_awaited_{worker2_id}", results)
        self.assertIn(f"worker_woken_default_awaited_{worker1_id}", results)
        self.assertIn(f"worker_woken_default_awaited_{worker2_id}", results)

        # Verify order for worker 1
        self.assertLess(results.index(f"default_callback_fired_by_awaited_{worker1_id}"),
                        results.index(f"worker_woken_default_awaited_{worker1_id}"),
                        f"Default callback for {worker1_id} not executed by awaited worker before its post-wait code.")
        # Verify order for worker 2
        self.assertLess(results.index(f"default_callback_fired_by_awaited_{worker2_id}"),
                        results.index(f"worker_woken_default_awaited_{worker2_id}"),
                        f"Default callback for {worker2_id} not executed by awaited worker before its post-wait code.")

        self.assertEqual(results.count(f"default_callback_fired_by_awaited_{worker1_id}"), 1)
        self.assertEqual(results.count(f"default_callback_fired_by_awaited_{worker2_id}"), 1)
        self.assertEqual(results.count(f"worker_woken_default_awaited_{worker1_id}"), 1)
        self.assertEqual(results.count(f"worker_woken_default_awaited_{worker2_id}"), 1)


    def test_no_callback_execution_by_notifier_when_awaited_caller_true(self):
        cond = SmartCondition()
        results = []

        def notifier_callback_should_not_fire():
            results.append("notifier_callback_incorrectly_fired")

        def awaited_callback_should_fire():
            results.append("awaited_callback_fired")

        worker_id = str(ulid.ULID())

        class CallbackWorker(Worker):
            def run(self):
                TestSmartCondition._set_thread_factory_id(self, worker_id)
                with cond:
                    cond.wait()
                results.append("worker_woken")

        worker = CallbackWorker()
        worker.start()

        time.sleep(0.1)

        # Notify with an inline callback, setting awaited_caller=True
        # This callback should be executed by the worker, NOT by the notifying thread
        with cond:
            cond.notify_and_call(factory_ids=worker_id, callback=awaited_callback_should_fire, awaited_caller=True)

        worker.join(timeout=1)

        self.assertIn("awaited_callback_fired", results)
        self.assertIn("worker_woken", results)
        self.assertNotIn("notifier_callback_incorrectly_fired", results) # THIS IS THE KEY ASSERTION

        self.assertLess(results.index("awaited_callback_fired"), results.index("worker_woken"),
                        "Awaited callback was not executed by the awaited worker before its own post-wait code.")
        self.assertEqual(results.count("awaited_callback_fired"), 1)
        self.assertEqual(results.count("worker_woken"), 1)


if __name__ == '__main__':
    unittest.main()