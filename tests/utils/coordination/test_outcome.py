import threading
import time
import unittest
from thread_factory import Outcome


# Assuming the Outcome class is in a file named 'outcome.py'
# For this test, we'll include it directly for self-containment.


class TestOutcome(unittest.TestCase):

    def setUp(self):
        self.outcome = Outcome()

    def tearDown(self):
        # Ensure the outcome is always cleaned, even if a test fails mid-execution
        if not self.outcome.cleaned:
            self.outcome.dispose()

    # --- Initialization Tests ---
    def test_initial_state(self):
        self.assertFalse(self.outcome.done)
        self.assertIsNone(self.outcome._result)
        self.assertIsNone(self.outcome._exception)
        self.assertFalse(self.outcome.cleaned)

    # --- set_result Tests ---
    def test_set_result_success(self):
        self.outcome.set_result("Test Result")
        self.assertTrue(self.outcome.done)
        self.assertEqual(self.outcome.result(), "Test Result")
        self.assertIsNone(self.outcome.exception())

    def test_set_result_idempotency(self):
        self.outcome.set_result("First Result")
        self.outcome.set_result("Second Result") # Should be ignored
        self.assertEqual(self.outcome.result(), "First Result")

    def test_set_result_after_exception(self):
        self.outcome.set_exception(ValueError("Error"))
        self.outcome.set_result("Result") # Should be ignored
        with self.assertRaises(ValueError):
            self.outcome.result()
        self.assertIsInstance(self.outcome.exception(), ValueError)

    def test_set_result_on_cleaned_outcome(self):
        self.outcome.dispose()
        with self.assertRaises(RuntimeError) as cm:
            self.outcome.set_result("Result")
        self.assertIn("Cannot set result on a cleaned Outcome.", str(cm.exception))
        self.assertTrue(self.outcome.cleaned)

    # --- set_exception Tests ---
    def test_set_exception_success(self):
        ex = ValueError("Something went wrong")
        self.outcome.set_exception(ex)
        self.assertTrue(self.outcome.done)
        with self.assertRaises(ValueError):
            self.outcome.result()
        self.assertEqual(self.outcome.exception(), ex)

    def test_set_exception_idempotency(self):
        ex1 = ValueError("First Error")
        ex2 = TypeError("Second Error")
        self.outcome.set_exception(ex1)
        self.outcome.set_exception(ex2) # Should be ignored
        with self.assertRaises(ValueError):
            self.outcome.result()
        self.assertEqual(self.outcome.exception(), ex1)

    def test_set_exception_after_result(self):
        self.outcome.set_result("Result")
        self.outcome.set_exception(ValueError("Error")) # Should be ignored
        self.assertEqual(self.outcome.result(), "Result")
        self.assertIsNone(self.outcome.exception())

    def test_set_exception_on_cleaned_outcome(self):
        self.outcome.dispose()
        with self.assertRaises(RuntimeError) as cm:
            self.outcome.set_exception(ValueError("Error"))
        self.assertIn("Cannot set exception on a cleaned Outcome.", str(cm.exception))
        self.assertTrue(self.outcome.cleaned)

    # --- result() Tests ---
    def test_result_blocks_until_set(self):
        def set_in_thread():
            time.sleep(0.1)
            self.outcome.set_result(42)

        t = threading.Thread(target=set_in_thread)
        t.start()
        start_time = time.monotonic()
        res = self.outcome.result()
        end_time = time.monotonic()
        self.assertEqual(res, 42)
        self.assertGreaterEqual(end_time - start_time, 0.1)
        t.join()

    def test_result_raises_exception(self):
        def set_exception_in_thread():
            time.sleep(0.1)
            self.outcome.set_exception(TypeError("Wrong type"))

        t = threading.Thread(target=set_exception_in_thread)
        t.start()
        with self.assertRaises(TypeError):
            self.outcome.result()
        t.join()

    def test_result_timeout(self):
        with self.assertRaises(TimeoutError):
            self.outcome.result(timeout=0.05)
        self.assertFalse(self.outcome.done)

    def test_result_cleaned_while_waiting(self):
        def dispose_in_thread():
            time.sleep(0.05)
            self.outcome.dispose()

        t = threading.Thread(target=dispose_in_thread)
        t.start()
        with self.assertRaises(RuntimeError) as cm:
            self.outcome.result()
        self.assertIn("Outcome was cleaned", str(cm.exception))
        self.assertTrue(self.outcome.cleaned)
        t.join()

    def test_result_cleaned_before_waiting(self):
        self.outcome.dispose()
        with self.assertRaises(RuntimeError) as cm:
            self.outcome.result()
        self.assertIn("Outcome was cleaned", str(cm.exception))
        self.assertTrue(self.outcome.cleaned)

    # --- done property Tests ---
    def test_done_property(self):
        self.assertFalse(self.outcome.done)
        self.outcome.set_result(1)
        self.assertTrue(self.outcome.done)
        self.setUp() # Reset outcome
        self.assertFalse(self.outcome.done)
        self.outcome.set_exception(Exception())
        self.assertTrue(self.outcome.done)
        self.setUp() # Reset outcome
        self.outcome.dispose()
        self.assertTrue(self.outcome.done)

    # --- exception() Tests ---
    def test_exception_returns_none_on_success(self):
        self.outcome.set_result("OK")
        self.assertIsNone(self.outcome.exception())

    def test_exception_returns_exception_on_failure(self):
        ex = ZeroDivisionError("Div by zero")
        self.outcome.set_exception(ex)
        self.assertEqual(self.outcome.exception(), ex)

    def test_exception_blocks_until_set(self):
        def set_exception_in_thread():
            time.sleep(0.1)
            self.outcome.set_exception(ValueError("Async error"))

        t = threading.Thread(target=set_exception_in_thread)
        t.start()
        start_time = time.monotonic()
        ex = self.outcome.exception()
        end_time = time.monotonic()
        self.assertIsInstance(ex, ValueError)
        self.assertGreaterEqual(end_time - start_time, 0.1)
        t.join()

    def test_exception_cleaned_while_waiting(self):
        def dispose_in_thread():
            time.sleep(0.05)
            self.outcome.dispose()

        t = threading.Thread(target=dispose_in_thread)
        t.start()
        ex = self.outcome.exception()
        self.assertIsInstance(ex, RuntimeError)
        self.assertIn("Outcome was cleaned", str(ex))
        self.assertTrue(self.outcome.cleaned)
        t.join()

    def test_exception_cleaned_before_waiting(self):
        self.outcome.dispose()
        ex = self.outcome.exception()
        self.assertIsInstance(ex, RuntimeError)
        self.assertIn("Outcome was cleaned", str(ex))
        self.assertTrue(self.outcome.cleaned)

    # --- dispose() Tests ---
    def test_dispose_idempotency(self):
        self.assertFalse(self.outcome.cleaned)
        self.outcome.dispose()
        self.assertTrue(self.outcome.cleaned)
        self.outcome.dispose()
        self.assertTrue(self.outcome.cleaned)

    def test_dispose_clears_references(self):
        # Test case 1: Result was set, then cleaned. _result should be None. _exception should be None.
        self.outcome.set_result("data")
        self.outcome.dispose()
        self.assertIsNone(self.outcome._result) # Now asserts None, as per dispose logic
        self.assertIsNone(self.outcome._exception) # Should be None as no exception was set
        self.assertIsNone(self.outcome._condition)

        # Test case 2: Exception was set, then cleaned. _result should be None. _exception should be original.
        self.setUp() # Reset for new test case
        original_ex = ValueError("Test Exception")
        self.outcome.set_exception(original_ex)
        self.outcome.dispose()
        self.assertIsNone(self.outcome._result) # Should be None, as per dispose logic
        self.assertEqual(self.outcome._exception, original_ex) # Should be original exception
        self.assertIsNone(self.outcome._condition)

    def test_dispose_sets_runtime_error_if_not_done(self):
        self.assertFalse(self.outcome.done)
        self.outcome.dispose()
        self.assertTrue(self.outcome.done)
        with self.assertRaises(RuntimeError) as cm:
            self.outcome.result()
        self.assertIn("Outcome was cleaned.", str(cm.exception))
        self.assertIsInstance(self.outcome.exception(), RuntimeError)

    # --- NEW TESTS BELOW ---

    def test_concurrent_set_result_from_multiple_threads(self):
        def worker(value):
            try:
                self.outcome.set_result(value)
            except RuntimeError:
                pass

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(f"Result {i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertTrue(self.outcome.done)
        # Verify that the outcome is done and has a result (one of the attempted ones)
        # We cannot reliably assert len(results) == 1 without changing Outcome API
        # to indicate if set_result actually changed state.
        # The idempotency is handled by Outcome itself.
        try:
            final_result = self.outcome.result()
            self.assertIn(final_result, [f"Result {i}" for i in range(5)])
        except RuntimeError as e:
            # If dispose somehow won the race, result() might raise RuntimeError
            self.assertIn("Outcome was cleaned", str(e))
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")


    def test_concurrent_set_exception_from_multiple_threads(self):
        class TestException(Exception): pass

        def worker(ex_msg):
            try:
                self.outcome.set_exception(TestException(ex_msg))
            except RuntimeError:
                pass

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(f"Error {i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertTrue(self.outcome.done)
        final_exception = self.outcome.exception()
        self.assertIsInstance(final_exception, TestException)
        self.assertIn(str(final_exception), [f"Error {i}" for i in range(5)])

    def test_concurrent_set_result_and_exception(self):
        def set_result_worker():
            try:
                self.outcome.set_result("Success")
            except RuntimeError:
                pass

        def set_exception_worker():
            try:
                self.outcome.set_exception(ValueError("Failure"))
            except RuntimeError:
                pass

        t1 = threading.Thread(target=set_result_worker)
        t2 = threading.Thread(target=set_exception_worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(self.outcome.done)
        if self.outcome.exception() is None:
            self.assertEqual(self.outcome.result(), "Success")
        else:
            self.assertIsInstance(self.outcome.exception(), ValueError)
            with self.assertRaises(ValueError):
                self.outcome.result()

    def test_dispose_during_concurrent_set_operations(self):
        def set_result_worker():
            try:
                self.outcome.set_result("Result")
            except RuntimeError:
                pass

        def dispose_worker():
            time.sleep(0.01)
            self.outcome.dispose()

        t1 = threading.Thread(target=set_result_worker)
        t2 = threading.Thread(target=dispose_worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(self.outcome.cleaned)
        self.assertTrue(self.outcome.done)

        try:
            # If set_result won, result() might return "Result"
            # If dispose won, result() will raise RuntimeError
            result_val = self.outcome.result(timeout=0.01)
            self.assertEqual(result_val, "Result")
            self.assertIsNone(self.outcome.exception())
        except RuntimeError as e:
            self.assertIn("Outcome was cleaned", str(e))
            self.assertIsInstance(self.outcome.exception(), RuntimeError)
        except TimeoutError:
            self.fail("Outcome did not complete within expected time.")
        except Exception as e:
            self.fail(f"Unexpected exception raised: {e}")

    def test_result_with_timeout_and_concurrent_dispose(self):
        def dispose_worker():
            time.sleep(0.05)
            self.outcome.dispose()

        t = threading.Thread(target=dispose_worker)
        t.start()

        start_time = time.monotonic()
        with self.assertRaises(RuntimeError) as cm:
            self.outcome.result(timeout=0.5)
        end_time = time.monotonic()

        self.assertIn("Outcome was cleaned", str(cm.exception))
        self.assertTrue(self.outcome.cleaned)
        self.assertGreaterEqual(end_time - start_time, 0.05)
        self.assertLess(end_time - start_time, 0.5)

        t.join()

    def test_exception_with_timeout_and_concurrent_dispose(self):
        def dispose_worker():
            time.sleep(0.05)
            self.outcome.dispose()

        t = threading.Thread(target=dispose_worker)
        t.start()

        start_time = time.monotonic()
        ex = self.outcome.exception()
        end_time = time.monotonic()

        self.assertIsInstance(ex, RuntimeError)
        self.assertIn("Outcome was cleaned", str(ex))
        self.assertTrue(self.outcome.cleaned)
        self.assertGreaterEqual(end_time - start_time, 0.05)

        t.join()

    def test_dispose_clears_result_if_exception_was_set_first(self):
        original_exception = ValueError("Original Error")
        self.outcome.set_exception(original_exception)
        self.outcome.dispose()
        # _result is None. So result() will raise original exception.
        with self.assertRaises(ValueError):
            self.outcome.result()
        # _exception should still be the original exception.
        self.assertEqual(self.outcome.exception(), original_exception)

    def test_result_access_after_set_and_dispose(self):
        self.outcome.set_result("Final Value")
        self.outcome.dispose()
        # After dispose, _result is None. So result() will raise RuntimeError.
        with self.assertRaises(RuntimeError) as cm:
            self.outcome.result()
        self.assertIn("Outcome was cleaned.", str(cm.exception))
        self.assertTrue(self.outcome.done)
        self.assertTrue(self.outcome.cleaned)

    def test_exception_access_after_set_and_dispose(self):
        original_ex = TypeError("Specific Error")
        self.outcome.set_exception(original_ex)
        self.outcome.dispose()
        # _exception should still be the original exception.
        self.assertEqual(self.outcome.exception(), original_ex)
        self.assertTrue(self.outcome.done)
        self.assertTrue(self.outcome.cleaned)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)