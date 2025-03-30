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
    def test_run_benchmark_invokes_callback(self):
        mock_callback = MagicMock()
        benchmark = ConcurrentBufferThreadsBenchmark(
            producers=2,
            consumers=2,
            items_per_producer=5,
            callback=mock_callback
        )
        benchmark.run_benchmark()
        self.assertTrue(mock_callback.called)
        self.assertEqual(mock_callback.call_count, 1)
        args, kwargs = mock_callback.call_args
        self.assertIn("duration", args[0])
        self.assertIn("remaining", args[0])
        self.assertIn("gil_enabled", args[0])

class TestConcurrentCollectionThreadsBenchmark(unittest.TestCase):
    def test_run_benchmark_basic(self):
        mock_callback = MagicMock()
        benchmark = ConcurrentCollectionThreadsBenchmark(
            producers=2,
            consumers=1,
            items_per_producer=10,
            callback=mock_callback
        )
        benchmark.run_benchmark()
        self.assertTrue(mock_callback.called)
        data = mock_callback.call_args[0][0]
        self.assertIn("remaining", data)
        self.assertGreaterEqual(data["remaining"], 0)

class TestConcurrentQueueThreadsBenchmark(unittest.TestCase):
    def test_run_benchmark_through_threads(self):
        mock_callback = MagicMock()
        benchmark = ConcurrentQueueThreadsBenchmark(
            producers=3,
            consumers=2,
            items_per_producer=4,
            callback=mock_callback
        )
        benchmark.run_benchmark()
        self.assertTrue(mock_callback.called)
        data = mock_callback.call_args[0][0]
        self.assertIn("duration", data)

class TestCollectionsDequeThreadsBenchmark(unittest.TestCase):
    def test_run_benchmark_deque_usage(self):
        mock_callback = MagicMock()
        benchmark = CollectionsDequeThreadsBenchmark(
            producers=4,
            consumers=2,
            items_per_producer=3,
            callback=mock_callback
        )
        benchmark.run_benchmark()
        self.assertTrue(mock_callback.called)
        data = mock_callback.call_args[0][0]
        self.assertIn("remaining", data)

class TestMultiprocessingQueueBenchmark(unittest.TestCase):
    def test_run_benchmark_multiprocessing(self):
        mock_callback = MagicMock()
        benchmark = MultiprocessingQueueBenchmark(
            producers=1,
            consumers=1,
            items_per_producer=5,
            callback=mock_callback
        )
        benchmark.run_benchmark()
        self.assertTrue(mock_callback.called)
        data = mock_callback.call_args[0][0]
        self.assertIn("duration", data)
        self.assertIn("remaining", data)  # might be string on Windows

if __name__ == '__main__':
    unittest.main()
