import unittest
from thread_factory.utils import IDisposable, Outcome, Group


class TestGroup(unittest.TestCase):

    def setUp(self):
        # Ensure a clean state for each test
        pass

    def tearDown(self):
        # No explicit cleanup needed for Group instances, as dispose is tested
        pass

    # --- Initialization Tests ---
    def test_init_valid_threshold(self):
        group = Group(threshold=1)
        self.assertEqual(group.threshold, 1)
        self.assertEqual(group.count, 0)
        self.assertFalse(group.ready)
        self.assertFalse(group.disposed)
        self.assertFalse(group._released_once)
        self.assertEqual(len(group.tasks), 0)
        self.assertEqual(len(group.outcomes), 0)
        group.dispose() # Clean up

    def test_init_invalid_threshold(self):
        with self.assertRaises(ValueError) as cm:
            Group(threshold=0)
        self.assertIn("Threshold must be a positive integer.", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            Group(threshold=-1)
        self.assertIn("Threshold must be a positive integer.", str(cm.exception))

    def test_init_with_single_task(self):
        def my_task(): return "hello"
        group = Group(threshold=1, tasks=my_task)
        self.assertEqual(len(group.tasks), 1)
        self.assertEqual(len(group.outcomes), 1)
        self.assertIsInstance(group.outcomes[0], Outcome)
        group.dispose()

    def test_init_with_list_of_tasks(self):
        def task1(): pass
        def task2(): pass
        group = Group(threshold=2, tasks=[task1, task2])
        self.assertEqual(len(group.tasks), 2)
        self.assertEqual(len(group.outcomes), 2)
        self.assertIsInstance(group.outcomes[0], Outcome)
        self.assertIsInstance(group.outcomes[1], Outcome)
        group.dispose()

    def test_init_with_invalid_tasks_type(self):
        with self.assertRaises(TypeError) as cm:
            Group(threshold=1, tasks="not a callable")
        # Updated assertion message to match the Group class's actual message
        self.assertIn("tasks must be a callable function or a list of callable functions.", str(cm.exception))

        with self.assertRaises(TypeError) as cm:
            Group(threshold=1, tasks=[lambda: None, "not a callable"])
        # Updated assertion message to match the Group class's actual message
        self.assertIn("tasks must be a callable function or a list of callable functions.", str(cm.exception))

    def test_init_with_coroutine_task(self):
        async def async_task(): pass
        with self.assertRaises(TypeError) as cm:
            Group(threshold=1, tasks=async_task)
        self.assertIn("Coroutines are not supported; only synchronous callables are allowed.", str(cm.exception))

    # --- dispose() Tests ---
    def test_dispose_sets_disposed_flag(self):
        group = Group(threshold=1)
        self.assertFalse(group.disposed)
        group.dispose()
        self.assertTrue(group.disposed)

    def test_dispose_idempotency(self):
        group = Group(threshold=1)
        group.dispose()
        self.assertTrue(group.disposed)
        group.dispose() # Call again
        self.assertTrue(group.disposed) # Should still be disposed, no error

    def test_dispose_calls_outcome_dispose(self):
        mock_outcome_disposed = False
        class MockOutcome(Outcome):
            def dispose(self):
                nonlocal mock_outcome_disposed
                mock_outcome_disposed = True
                super().dispose() # Call parent dispose to clear internal state

        group = Group(threshold=1, tasks=[lambda: None])
        group.outcomes[0] = MockOutcome() # Replace with mock
        group.dispose()
        self.assertTrue(mock_outcome_disposed)
        # We can't safely access group.outcomes[0] after group.dispose() nullifies group.outcomes
        # Instead, rely on mock_outcome_disposed flag set by the mock.
        # self.assertTrue(group.outcomes[0].disposed) # REMOVED: This causes TypeError

    def test_dispose_clears_references(self):
        group = Group(threshold=1, tasks=[lambda: 1])
        group.dispose()
        self.assertIsNone(group.tasks)
        self.assertIsNone(group.outcomes)
        self.assertIsNone(group.threshold)
        self.assertIsNone(group.count)
        self.assertIsNone(group.ready)
        self.assertIsNone(group._released_once) # This should now be None

    def test_properties_after_dispose(self):
        def my_task(): return "result"
        group = Group(threshold=1, tasks=my_task)
        group.outcomes[0].set_result("result") # Set an outcome before dispose
        group.dispose()
        self.assertEqual(group.results, [])
        self.assertEqual(group.exceptions, [])

    # --- reset() Tests ---
    def test_reset_restores_initial_state(self):
        group = Group(threshold=1, tasks=[lambda: None])
        group.count = 5
        group.ready = True
        group._released_once = True
        group.outcomes[0].set_result("old result") # Set an old result

        group.reset()
        self.assertEqual(group.count, 0)
        self.assertFalse(group.ready)
        self.assertFalse(group._released_once)
        self.assertEqual(len(group.outcomes), 1)
        self.assertFalse(group.outcomes[0].done) # New outcome should not be done

    def test_reset_creates_new_outcome_objects(self):
        group = Group(threshold=1, tasks=[lambda: None])
        old_outcome = group.outcomes[0]
        group.reset()
        new_outcome = group.outcomes[0]
        self.assertIsNot(old_outcome, new_outcome) # Should be a new object
        self.assertTrue(old_outcome.disposed) # Old outcome should be disposed by reset

    def test_reset_on_disposed_group(self):
        group = Group(threshold=1)
        group.dispose()
        # Reset should do nothing if disposed
        group.reset()
        self.assertTrue(group.disposed)
        self.assertIsNone(group.count) # Should remain None from dispose

    # --- results property Tests ---
    def test_results_no_tasks(self):
        group = Group(threshold=1)
        self.assertEqual(group.results, [])
        group.dispose()

    def test_results_all_successful(self):
        def task1(): return "one"
        def task2(): return 2
        group = Group(threshold=2, tasks=[task1, task2])
        group.outcomes[0].set_result("one")
        group.outcomes[1].set_result(2)
        self.assertCountEqual(group.results, ["one", 2])
        group.dispose()

    def test_results_mixed_outcomes(self):
        def task_ok(): return "OK"
        def task_fail(): raise ValueError("Failed")
        group = Group(threshold=2, tasks=[task_ok, task_fail])
        group.outcomes[0].set_result("OK")
        group.outcomes[1].set_exception(ValueError("Failed"))
        self.assertCountEqual(group.results, ["OK"])
        self.assertEqual(len(group.exceptions), 1) # Check exceptions too
        group.dispose()

    def test_results_empty_if_not_done(self):
        def task_pending(): pass
        group = Group(threshold=1, tasks=[task_pending])
        self.assertEqual(group.results, []) # Not done yet
        group.dispose()

    # --- exceptions property Tests ---
    def test_exceptions_no_tasks(self):
        group = Group(threshold=1)
        self.assertEqual(group.exceptions, [])
        group.dispose()

    def test_exceptions_all_failed(self):
        class CustomError(Exception): pass
        def task1(): raise CustomError("Error1")
        def task2(): raise RuntimeError("Error2")
        group = Group(threshold=2, tasks=[task1, task2])
        group.outcomes[0].set_exception(CustomError("Error1"))
        group.outcomes[1].set_exception(RuntimeError("Error2"))
        excs = group.exceptions
        self.assertEqual(len(excs), 2)
        self.assertIsInstance(excs[0], CustomError)
        self.assertIsInstance(excs[1], RuntimeError)
        group.dispose()

    def test_exceptions_empty_if_not_done(self):
        def task_pending(): pass
        group = Group(threshold=1, tasks=[task_pending])
        self.assertEqual(group.exceptions, []) # Not done yet
        group.dispose()

    def test_exceptions_disposed_outcome_in_list(self):
        # Test case where an outcome might be disposed but still in the list
        group = Group(threshold=1, tasks=[lambda: "result"])
        # Manually dispose the outcome without going through group.dispose()
        group.outcomes[0].dispose()
        # Now, when accessing exceptions, it should handle the disposed outcome gracefully
        # It should NOT include the RuntimeError("Outcome was disposed.")
        self.assertEqual(group.exceptions, [])
        self.assertEqual(group.results, []) # Should also be empty

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
