import unittest
import threading
import time
from thread_factory.synchronization.primitives.smart_condition import SmartCondition

class TestSmartCondition(unittest.TestCase):

    def test_notify_wakes_one_thread(self):
        cond = SmartCondition()
        result = []

        def worker():
            with cond:
                cond.wait()
                result.append("woke")

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)  # Let thread start and wait

        with cond:
            cond.notify()

        t.join()
        self.assertIn("woke", result)

    def test_notify_and_call_executes_callback_from_notifier(self):
        cond = SmartCondition()
        result = []

        def worker():
            with cond:
                cond.wait()

        def callback():
            result.append("called")

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)

        with cond:
            cond.notify_and_call(callback=callback)

        t.join()
        self.assertIn("called", result)

    def test_notify_and_call_awaited_caller(self):
        cond = SmartCondition()
        result = []

        def worker():
            with cond:
                cond.wait()
                result.append("callback-ran")

        def callback():
            # Do nothing if executed by notifier
            if threading.current_thread().name == "MainThread":
                result.append("should-not-run-here")
            else:
                result.append("callback-ran")

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)

        with cond:
            cond.notify_and_call(callback=callback, awaited_caller=True)

        t.join()
        self.assertIn("callback-ran", result)
        self.assertNotIn("should-not-run-here", result)

    def test_notify_all_and_call_runs_callback_for_each_thread(self):
        cond = SmartCondition()
        result = []
        num_threads = 5
        events = [threading.Event() for _ in range(num_threads)]

        def make_worker(i):
            def cb():
                result.append(f"cb-{i}")
                events[i].set()

            def thread_fn():
                threading.current_thread().factory_id = f"worker-{i}"
                cond.bind_callback(f"worker-{i}", cb)
                with cond:
                    cond.wait()

            return threading.Thread(target=thread_fn, name=f"worker-{i}")

        threads = [make_worker(i) for i in range(num_threads)]
        for t in threads:
            t.start()

        time.sleep(0.2)  # Ensure all are blocking on cond.wait()

        with cond:
            cond.notify_all_and_call(awaited_caller=True)

        for e in events:
            self.assertTrue(e.wait(1), "Callback did not execute in time")

        for t in threads:
            t.join()

        self.assertEqual(sorted(result), [f"cb-{i}" for i in range(num_threads)])
    def test_notify_with_awaited_caller_invokes_callback_per_thread(self):
        cond = SmartCondition()
        result = []
        num_threads = 5
        events = [threading.Event() for _ in range(num_threads)]

        def make_worker(i):
            def cb():
                result.append(f"cb-{i}")
                events[i].set()

            def thread_fn():
                threading.current_thread().factory_id = f"worker-{i}"
                cond.bind_callback(f"worker-{i}", cb)
                with cond:
                    cond.wait()

            return threading.Thread(target=thread_fn, name=f"worker-{i}")

        threads = [make_worker(i) for i in range(num_threads)]
        for t in threads:
            t.start()

        time.sleep(0.2)  # Give time for threads to enter wait

        with cond:
            for i in range(num_threads):
                cond.notify(awaited_caller=True)
                time.sleep(0.05)  # Small gap to ensure fair wakeup

        for e in events:
            self.assertTrue(e.wait(1), "Callback did not execute in time")

        for t in threads:
            t.join()

        self.assertEqual(sorted(result), [f"cb-{i}" for i in range(num_threads)])


    def test_wait_timeout(self):
        cond = SmartCondition()
        result = []

        def worker():
            with cond:
                ok = cond.wait(timeout=0.3)
                result.append(ok)

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(result, [False])

    def test_wait_for_predicate(self):
        cond = SmartCondition()
        shared = {"done": False}

        def predicate():
            return shared["done"]

        def worker():
            with cond:
                cond.wait_for(predicate)
                shared["result"] = "yes"

        t = threading.Thread(target=worker)
        t.start()

        time.sleep(0.2)
        with cond:
            shared["done"] = True
            cond.notify_all()

        t.join()
        self.assertEqual(shared.get("result"), "yes")

if __name__ == "__main__":
    unittest.main()
