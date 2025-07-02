import unittest
import inspect
import ulid
from typing import Callable, List

from thread_factory.utils.coordination.group import Group
from thread_factory.utils.coordination.outcome import Outcome


class TestGroup(unittest.TestCase):

    def test_init_with_single_task(self):
        def my_task(): return "hello"
        g = Group(name="test", tasks=my_task)
        self.assertEqual(len(g.tasks), 1)
        self.assertEqual(len(g.outcomes), 1)
        g.dispose()

    def test_init_with_multiple_tasks(self):
        def t1(): pass
        def t2(): pass
        g = Group(name="batch", tasks=[t1, t2])
        self.assertEqual(len(g.tasks), 2)
        self.assertEqual(len(g.outcomes), 2)
        g.dispose()

    def test_invalid_task_type(self):
        with self.assertRaises(TypeError):
            Group(name="bad", tasks="not callable")
        with self.assertRaises(TypeError):
            Group(name="also bad", tasks=[lambda: 1, "oops"])

    def test_coroutine_task_rejected(self):
        async def bad(): pass
        with self.assertRaises(TypeError):
            Group(name="bad", tasks=bad)

    def test_dispose_disposes_outcomes(self):
        g = Group(name="disposable", tasks=[lambda: "x"])
        g.outcomes[0].set_result("x")
        self.assertFalse(g.outcomes[0].disposed)
        g.dispose()
        # Safe access via _iter_outcomes after dispose
        for o in g._iter_outcomes():
            self.assertTrue(o.disposed)

    def test_dispose_idempotent(self):
        g = Group(name="idempotent", tasks=[lambda: 1])
        g.dispose()
        g.dispose()  # no crash

    def test_reset_resets_outcomes(self):
        g = Group(name="reset", tasks=[lambda: "ok"])
        old = g.outcomes[0]
        old.set_result("ok")
        g.reset()
        new = g.outcomes[0]
        self.assertIsNot(old, new)
        self.assertFalse(new.done)
        self.assertTrue(old.disposed)
        g.dispose()

    def test_reset_does_nothing_if_disposed(self):
        g = Group(name="dead", tasks=[lambda: 1])
        g.dispose()
        g.reset()
        self.assertTrue(g.disposed)

    def test_results_only_returns_success(self):
        g = Group(name="results", tasks=[lambda: 1, lambda: 2])
        g.outcomes[0].set_result(1)
        g.outcomes[1].set_exception(ValueError("fail"))
        self.assertEqual(g.results, [1])
        g.dispose()

    def test_exceptions_only_returns_real_errors(self):
        g = Group(name="errors", tasks=[lambda: 1, lambda: 2])
        g.outcomes[0].set_result(1)
        g.outcomes[1].set_exception(ValueError("fail"))
        self.assertEqual(len(g.exceptions), 1)
        self.assertIsInstance(g.exceptions[0], ValueError)
        g.dispose()

    def test_results_and_exceptions_empty_if_not_done(self):
        g = Group(name="pending", tasks=[lambda: None])
        self.assertEqual(g.results, [])
        self.assertEqual(g.exceptions, [])
        g.dispose()

    def test_results_empty_after_dispose(self):
        g = Group(name="afterlife", tasks=[lambda: "x"])
        g.outcomes[0].set_result("x")
        g.dispose()
        self.assertEqual(g.results, [])
        self.assertEqual(g.exceptions, [])

    def test_multiple_outcomes_per_task_mode(self):
        g = Group(name="multi", tasks=[lambda: 1], multiple_outcomes_per_task=True)
        g.outcomes[0].append(Outcome())
        g.outcomes[0][0].set_result(123)
        self.assertEqual(g.results, [123])
        g.dispose()

    def test_iter_outcomes_covers_all_modes(self):
        g = Group(name="iter", tasks=[lambda: 1], multiple_outcomes_per_task=True)
        o1 = Outcome()
        o2 = Outcome()
        g.outcomes[0].extend([o1, o2])
        o1.set_result("a")
        o2.set_result("b")
        r = g.results
        self.assertCountEqual(r, ["a", "b"])
        g.dispose()

    def test_dispose_handles_disposed_outcome_gracefully(self):
        g = Group(name="fragile", tasks=[lambda: "res"])
        g.outcomes[0].dispose()
        self.assertEqual(g.results, [])
        self.assertEqual(g.exceptions, [])
        g.dispose()


if __name__ == "__main__":
    unittest.main()
