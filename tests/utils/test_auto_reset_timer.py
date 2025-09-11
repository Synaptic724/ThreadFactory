import unittest
import time
from threading import Event
from thread_factory import AutoResetTimer  # Adjust this import based on your structure

class TestAutoResetTimer(unittest.TestCase):

    def setUp(self):
        self.trigger_count = 0
        self.trigger_event = Event()

        def callback():
            self.trigger_count += 1
            self.trigger_event.set()

        self.timer = AutoResetTimer(interval_sec=0.1, callback=callback)

    def tearDown(self):
        self.timer.stop()

    def test_timer_triggers_callback(self):
        self.timer.start()
        triggered = self.trigger_event.wait(timeout=0.5)
        self.assertTrue(triggered, "Timer did not trigger callback within expected time.")
        self.assertGreaterEqual(self.trigger_count, 1)

    def test_timer_repeats(self):
        self.timer.start()
        time.sleep(0.35)
        self.timer.stop()
        self.assertGreaterEqual(self.trigger_count, 2)

    def test_stop_timer(self):
        self.timer.start()
        time.sleep(0.15)
        self.timer.stop()
        count_at_stop = self.trigger_count
        time.sleep(0.2)
        self.assertEqual(self.trigger_count, count_at_stop, "Timer should not trigger after stop.")

    def test_is_running(self):
        self.assertFalse(self.timer.is_running())
        self.timer.start()
        self.assertTrue(self.timer.is_running())
        self.timer.stop()
        self.assertFalse(self.timer.is_running())


    def test_cleanup(self):
        self.timer.start()
        self.timer.cleanup()
        self.assertFalse(self.timer.is_running())
        self.assertIsNone(self.timer._timer, "Timer should be cleaned and timer reference should be None.")

if __name__ == '__main__':
    unittest.main()
