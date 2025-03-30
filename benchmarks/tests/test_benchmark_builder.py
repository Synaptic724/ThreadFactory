import unittest
from unittest.mock import MagicMock
from benchmarks.benchmark_builder import (
    ConcurrentBufferThreadsBenchmark,
    ConcurrentCollectionThreadsBenchmark,
    ConcurrentQueueThreadsBenchmark,
    CollectionsDequeThreadsBenchmark,
    MultiprocessingQueueBenchmark
)

class TestConcurrentBufferThreadsBenchmark(unittest.TestCase):
    def setUp(self):
        self.benchmark = ConcurrentBufferThreadsBenchmark()

    def test_run_benchmark_invokes_callback(self):
        mock_callback = MagicMock()
        self.benchmark.run_benchmark(
            callback=mock_callback,
            producers=2,
            consumers=2,
            items_per_producer=5
        )
        # Verify callback was indeed called exactly once
        self.assertTrue(mock_callback.called)
        self.assertEqual(mock_callback.call_count, 1)
        # Check the data shape passed to callback
        args, kwargs = mock_callback.call_args
        self.assertIn("duration", args[0])
        self.assertIn("remaining", args[0])
        self.assertIn("gil_enabled", args[0])

class TestConcurrentCollectionThreadsBenchmark(unittest.TestCase):
    def setUp(self):
        self.benchmark = ConcurrentCollectionThreadsBenchmark()

    def test_run_benchmark_basic(self):
        mock_callback = MagicMock()
        self.benchmark.run_benchmark(
            callback=mock_callback,
            producers=2,
            consumers=1,
            items_per_producer=10
        )
        self.assertTrue(mock_callback.called)
        args, _ = mock_callback.call_args
        data = args[0]
        self.assertIn("remaining", data)
        # 'remaining' should generally be 0 if all items were consumed
        self.assertGreaterEqual(data["remaining"], 0)

class TestConcurrentQueueThreadsBenchmark(unittest.TestCase):
    def setUp(self):
        self.benchmark = ConcurrentQueueThreadsBenchmark()

    def test_run_benchmark_through_threads(self):
        mock_callback = MagicMock()
        self.benchmark.run_benchmark(
            callback=mock_callback,
            producers=3,
            consumers=2,
            items_per_producer=4
        )
        # Check callback results
        self.assertTrue(mock_callback.called)
        data = mock_callback.call_args[0][0]
        self.assertIn("duration", data)

class TestCollectionsDequeThreadsBenchmark(unittest.TestCase):
    def setUp(self):
        self.benchmark = CollectionsDequeThreadsBenchmark()

    def test_run_benchmark_deque_usage(self):
        mock_callback = MagicMock()
        self.benchmark.run_benchmark(
            callback=mock_callback,
            producers=4,
            consumers=2,
            items_per_producer=3
        )
        self.assertTrue(mock_callback.called)
        data = mock_callback.call_args[0][0]
        self.assertIn("remaining", data)

class TestMultiprocessingQueueBenchmark(unittest.TestCase):
    def setUp(self):
        self.benchmark = MultiprocessingQueueBenchmark()

    def test_run_benchmark_multiprocessing(self):
        # Because this uses multiprocessing.Process, tests can be slower or tricky.
        mock_callback = MagicMock()
        self.benchmark.run_benchmark(
            callback=mock_callback,
            producers=1,
            consumers=1,
            items_per_producer=5
        )
        self.assertTrue(mock_callback.called)
        data = mock_callback.call_args[0][0]
        self.assertIn("duration", data)
        # 'remaining' might be "Unknown (platform-dependent)" on some OS
        # so we just check the key is present.
        self.assertIn("remaining", data)

if __name__ == '__main__':
    unittest.main()
