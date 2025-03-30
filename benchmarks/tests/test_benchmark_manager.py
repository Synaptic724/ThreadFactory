import unittest
from unittest.mock import MagicMock, patch
from benchmarks.benchmark_manager import BenchmarkManager
from benchmarks.benchmark_builder import BaseBenchmark


class FakeBenchmark(BaseBenchmark):
    """A simple fake benchmark to test manager logic without concurrency complexities."""
    def run_benchmark(self, callback, producers, consumers, items_per_producer):
        data = {
            "duration": 0.5,
            "remaining": 0,
            "gil_enabled": True
        }
        callback(data)


class TestBenchmarkManager(unittest.TestCase):
    def setUp(self):
        self.manager = BenchmarkManager()

    @patch('benchmarks.benchmark_builder.BenchmarkFactory.get_benchmark')
    def test_run_benchmark_stores_record(self, mock_get_benchmark):
        # Mock the concurrency test object
        mock_get_benchmark.return_value = FakeBenchmark("fake_benchmark")

        self.manager.run_benchmark(
            name="fake_benchmark",
            producers=2,
            consumers=2,
            items_per_producer=10
        )
        # Check that a record was stored
        self.assertEqual(len(self.manager.records), 1)
        record = self.manager.records[0]
        self.assertEqual(record.name, "fake_benchmark")
        self.assertEqual(record.producers, 2)
        self.assertEqual(record.consumers, 2)
        self.assertEqual(record.items_per_producer, 10)
        self.assertGreater(record.duration, 0)
        self.assertGreaterEqual(record.throughput, 0)

    def test_export_no_records(self):
        """Export should return an empty list if no benchmarks were run."""
        exported = self.manager.export()
        self.assertEqual(exported, [])

    def test_store_record_directly(self):
        """Test internal _store_record usage."""
        data = {"duration": 1.0, "remaining": 5, "custom_key": "abc"}
        self.manager._store_record("test_bench", 3, 2, 10, data)
        self.assertEqual(len(self.manager.records), 1)
        record = self.manager.records[0]
        self.assertEqual(record.duration, 1.0)
        self.assertEqual(record.extra["custom_key"], "abc")

    @patch('builtins.print')
    def test_print_summary(self, mock_print):
        """Ensure print_summary prints lines for each record."""
        # Add a fake record
        data = {"duration": 1.0}
        self.manager._store_record("test_bench", 1, 1, 5, data)
        self.manager.print_summary()
        self.assertTrue(mock_print.called)
        # We can check that something about "test_bench" was printed:
        printed_args = " ".join(str(arg) for call in mock_print.call_args_list for arg in call[0])
        self.assertIn("test_bench", printed_args)

if __name__ == '__main__':
    unittest.main()
