import unittest

from thread_factory.concurrency.concurrent_list import ConcurrentList
from thread_factory.utilities.coordination.group import Group
from thread_factory.utilities.coordination.outcome import Outcome
from thread_factory.utilities.coordination.package import Pack


class TestGroup(unittest.TestCase):

    def test_init_with_single_task(self):
        def my_task(): return "hello"
        g = Group(name="test", tasks=my_task)
        self.assertEqual(len(g.tasks), 1)
        self.assertEqual(len(g.outcomes), 1)
        g.dispose()

    def test_none_task_yields_empty_group(self):
        g = Group(name="none-is-fine", tasks=None)
        self.assertEqual(len(g.tasks), 0)
        self.assertEqual(len(g.outcomes), 0)
        g.dispose()

    def test_pack_wrapped_lambda(self):
        g = Group("wrapped", tasks=Pack(lambda: 42))
        self.assertEqual(len(g), 1)
        self.assertTrue(isinstance(g.tasks[0], Pack))
        g.dispose()

    def test_pack_multiple_valid_inputs(self):
        def f(): return 1

        def g(): return 2

        p1 = Pack(f)
        p2 = Pack(g)
        group = Group(name="many", tasks=[p1, p2])
        self.assertEqual(len(group.tasks), 2)
        group.dispose()

    def test_result_on_disposed_outcome(self):
        g = Group("deadres", tasks=[lambda: "x"])
        g.outcomes[0] = Outcome()
        g.outcomes[0].set_result("y")
        g.outcomes[0].dispose()
        self.assertEqual(g.results, [])
        g.dispose()

    def test_invalid_item_in_iterable(self):
        with self.assertRaises(TypeError):
            Group("badlist", tasks=[lambda: 1, None])

    def test_iter_and_len(self):
        g = Group("check", tasks=[lambda: 1, lambda: 2])
        self.assertEqual(len(g), 2)
        self.assertEqual(sum(1 for _ in g), 2)
        g.dispose()

    def test_outcome_index_out_of_range(self):
        g = Group("outofrange", tasks=[lambda: 1])
        with self.assertRaises(KeyError):
            _ = g.outcomes[99]
        g.dispose()

    def test_empty_group_is_safe(self):
        g = Group("empty")
        self.assertEqual(len(g), 0)
        self.assertEqual(g.results, [])
        self.assertEqual(g.exceptions, [])
        g.dispose()

    def test_dispose_on_already_disposed_outcome(self):
        g = Group("redead", tasks=[lambda: 1])
        g.outcomes[0].dispose()
        g.dispose()

    def test_partial_results(self):
        g = Group("partial", tasks=[lambda: 1, lambda: 2])
        g.outcomes[0] = Outcome()
        g.outcomes[0].set_result(100)
        self.assertEqual(g.results, [100])
        g.dispose()

    def test_outcome_manual_injection_with_result(self):
        g = Group("inject", tasks=[lambda: 1])
        o = Outcome()
        o.set_result("ok")
        g.outcomes[0] = o
        self.assertEqual(g.results, ["ok"])
        g.dispose()

    def test_reset_rebuilds_dict_structure(self):
        g = Group("rebuild", tasks=[lambda: 1, lambda: 2])
        old_outcomes = g.outcomes
        g.reset()
        self.assertIsNot(g.outcomes, old_outcomes)
        self.assertEqual(len(g.outcomes), 2)
        g.dispose()

    def test_multiple_outcomes_per_task_initializes_correctly(self):
        g = Group("multiinit", tasks=[lambda: 1], multiple_outcomes_per_task=True)
        self.assertTrue(isinstance(g.outcomes[0], ConcurrentList))
        g.dispose()

    def test_result_not_disposed_not_done(self):
        g = Group("pending2", tasks=[lambda: None])
        g.outcomes[0] = Outcome()
        self.assertEqual(g.results, [])
        g.dispose()

    def test_strict_none_task(self):
        with self.assertRaises(TypeError):
            Group("strict", tasks=[None])

    def test_generator_function_rejected(self):
        def gen(): yield 1

        with self.assertRaises(TypeError):
            Group("nope", tasks=gen)

    def test_non_callable_object(self):
        with self.assertRaises(TypeError):
            Group("badobj", tasks=[object()])

    def test_callable_class_accepted(self):
        class CallableObj:
            def __call__(self): return "yes"

        g = Group("callclass", tasks=CallableObj())
        self.assertEqual(len(g), 1)
        g.dispose()

    def test_reset_replaces_all_outcomes(self):
        g = Group("replace", tasks=[lambda: 1])
        o = g.outcomes[0]
        g.reset()
        self.assertIsNot(g.outcomes[0], o)
        g.dispose()

    def test_results_unwrap_nested_outcomes(self):
        g = Group("nest", tasks=[lambda: 1])
        g.outcomes[0] = Outcome()
        g.outcomes[0].set_result(123)
        self.assertEqual(g.results, [123])
        g.dispose()

    def test_results_with_mixed_success_and_exceptions(self):
        g = Group("mixedbag", tasks=[lambda: 1, lambda: 2])
        g.outcomes[0] = Outcome()
        g.outcomes[1] = Outcome()
        g.outcomes[0].set_result(10)
        g.outcomes[1].set_exception(ValueError("fail"))
        self.assertEqual(g.results, [10])
        g.dispose()

    def test_dispose_after_reset(self):
        g = Group("afterreset", tasks=[lambda: 1])
        g.reset()
        g.dispose()
        self.assertTrue(g.disposed)

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
        g.outcomes[0] = Outcome()  # Assign first
        g.outcomes[0].set_result("x")
        self.assertFalse(g.outcomes[0].disposed)
        g.dispose()
        for o in g._iter_outcomes():
            self.assertTrue(o.disposed)

    def test_dispose_idempotent(self):
        g = Group(name="idempotent", tasks=[lambda: 1])
        g.dispose()
        g.dispose()  # no crash

    def test_reset_resets_outcomes(self):
        g = Group(name="reset", tasks=[lambda: "ok"])
        g.outcomes[0] = Outcome()
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
        g.outcomes[0] = Outcome()
        g.outcomes[1] = Outcome()
        g.outcomes[0].set_result(1)
        g.outcomes[1].set_exception(ValueError("fail"))
        self.assertEqual(g.results, [1])
        g.dispose()

    def test_exceptions_only_returns_real_errors(self):
        g = Group(name="errors", tasks=[lambda: 1, lambda: 2])
        g.outcomes[0] = Outcome()
        g.outcomes[1] = Outcome()
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
        g.outcomes[0] = Outcome()
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
        g.outcomes[0] = Outcome()
        g.outcomes[0].dispose()
        self.assertEqual(g.results, [])
        self.assertEqual(g.exceptions, [])
        g.dispose()


if __name__ == "__main__":
    unittest.main()
