import unittest

from thread_factory import Work


class TestWork(unittest.TestCase):
    def test_successful_execution(self):
        """Test that Work executes successfully and records timing."""
        def sample_task(x, y):
            return x + y

        work = Work(sample_task, 2, 3)
        work.run()

        self.assertTrue(work.done())
        self.assertEqual(work.result(), 5)
        self.assertIsNotNone(work.timestamp_started)
        self.assertIsNotNone(work.timestamp_finished)
        self.assertIsNotNone(work.duration_ns)
        self.assertGreater(work.duration_ns, 0)

    def test_cancellation(self):
        """Test that Work handles cancellation before execution."""
        work = Work(lambda: 42)
        work.cancel_requested = True
        work.run()

        self.assertTrue(work.done())
        with self.assertRaises(RuntimeError):
            _ = work.result()

    def test_hooks_execution(self):
        """Test that hooks are called before and after task execution."""
        events = []

        def hook(work_obj, phase):
            events.append(phase)

        def dummy_task():
            return "OK"

        work = Work(dummy_task)
        work.add_hook(hook)
        work.run()

        self.assertEqual(events, ['before', 'after'])

    def test_exception_handling(self):
        """Test that exceptions in the task are captured by the Work object."""
        def failing_task():
            raise ValueError("Intentional failure")

        work = Work(failing_task)
        work.run()

        self.assertTrue(work.done())
        with self.assertRaises(ValueError):
            _ = work.result()


if __name__ == "__main__":
    unittest.main()
