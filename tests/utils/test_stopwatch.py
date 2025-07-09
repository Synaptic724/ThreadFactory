# Re-import necessary modules after code execution state reset
import unittest
import time
from thread_factory.utilities.timing_tools.stopwatch import Stopwatch

# Define unittests
class TestStopwatch(unittest.TestCase):
    def setUp(self):
        self.stopwatch = Stopwatch()

    def tearDown(self):
        self.stopwatch.dispose()

    def test_initial_state(self):
        self.assertEqual(self.stopwatch.elapsed(), 0.0)
        self.assertFalse(self.stopwatch.is_running())

    def test_start_and_stop(self):
        self.stopwatch.start()
        time.sleep(0.05)
        self.assertTrue(self.stopwatch.is_running())
        self.stopwatch.stop()
        elapsed = self.stopwatch.elapsed()
        self.assertFalse(self.stopwatch.is_running())
        self.assertGreater(elapsed, 0.0)

    def test_reset(self):
        self.stopwatch.start()
        time.sleep(0.05)
        self.stopwatch.stop()
        self.stopwatch.reset()
        self.assertEqual(self.stopwatch.elapsed(), 0.0)
        self.assertFalse(self.stopwatch.is_running())

    def test_multiple_start_stop_accumulates_time(self):
        self.stopwatch.start()
        time.sleep(0.03)
        self.stopwatch.stop()
        first_elapsed = self.stopwatch.elapsed()

        time.sleep(0.01)

        self.stopwatch.start()
        time.sleep(0.02)
        self.stopwatch.stop()
        second_elapsed = self.stopwatch.elapsed()

        self.assertGreater(second_elapsed, first_elapsed)

    def test_dispose_resets_state(self):
        self.stopwatch.start()
        time.sleep(0.02)
        self.stopwatch.dispose()
        self.assertEqual(self.stopwatch.elapsed_time, 0.0)
        self.assertIsNone(self.stopwatch.start_time)
        self.assertIsNone(self.stopwatch._clock)


if __name__ == "__main__":
    unittest.main()
