import unittest
from thread_factory.runtime.orchestrator.load_balancer import QueueAllocator


class TestQueueAllocator(unittest.TestCase):

    def test_acquire_release_cycle(self):
        allocator = QueueAllocator(queue_size=10)
        ids = [allocator.acquire() for _ in range(10)]
        self.assertEqual(len(allocator), 0)  # Queue should be empty

        # Release all
        for id_ in ids:
            allocator.release(id_)
        self.assertEqual(len(allocator), 10)  # Queue should be full again

    def test_acquire_overflow(self):
        allocator = QueueAllocator(queue_size=5)
        for _ in range(5):
            allocator.acquire()

        with self.assertRaises(RuntimeError) as context:
            allocator.acquire()
        self.assertIn("Queue is empty", str(context.exception))

    def test_release_invalid_id(self):
        allocator = QueueAllocator(queue_size=5)

        with self.assertRaises(ValueError):
            allocator.release(-1)

        with self.assertRaises(ValueError):
            allocator.release(9999)

    def test_dispose(self):
        allocator = QueueAllocator(queue_size=5)
        allocator.dispose()

        with self.assertRaises(RuntimeError):
            allocator.dispose()  # Should raise again if called twice (since you designed it that way)

    def test_context_manager(self):
        with QueueAllocator(queue_size=5) as allocator:
            ids = [allocator.acquire() for _ in range(5)]
            self.assertEqual(len(allocator), 0)

        # Should now be disposed after context exit
        with self.assertRaises(RuntimeError):
            allocator.acquire()

