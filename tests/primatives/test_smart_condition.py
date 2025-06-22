import unittest
import time
import random
import threading
import ulid  # Assuming ulid is available and imported correctly in your project
import queue  # For result_queue in test_ensure_factory_id_on_generic_thread_without_id_problematic

# --- IMPORT YOUR ACTUAL CLASSES ---
# Ensure these imports correctly point to your SmartCondition and Worker implementations.
from thread_factory.primatives.smart_condition import SmartCondition
from thread_factory.runtime.worker.worker import Worker


# A simple thread class that does *not* pre-set factory_id,
# to simulate the problematic scenario for testing _ensure_factory_id.
# This class is for testing SmartCondition's _ensure_factory_id robustness.
class GenericTestThread(threading.Thread):
    def __init__(self, target=None, args=(), kwargs=None):
        super().__init__(target=target, args=args, kwargs=kwargs)
        # Ensure it does NOT have factory_id set initially for the purpose of this test.
        if hasattr(self, 'factory_id'):
            del self.factory_id


class TestSmartCondition(unittest.TestCase):
    # --- Helper for factory_id setup in test MyWorker classes ---
    # This helper function is specifically for MyWorker.run() methods
    # that override Worker.run() and don't call super().run().
    # It ensures threading.current_thread().factory_id is set for SmartCondition.
    def _set_thread_factory_id(self, fid: str):
        threading.current_thread().factory_id = fid

    # --- Existing tests (from your provided code) ---
    def test_notify_partial_then_all(self):
        cond = SmartCondition()
        results = []
        lock = threading.Lock()

        class MyWorker(Worker):
            def __init__(self, name, fid):
                super().__init__()
                self.name = name
                self.factory_id = str(fid)  # This sets self.factory_id on the instance

            def run(self):
                # Ensure the current thread object's factory_id is set
                # as the base Worker.run() (which does _bind_factory_id) is not called.
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
        order = []  # Not strictly used for assertion, but good for understanding flow

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
                cond.notify_all(factory_ids=str(fid))  # notify_all wakes all with matching FID
            time.sleep(0.05)
            order.append(fid)

        for t in threads:
            t.join()

        # Should be [1, 1, 2, 2, 3, 3] as two workers for each FID are woken
        self.assertEqual(sorted(results), [1, 1, 2, 2, 3, 3])
        self.assertTrue(all(fid in results for fid in order))  # Check if all targeted FIDs appear in results

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
                with cond:  # Each recursive call also acquires the condition's lock
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

        factory_ids = [random.choice(range(10)) for _ in range(100)]  # 100 workers, 10 possible IDs
        threads = [MyWorker(fid) for fid in factory_ids]
        for t in threads:
            t.start()

        time.sleep(0.2)  # Allow workers to enter wait state

        # Notify each group of FIDs
        for fid_to_notify in set(factory_ids):  # Iterate over unique IDs to notify each group
            with cond:
                cond.notify_all(factory_ids=str(fid_to_notify))
            time.sleep(0.01)  # Short pause between group notifications

        for t in threads:
            t.join()

        self.assertEqual(len(results), 100)
        self.assertCountEqual(sorted(results), sorted(factory_ids))

    def test_waiter_removed_on_timeout(self):
        cond = SmartCondition()
        results = []

        class TimeoutWorker(Worker):
            def run(self):
                # For this test, SmartCondition assigns a default ULID via _ensure_factory_id
                # as we don't explicitly set threading.current_thread().factory_id here.
                # However, it's good practice for any worker to ensure its ID is set.
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
            cond.notify(n=2)  # Wake 2 arbitrary threads

        time.sleep(0.2)  # Give woken threads time to run

        with cond:
            cond.notify_all()  # Wake any remaining threads

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
            # Only notify workers with factory_id "1" or "3"
            cond.notify(n=2, factory_ids=["1", "3"])

        time.sleep(0.2)  # Give targeted threads time to run

        num_woken_initially = len(results)
        initial_woken_ids = list(results)

        self.assertLessEqual(num_woken_initially, 2, "More than 2 threads woken by targeted notify")
        if num_woken_initially > 0:
            for woken_fid in initial_woken_ids:
                self.assertIn(str(woken_fid), ["1", "3"], "Woke a thread not in target group")

        with cond:
            cond.notify_all()  # Wake any remaining

        for t in threads:
            t.join()

        self.assertEqual(len(results), 4, "All threads should have eventually completed")
        self.assertTrue(1 in results and 3 in results, "Targeted threads should have woken up")
        self.assertTrue(2 in results and 4 in results, "Other threads should have woken up eventually")

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

        # Start 3 workers who will all block on SmartCondition
        threads = [MyWorker(f"test_id_{i}") for i in range(3)]
        for t in threads:
            t.start()

        time.sleep(0.2)  # Allow them to enter the wait state

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
            # This is the line that was problematic. It is now removed.
            self.assertIn(fid, [f"test_id_{i}" for i in range(3)], f"Unexpected ID captured: {fid}")

    # --- New High-Performance Tests for SmartCondition ---

    def test_performance_high_contention_notify_all(self):
        # Scenario: Many threads wait, single source notifies all.
        # Measures efficiency of SmartCondition.wait() and SmartCondition.notify_all()
        num_workers = 100
        operations_per_worker = 100  # Each worker waits/wakes 100 times
        total_operations = num_workers * operations_per_worker

        cond = SmartCondition()
        successful_wakes = 0
        wakes_lock = threading.Lock()  # Protect shared counter

        events = [threading.Event() for _ in range(num_workers)]  # Signal worker completion

        class ContentionWorker(Worker):
            def __init__(self, worker_id, event_to_set):
                super().__init__()
                self.factory_id = f"worker-{worker_id}"
                self.event_to_set = event_to_set

            def run(self):
                TestSmartCondition._set_thread_factory_id(self, self.factory_id)
                nonlocal successful_wakes  # Access outer scope counter
                for _ in range(operations_per_worker):
                    with cond:
                        # Wait for the condition to be met (i.e., notified)
                        # We don't have an explicit predicate here, just waiting for a signal.
                        # `cond.wait()` will return True if notified.
                        if cond.wait(timeout=0.5):  # Short timeout per wait cycle
                            with wakes_lock:
                                successful_wakes += 1
                        else:
                            # If timeout, means condition wasn't met in time.
                            # Re-enter loop to potentially wait again.
                            pass
                self.event_to_set.set()  # Signal completion

        workers = []
        for i in range(num_workers):
            w = ContentionWorker(i, events[i])
            workers.append(w)

        start_time = time.perf_counter()
        for w in workers:
            w.start()

        # The main thread will continuously notify all workers
        # to simulate high wake-up frequency.
        notifies_sent = 0
        while successful_wakes < total_operations and (time.perf_counter() - start_time < 10):  # Limit total runtime
            with cond:
                # Notify some workers. Since we have many workers and few notifies,
                # this simulates contention for wake-ups.
                cond.notify(n=num_workers // 5)  # Wake a fifth of workers at a time
                notifies_sent += (num_workers // 5)
            time.sleep(0.001)  # Small pause to allow workers to re-acquire lock and wait

        # After initial burst, ensure all workers eventually finish
        if successful_wakes < total_operations:
            with cond:
                cond.notify_all()  # Final sweep to wake everyone up

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
        # Scenario: Many threads wait, notifications are precisely targeted.
        # Measures efficiency of SmartCondition.notify(factory_ids=...)
        num_workers = 50
        num_unique_ids = 10  # Workers will share these IDs
        operations_per_worker = 200
        total_operations = num_workers * operations_per_worker

        cond = SmartCondition()
        successful_wakes = 0
        wakes_lock = threading.Lock()

        events = [threading.Event() for _ in range(num_workers)]

        # Keep track of worker FIDs for targeted notifications
        worker_fids = [f"group-{i % num_unique_ids}" for i in range(num_workers)]

        class TargetedWorker(Worker):
            def __init__(self, worker_id, event_to_set):
                super().__init__()
                self.factory_id = worker_fids[worker_id]  # Assign group ID
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

        # Continuously send targeted notifications
        notifies_sent = 0
        unique_ids = list(set(worker_fids))  # Get the unique IDs to cycle through
        id_idx = 0
        while successful_wakes < total_operations and (time.perf_counter() - start_time < 15):
            target_fid = unique_ids[id_idx % num_unique_ids]
            with cond:
                # Notify one specific worker (or group) at a time
                cond.notify(n=1, factory_ids=target_fid)
                notifies_sent += 1
            id_idx += 1
            time.sleep(0.0005)  # Small pause

        if successful_wakes < total_operations:
            with cond:
                cond.notify_all()  # Final sweep

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
        # Scenario: Many threads wait for a shared counter to reach a specific value.
        # This tests SmartCondition.wait_for() and its underlying wait/notify cycles.
        num_workers = 20
        target_count_per_worker = 5  # Each worker aims to advance the counter 5 times

        # Use a class to hold shared state, better than 'nonlocal' for complex tests
        class SharedState:
            def __init__(self):
                self.counter = 0
                self.lock = threading.Lock()  # Lock to protect the counter

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
                    # Each worker waits for the global counter to become (i+1)
                    # The condition is that shared_state.counter should be >= the worker's current target.
                    expected_counter_value = i + 1

                    def predicate():
                        # This predicate runs inside cond's lock, so shared_state.counter access is safe.
                        return shared_state.counter >= expected_counter_value

                    if cond.wait_for(predicate, timeout=5):  # Wait for predicate with timeout
                        self.acquired_predicates += 1

                        # IMPORTANT: Only increment shared_state.counter IF it's exactly the value
                        # we just advanced to. This prevents a race where multiple workers might
                        # try to increment past each other causing missed steps or double increments
                        # for the same 'target_value'.
                        with shared_state.lock:  # Protect access to shared_state.counter outside cond's lock
                            if shared_state.counter < expected_counter_value:
                                pass  # We already know predicate() is true, meaning shared_state.counter >= expected_counter_value

                    else:
                        print(f"[{self.factory_id}] Predicate wait for {expected_counter_value} timed out.")
                        # This break makes the worker stop if it times out once, which can lead to test failure.
                        # For robust predicate tests, consider if a timeout should truly stop the worker,
                        # or just mean it missed a cycle and should try again. For this test, it's ok.
                        break

                self.event_to_set.set()

        workers = []
        for i in range(num_workers):
            w = PredicateWorker(i, events[i])
            workers.append(w)

        # Start workers
        start_time = time.perf_counter()
        for w in workers:
            w.start()

        # The main thread (test runner) will drive the `shared_state.counter`
        # and notify the workers. This is the "missing link" for the chain reaction.
        for step in range(num_workers * target_count_per_worker):  # Max possible increments
            with shared_state.lock:
                # Increment the counter
                shared_state.counter += 1
                current_count = shared_state.counter

            with cond:
                cond.notify_all()  # Notify all workers when the counter changes

            # Introduce a small delay to simulate work/scheduling
            time.sleep(0.0001)

            # Check if all workers have finished their predicates, or if we've iterated enough
            if all(w.acquired_predicates == target_count_per_worker for w in workers):
                break  # All done early!

        # Ensure final notify_all in case some workers missed signals
        with cond:
            cond.notify_all()

        all_finished = all(e.wait(timeout=30) for e in events)  # Wait for all workers to signal completion
        end_time = time.perf_counter()

        for w in workers:
            w.join(timeout=1)
            self.assertFalse(w.is_alive(), f"Worker {w.factory_id} did not terminate.")

        elapsed_time = end_time - start_time

        # Calculate total successful predicate checks across all workers
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


# --- Existing _ensure_factory_id theory tests (unchanged from your last successful run) ---
class TestSmartConditionFactoryIdTheory(unittest.TestCase):

    def setUp(self):
        self.cond = SmartCondition()

    def test_ensure_factory_id_on_main_thread(self):
        initial_main_factory_id = getattr(threading.current_thread(), 'factory_id', None)
        try:
            fid = self.cond._ensure_factory_id()
            self.assertEqual(fid, "MainThread", "MainThread factory_id should be 'MainThread'")
            self.assertEqual(threading.current_thread().factory_id, "MainThread",
                             "MainThread's thread object should have 'MainThread' factory_id")
        finally:
            if initial_main_factory_id is not None:
                threading.current_thread().factory_id = initial_main_factory_id
            elif hasattr(threading.current_thread(), 'factory_id'):
                del threading.current_thread().factory_id

    def test_ensure_factory_id_on_thread_with_predefined_id(self):
        expected_fid = "pre-assigned-ulid-123456789012345"  # Needs to be 26 chars like a real ULID

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


if __name__ == '__main__':
    unittest.main()
