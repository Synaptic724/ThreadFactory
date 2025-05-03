import datetime
import unittest
import threading
import time
import ulid
from collections import deque

from thread_factory.runtime import Records, Worker  # Change to match your actual module


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
        self.assertEqual(self.worker.state, "IDLE")
        self.assertEqual(self.worker.completed_work, 0)
        self.assertIsInstance(self.worker.unique, str)
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


if __name__ == "__main__":
    unittest.main()
