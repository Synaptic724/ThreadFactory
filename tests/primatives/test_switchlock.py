import unittest
import threading
import time
import random
from thread_factory.primatives import SwitchLock
from thread_factory.runtime.worker.worker import Worker


# --- Helper function (from your existing tests) ---
def wait_for_waiters(lock: SwitchLock, expected: int, timeout: float = 2.0):
    start = time.time()
    while time.time() - start < timeout:
        current = lock.get_all_waiting_factory_ids()
        if len(current) >= expected:
            return
        time.sleep(0.01)  # Short sleep to avoid busy-waiting
    raise AssertionError(f"Waiters not registered in time. Expected: {expected}, Got: {len(current)}")


class TestSwitchLock(unittest.TestCase):
    # --- Existing tests (unchanged, just for context) ---
    def test_init_negative_value_raises(self):
        with self.assertRaises(ValueError):
            SwitchLock(value=-1)

    def test_init_zero_acquire_block(self):
        lock = SwitchLock(value=0)
        event = threading.Event()

        def attempt_acquire():
            got_it = lock.acquire(timeout=0.5)
            if got_it:
                event.set()

        t = Worker(target=attempt_acquire)
        t.start()
        wait_for_waiters(lock, expected=1)
        lock.release()
        t.join(timeout=1)
        self.assertTrue(event.wait(timeout=1))

    def test_basic_single_permit(self):
        lock = SwitchLock(value=1)
        self.assertTrue(lock.acquire(blocking=False))
        self.assertFalse(lock.acquire(blocking=False))
        lock.release()
        self.assertTrue(lock.acquire(blocking=False))

    def test_acquire_timeout(self):
        lock = SwitchLock(value=0)
        start = time.time()
        self.assertFalse(lock.acquire(timeout=0.3))
        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 0.3)

    def test_permit_increase_unblocks_thread(self):
        lock = SwitchLock(value=0)
        result = []
        event = threading.Event()

        def wait_and_append():
            # This worker will acquire the lock using its context manager,
            # which means it will release it automatically on exit.
            with lock:
                result.append("done")
                event.set()

        t = Worker(target=wait_and_append)
        t.start()
        wait_for_waiters(lock, expected=1)
        lock.increase_permits(1)
        event.wait(timeout=1)
        t.join(timeout=1)
        self.assertEqual(result, ["done"])

    def test_decrease_permits_check(self):
        lock = SwitchLock(value=2)
        lock.acquire()
        self.assertTrue(lock.acquire(blocking=False))
        with self.assertRaises(ValueError):
            lock.decrease_permits(n=1)  # Should fail as 0 permits left

    def test_targeted_release_uses_factory_ids(self):
        lock = SwitchLock(value=0)
        results = {}
        threads = []

        def blocking():
            lock.acquire()
            fid = threading.current_thread().factory_id
            # Use a synchronized way to update results, as multiple threads write
            with threading.Lock():
                results[fid] = results.get(fid, 0) + 1

        for _ in range(4):
            t = Worker(target=blocking)
            threads.append(t)
            t.start()

        wait_for_waiters(lock, expected=4)

        all_ids = lock.get_all_waiting_factory_ids()
        group = all_ids[:2]  # Select first two IDs for targeted release

        lock.release(n=2, factory_ids=group)
        time.sleep(0.2)  # Give threads time to wake up and process
        for fid in group:
            self.assertIn(fid, results, f"Expected {fid} to be in results after targeted release")

        lock.release(n=2)  # Release remaining permits to unblock others
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

        self.assertEqual(len(results), 4, "Expected all 4 threads to have updated results")

    def test_nonblocking_acquire(self):
        lock = SwitchLock(value=1)
        self.assertTrue(lock.acquire(blocking=False))
        self.assertFalse(lock.acquire(blocking=False))

    def test_dispose_wakes_waiters(self):
        lock = SwitchLock(value=0)
        done = [threading.Event(), threading.Event()]

        def waiter(idx):
            # Worker will block here until lock is acquired or disposed
            lock.acquire()
            done[idx].set()

        threads = [Worker(target=waiter, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()

        wait_for_waiters(lock, expected=2)  # Ensure both threads are waiting
        lock.dispose()  # Dispose the lock, which should wake all waiters

        for i, e in enumerate(done):
            self.assertTrue(e.wait(timeout=1), f"Waiter {i} was not woken up after dispose")

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate after dispose.")

    def test_get_all_waiting_factory_ids(self):
        lock = SwitchLock(value=0)

        def blocking():
            lock.acquire()  # This thread will block here

        threads = [Worker(target=blocking) for _ in range(3)]
        for t in threads:
            t.start()

        wait_for_waiters(lock, expected=3)  # Ensure all 3 threads are waiting

        waiting = lock.get_all_waiting_factory_ids()
        self.assertEqual(len(waiting), 3, "Expected 3 threads to be waiting")
        for fid in waiting:
            self.assertIsInstance(fid, str)  # Check type
            self.assertEqual(len(fid), 26)  # Check if it looks like a ULID

        lock.release(n=3)  # Release all permits
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

    def test_release_n_unblocks_n_threads(self):
        lock = SwitchLock(value=0)
        released_indices = []  # Track which worker indices were woken up
        events = [threading.Event() for _ in range(5)]  # One event per worker

        def waiter(worker_idx, event_to_set):
            if lock.acquire(timeout=2):  # Acquire with a timeout
                with threading.Lock():  # Protect shared list
                    released_indices.append(worker_idx)
                event_to_set.set()  # Signal that this worker acquired the lock

        threads = []
        for i in range(5):
            t = Worker(target=waiter, args=(i, events[i]))
            threads.append(t)
            t.start()

        time.sleep(0.2)  # Give threads time to block on the lock
        lock.release(n=2)  # Wake 2 arbitrary threads

        # Wait for the specific events of the 2 woken threads to be set
        # This will block until up to 2 events are set or timeout
        triggered_count = sum(e.wait(timeout=1) for e in events)
        self.assertEqual(len(released_indices), 2, "Expected exactly 2 workers to acquire the lock")
        self.assertEqual(triggered_count, 2, "Expected exactly 2 events to be set")

        # Clean up: release remaining permits and join threads
        lock.release(n=3)  # Release the rest
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

    def test_targeted_release_by_ulid(self):
        lock = SwitchLock(value=0)
        got_ids = []
        events = [threading.Event() for _ in range(4)]  # One event per worker

        def waiter(event_to_set):
            fid = threading.current_thread().factory_id
            if lock.acquire(timeout=2):
                with threading.Lock():  # Protect shared list
                    got_ids.append(fid)
                event_to_set.set()

        threads = []
        # Assign unique names to Workers for easier debugging, factory_id will be derived
        for i in range(4):
            t = Worker(target=waiter, args=(events[i],), name=f"TestWorker-{i}")
            threads.append(t)
            t.start()

        time.sleep(0.2)  # Let all threads block
        wait_for_waiters(lock, expected=4)  # Ensure all 4 threads are waiting

        all_waiting_ids = lock.get_all_waiting_factory_ids()
        # Select two specific IDs to target for notification
        # Ensure we pick actual IDs from the waiting list to guarantee they exist
        targets = all_waiting_ids[:2]

        print(f"Targeting IDs for release: {targets}")  # Debug output

        lock.release(n=2, factory_ids=targets)  # Release 2 permits, targeting specific IDs

        woken_count = sum(e.wait(timeout=1) for e in events)
        self.assertEqual(len(got_ids), 2, "Expected exactly 2 workers to acquire the lock")
        self.assertEqual(woken_count, 2, "Expected exactly 2 events to be set")

        # Verify that the woken threads are indeed the targeted ones
        self.assertCountEqual(got_ids, targets, "The woken IDs should match the targeted IDs")

        # Clean up: release remaining permits and join threads
        lock.release(n=2)  # Release the rest
        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

    def test_notify_all_threads(self):
        lock = SwitchLock(value=0)
        events = []  # One event per worker

        def waiter(event_to_set):
            if lock.acquire(timeout=2):
                event_to_set.set()

        threads = []
        for _ in range(4):
            e = threading.Event()
            events.append(e)
            t = Worker(target=waiter, args=(e,))
            threads.append(t)
            t.start()

        time.sleep(0.2)  # Give threads time to block
        wait_for_waiters(lock, expected=4)  # Ensure all 4 threads are waiting

        lock.release(n=4)  # Release all 4 permits, implicitly notifying all

        all_woke = all(e.wait(timeout=1) for e in events)
        self.assertTrue(all_woke, "Not all threads woke up as expected after notify_all")

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

    def test_concurrent_stress_simple(self):
        num_threads = 10
        operations_per_thread = 50
        total_operations = num_threads * operations_per_thread
        lock = SwitchLock(value=num_threads // 2)  # Moderate contention: half as many permits as threads
        total_success_acquires = 0
        total_lock = threading.Lock()  # Protect the shared counter

        events = [threading.Event() for _ in range(num_threads)]  # One event per worker

        def job(event_to_set):
            nonlocal total_success_acquires
            acquired_count = 0
            for _ in range(operations_per_thread):
                if lock.acquire(timeout=1):  # Acquire with a timeout
                    try:
                        # Simulate some work under lock
                        time.sleep(0.001)
                        with total_lock:
                            total_success_acquires += 1
                        acquired_count += 1
                    finally:
                        lock.release()  # Always release the lock
            event_to_set.set()  # Signal that this worker is done

        threads = []
        for i in range(num_threads):
            t = Worker(target=job, args=(events[i],), name=f"StressWorker-{i}")
            threads.append(t)

        start_time = time.perf_counter()
        for t in threads:
            t.start()

        all_finished = all(e.wait(timeout=5) for e in events)  # Wait for all threads to signal completion
        end_time = time.perf_counter()

        for t in threads:
            t.join(timeout=1)  # Ensure all threads actually terminate
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

        elapsed_time = end_time - start_time
        print(f"\n--- Performance Test Results ---")
        print(
            f"Test: Concurrent Stress (Permits: {lock._value}, Threads: {num_threads}, Ops/Thread: {operations_per_thread})")
        print(f"Total time: {elapsed_time:.4f} seconds")
        print(f"Total successful acquires: {total_success_acquires}")
        # Calculate operations per second (throughput)
        if elapsed_time > 0:
            ops_per_second = total_success_acquires / elapsed_time
            print(f"Operations per second (throughput): {ops_per_second:.2f}")
        else:
            print("Elapsed time is zero, cannot calculate operations per second.")

        self.assertTrue(all_finished, "Not all threads finished signaling in time.")
        self.assertEqual(total_success_acquires, total_operations,
                         "Expected total successful acquires to match total operations")

    # --- New Performance Test: High Contention ---
    def test_performance_high_contention(self):
        num_threads = 50  # High number of threads
        operations_per_thread = 1000  # Many operations
        total_operations = num_threads * operations_per_thread
        lock = SwitchLock(value=1)  # Very high contention (only 1 permit)

        total_success_acquires = 0
        total_lock = threading.Lock()
        events = [threading.Event() for _ in range(num_threads)]

        def job(event_to_set):
            nonlocal total_success_acquires
            for _ in range(operations_per_thread):
                # Acquire the lock; indefinite wait if no timeout, but here 1s is fair for stress
                if lock.acquire(timeout=10):  # A longer timeout for stress test
                    try:
                        # Simulate minimal work under lock to keep it held briefly
                        time.sleep(0.00001)  # Very small sleep to represent critical section work
                        with total_lock:
                            total_success_acquires += 1
                    finally:
                        lock.release()
            event_to_set.set()

        threads = []
        for i in range(num_threads):
            t = Worker(target=job, args=(events[i],), name=f"HighContentionWorker-{i}")
            threads.append(t)

        start_time = time.perf_counter()
        for t in threads:
            t.start()

        all_finished = all(e.wait(timeout=30) for e in events)  # Longer timeout for high contention
        end_time = time.perf_counter()

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

        elapsed_time = end_time - start_time
        print(f"\n--- Performance Test Results ---")
        print(
            f"Test: High Contention (Permits: {lock._value}, Threads: {num_threads}, Ops/Thread: {operations_per_thread})")
        print(f"Total time: {elapsed_time:.4f} seconds")
        print(f"Total successful acquires: {total_success_acquires}")
        if elapsed_time > 0:
            ops_per_second = total_success_acquires / elapsed_time
            print(f"Operations per second (throughput): {ops_per_second:.2f}")
        else:
            print("Elapsed time is zero, cannot calculate operations per second.")

        self.assertTrue(all_finished, "Not all threads finished signaling in time.")
        self.assertEqual(total_success_acquires, total_operations,
                         "Expected total successful acquires to match total operations")
        self.assertGreater(ops_per_second, 1000,
                           "Expected a minimum throughput of 1000 ops/sec for high contention")  # Example threshold

    # --- New Performance Test: Low Contention ---
    def test_performance_low_contention(self):
        num_threads = 50
        operations_per_thread = 1000
        total_operations = num_threads * operations_per_thread
        lock = SwitchLock(value=num_threads)  # Low contention (many permits, one per thread capacity)

        total_success_acquires = 0
        total_lock = threading.Lock()
        events = [threading.Event() for _ in range(num_threads)]

        def job(event_to_set):
            nonlocal total_success_acquires
            for _ in range(operations_per_thread):
                if lock.acquire(timeout=10):
                    try:
                        time.sleep(0.00001)
                        with total_lock:
                            total_success_acquires += 1
                    finally:
                        lock.release()
            event_to_set.set()

        threads = []
        for i in range(num_threads):
            t = Worker(target=job, args=(events[i],), name=f"LowContentionWorker-{i}")
            threads.append(t)

        start_time = time.perf_counter()
        for t in threads:
            t.start()

        all_finished = all(e.wait(timeout=30) for e in events)
        end_time = time.perf_counter()

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

        elapsed_time = end_time - start_time
        print(f"\n--- Performance Test Results ---")
        print(
            f"Test: Low Contention (Permits: {lock._value}, Threads: {num_threads}, Ops/Thread: {operations_per_thread})")
        print(f"Total time: {elapsed_time:.4f} seconds")
        print(f"Total successful acquires: {total_success_acquires}")
        if elapsed_time > 0:
            ops_per_second = total_success_acquires / elapsed_time
            print(f"Operations per second (throughput): {ops_per_second:.2f}")
        else:
            print("Elapsed time is zero, cannot calculate operations per second.")

        self.assertTrue(all_finished, "Not all threads finished signaling in time.")
        self.assertEqual(total_success_acquires, total_operations,
                         "Expected total successful acquires to match total operations")
        self.assertGreater(ops_per_second, 5000,
                           "Expected a minimum throughput of 5000 ops/sec for low contention")  # Example threshold

    # --- New Performance Test: Dynamic Permit Adjustment ---
    def test_performance_dynamic_permit_adjustment(self):
        num_threads = 20
        operations_per_thread = 200  # Fewer ops because of dynamic changes
        total_operations = num_threads * operations_per_thread
        lock = SwitchLock(value=2)  # Start with low permits

        total_success_acquires = 0
        total_lock = threading.Lock()
        events = [threading.Event() for _ in range(num_threads)]

        # Event to signal permit adjustment from main thread
        adjust_signal = threading.Event()
        adjustment_done_signal = threading.Event()

        def job(event_to_set):
            nonlocal total_success_acquires
            for i in range(operations_per_thread):
                if lock.acquire(timeout=5):  # Acquire with timeout
                    try:
                        time.sleep(0.0001)  # Very small work
                        with total_lock:
                            total_success_acquires += 1

                        # Halfway through, wait for adjustment signal
                        if i == operations_per_thread // 2 and not adjust_signal.is_set():
                            adjust_signal.wait(timeout=1)  # Wait briefly for main thread to adjust
                    finally:
                        lock.release()
            event_to_set.set()

        def adjust_permits_task():
            # Wait for some operations to complete, creating initial contention
            time.sleep(num_threads * operations_per_thread * 0.0001 / 2)  # Rough estimate to mid-run

            print(f"\n[Adjuster] Increasing permits by {num_threads // 2}")
            lock.increase_permits(n=num_threads // 2)  # Increase permits
            adjust_signal.set()  # Signal workers that adjustment happened

            time.sleep(0.5)  # Allow workers to pick up new permits

            print(f"[Adjuster] Decreasing permits back to 2")
            try:
                lock.decrease_permits(n=num_threads // 2 - 2)  # Bring it back down
            except ValueError as e:
                print(f"[Adjuster] Error decreasing permits: {e}")

            adjustment_done_signal.set()  # Signal that adjustment process is done

        threads = []
        for i in range(num_threads):
            t = Worker(target=job, args=(events[i],), name=f"DynamicWorker-{i}")
            threads.append(t)

        adjuster_thread = threading.Thread(target=adjust_permits_task, name="PermitAdjuster")

        start_time = time.perf_counter()
        adjuster_thread.start()
        for t in threads:
            t.start()

        all_finished = all(e.wait(timeout=30) for e in events)
        adjustment_done_signal.wait(timeout=5)  # Wait for adjuster to finish its job
        end_time = time.perf_counter()

        adjuster_thread.join(timeout=1)
        self.assertFalse(adjuster_thread.is_alive(), "Adjuster thread did not terminate.")

        for t in threads:
            t.join(timeout=1)
            self.assertFalse(t.is_alive(), f"Thread {t.factory_id} did not terminate.")

        elapsed_time = end_time - start_time
        print(f"\n--- Performance Test Results ---")
        print(f"Test: Dynamic Permit Adjustment (Threads: {num_threads}, Ops/Thread: {operations_per_thread})")
        print(f"Total time: {elapsed_time:.4f} seconds")
        print(f"Total successful acquires: {total_success_acquires}")
        if elapsed_time > 0:
            ops_per_second = total_success_acquires / elapsed_time
            print(f"Operations per second (throughput): {ops_per_second:.2f}")
        else:
            print("Elapsed time is zero, cannot calculate operations per second.")

        self.assertTrue(all_finished, "Not all threads finished signaling in time.")
        self.assertEqual(total_success_acquires, total_operations,
                         "Expected total successful acquires to match total operations")
        self.assertGreater(ops_per_second, 200,
                           "Expected a minimum throughput of 200 ops/sec for dynamic adjustment")  # Example threshold


# This block allows you to run these tests directly if saved in a file.
if __name__ == '__main__':
    unittest.main()
