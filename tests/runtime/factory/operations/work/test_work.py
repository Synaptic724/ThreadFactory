import unittest
from thread_factory.runtime.factory.operations import Work
import unittest
import time
import asyncio
from concurrent.futures import CancelledError

class TestWork(unittest.TestCase):

    def test_basic_execution_and_result(self):
        def sample_fn(x, y): return x + y
        work = Work(sample_fn, 2, 3)
        work.run()
        self.assertEqual(work.result(), 5)
        self.assertEqual(work.status(), "completed")

    def test_pre_post_hooks(self):
        hooks_called = []

        def hook(w, phase): hooks_called.append((phase, w.task_id))

        def fn(): return 42

        work = Work(fn)
        work.add_hook(hook, "before")
        work.add_hook(hook, "after")
        work.run()
        self.assertIn(("before", work.task_id), hooks_called)
        self.assertIn(("after", work.task_id), hooks_called)

    def test_exception_handling(self):
        def faulty(): raise ValueError("fail")
        work = Work(faulty)
        work.run()
        self.assertIsInstance(work.exception(), ValueError)
        self.assertEqual(work.status(), "completed")

    def test_cancel_before_run(self):
        def fn(): return 99
        work = Work(fn)
        cancelled = work.cancel()
        self.assertTrue(cancelled)
        self.assertTrue(work.cancelled())
        with self.assertRaises(CancelledError):
            work.result()
        self.assertEqual(work.status(), "cancelled")

    def test_coroutine_function(self):
        async def async_fn():
            await asyncio.sleep(1)
            return "done"

        with self.assertRaises(TypeError):
            work = Work(async_fn)


    def test_add_callback(self):
        async def async_fn():
            await asyncio.sleep(1)
            return "done"

        with self.assertRaises(TypeError):
            work = Work()
            work.add_done_callback(async_fn)

    def test_hooks_with_exceptions(self):
        async def pre_hook_fn():
            pass

        async def post_hook_fn():
            pass

        with self.assertRaises(TypeError):
            work = Work()
            work.add_hook(pre_hook_fn, "before")

        with self.assertRaises(TypeError):
            work = Work()
            work.add_hook(post_hook_fn, "before")

    def test_cleanup(self):
        def cleanup_fn():
            return "cleanup"

        work = Work(cleanup_fn)
        work.run()
        result = work.result()
        work.dispose()

        self.assertEqual(result, "cleanup")
        self.assertEqual(work.result(), None)
        self.assertTrue(work.disposed)

    def test_multiple_hooks_and_priority(self):
        state = []

        def hook1(w, phase): state.append(f"hook1-{phase}")
        def hook2(w, phase): state.append(f"hook2-{phase}")
        def task(): return "done"

        work = Work(task, priority=10)
        work.add_hook(hook1, "before")
        work.add_hook(hook2, "after")
        work.run()
        self.assertIn("hook1-before", state)
        self.assertIn("hook2-after", state)
        self.assertEqual(work.priority, 10)

if __name__ == "__main__":
    unittest.main()
