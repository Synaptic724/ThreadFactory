import datetime
import unittest
import threading
import time
from enum import Enum, auto
import ulid
from collections import deque
from thread_factory.runtime import Records, Worker, WorkerState

class DummyQueue:
    """Simple queue to test Worker"""
    def __init__(self):
        self.queue = deque()
        self.lock = threading.Lock()

    def enqueue(self, item):
        with self.lock:
            self.queue.append(item)

    def dequeue(self):
        with self.lock:
            if self.queue:
                return self.queue.popleft()
            raise Exception("Empty")


class TestRecords(unittest.TestCase):

    def test_add_record(self):
        r = Records()
        u = ulid.ULID()
        r.add(u)
        self.assertEqual(len(r), 1)
        self.assertIn(u, r.records)

    def test_repr(self):
        r = Records()
        self.assertTrue("count=0" in repr(r))
        r.add(ulid.ULID())
        self.assertTrue("count=1" in repr(r))


class TestWorker(unittest.TestCase):

    def setUp(self):
        self.queue = DummyQueue()
        self.worker = Worker(factory=None)
        self.worker.daemon = False  # so unittest can detect properly

    def tearDown(self):
        if self.worker.is_alive():
            self.worker.stop()
            self.worker.join(timeout=2)

    def test_worker_initial_state(self):
        self.assertEqual(self.worker.state, WorkerState.CREATED)
        self.assertEqual(self.worker.completed_work, 0)
        self.assertIsInstance(self.worker.factory_id, str)
        self.assertIsInstance(self.worker.records, Records)

    def test_worker_hard_kill(self):
        self.queue.enqueue(lambda: time.sleep(0.5))  # long-running task

        self.worker.start()
        time.sleep(0.05)

        self.worker.hard_kill()
        self.worker.join(timeout=2)

        self.assertFalse(self.worker.is_alive())
        self.assertTrue(self.worker.death_event.is_set())

    def test_get_creation_timestamp(self):
        ts = self.worker.get_creation_timestamp()
        self.assertIsInstance(ts, float)

    def test_get_creation_datetime(self):
        dt = self.worker.get_creation_datetime()
        self.assertIsInstance(dt, datetime.datetime)


    def test_disposed(self):
        self.assertFalse(self.worker.disposed)
        self.worker.dispose()
        self.assertTrue(self.worker.disposed)
        self.assertFalse(self.worker.is_alive())

    def test_worker_executes_callable(self):
        flag = threading.Event()

        def task():
            flag.set()

        self.worker.work_queue = self.queue
        self.queue.enqueue(task)
        self.worker.start()
        flag.wait(timeout=2)
        self.worker.stop()
        self.worker.join()

        self.assertTrue(flag.is_set())
        self.assertEqual(self.worker.completed_work, 1)

    def test_worker_executes_run_method(self):
        class MyTask:
            def __init__(self):
                self.ran = False

            def run(self):
                self.ran = True

        obj = MyTask()
        self.worker.work_queue = self.queue
        self.queue.enqueue(obj)
        self.worker.start()
        time.sleep(0.05)
        self.worker.stop()
        self.worker.join()

        self.assertTrue(obj.ran)
        self.assertEqual(self.worker.completed_work, 1)

    def test_invalid_task_type(self):
        self.worker.work_queue = self.queue
        self.queue.enqueue(123)  # Not callable or runnable

        self.worker.start()
        time.sleep(0.05)
        self.worker.stop()
        self.worker.join()

        self.assertEqual(self.worker.completed_work, 0)

    def test_thread_switch_behavior(self):
        new_queue = DummyQueue()
        self.worker.thread_switch(new_queue)
        self.assertIs(self.worker.work_queue, new_queue)
        self.assertEqual(self.worker.state, WorkerState.SWITCHED)

    def test_get_creation_properties(self):
        ts = self.worker.get_creation_timestamp()
        dt = self.worker.get_creation_datetime()
        self.assertIsInstance(ts, float)
        self.assertIsInstance(dt, datetime.datetime)

    def test_stop_flag_sets(self):
        self.assertFalse(self.worker.shutdown_flag.is_set())
        self.worker.stop()
        self.assertTrue(self.worker.shutdown_flag.is_set())

    def test_dispose_twice_safe(self):
        self.worker.dispose()
        self.assertTrue(self.worker.disposed)
        try:
            self.worker.dispose()  # Should not raise
        except Exception as e:
            self.fail(f"Calling dispose twice raised an exception: {e}")

    def test_repr_contains_state_and_id(self):
        rep = repr(self.worker)
        self.assertIn("Worker", rep)
        self.assertIn("state=", rep)
        self.assertIn("completed=", rep)


if __name__ == "__main__":
    unittest.main()
