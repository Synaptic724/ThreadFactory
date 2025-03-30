import unittest
from unittest.mock import patch, MagicMock
import matplotlib
matplotlib.use('Agg')  # Use a non-interactive backend to avoid popups in test
from benchmarks.benchmark_visualizer import BenchmarkVisualizer

class TestBenchmarkVisualizer(unittest.TestCase):
    def setUp(self):
        self.mock_records = [
            {
                "name": "test_bench_1",
                "producers": 2,
                "consumers": 2,
                "items_per_producer": 10,
                "total_ops": 20,
                "duration": 1.0,
                "throughput": 20.0,
                "extra": {}
            },
            {
                "name": "test_bench_2",
                "producers": 4,
                "consumers": 2,
                "items_per_producer": 5,
                "total_ops": 20,
                "duration": 2.0,
                "throughput": 10.0,
                "extra": {"some_key": "groupA"}
            },
        ]
        self.viz = BenchmarkVisualizer(self.mock_records)

    @patch("matplotlib.pyplot.show")
    def test_show_bar_chart(self, mock_show):
        # We just ensure it runs without error
        self.viz.show_bar_chart(metric="throughput")
        self.assertTrue(mock_show.called)

    @patch("matplotlib.pyplot.show")
    def test_show_multiple_metrics(self, mock_show):
        self.viz.show_multiple_metrics(["throughput", "duration"])
        # Called once per metric
        self.assertEqual(mock_show.call_count, 2)

    def test_filter_by_name(self):
        filtered = self.viz.filter_by_name("bench_1")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "test_bench_1")

    def test_group_by_extra_key(self):
        # Just ensure it groups and prints. We'll use a patch on print to verify it runs.
        with patch('builtins.print') as mock_print:
            self.viz.group_by_extra_key("some_key")
            self.assertTrue(mock_print.called)

    @patch("matplotlib.pyplot.show")
    def test_show_grouped_bar_chart(self, mock_show):
        self.viz.show_grouped_bar_chart()
        self.assertTrue(mock_show.called)

    @patch("matplotlib.pyplot.show")
    def test_show_dual_axis_chart(self, mock_show):
        self.viz.show_dual_axis_chart()
        self.assertTrue(mock_show.called)

    @patch("matplotlib.pyplot.show")
    def test_show_line_chart(self, mock_show):
        self.viz.show_line_chart(x_field="producers", y_field="throughput")
        self.assertTrue(mock_show.called)

    @patch("matplotlib.pyplot.show")
    def test_show_scatter_plot(self, mock_show):
        self.viz.show_scatter_plot(x_field="duration", y_field="throughput")
        self.assertTrue(mock_show.called)

if __name__ == '__main__':
    unittest.main()
