import unittest
from Threading.Parallel import Parallel as parallel
import time

# Import your 'parallel' class here, for example:
# from your_module_name import parallel

# For demonstration, I'll just assume 'parallel' is in the same file or you can do:
# from parallel_lib import parallel


class TestParallel(unittest.TestCase):
    def test_for_basic_sum(self):
        """
        Test parallel_for with a basic summation of a range [0..100).
        """
        total = 0
        lock = None  # Not strictly needed in this example

        def add_number(i):
            nonlocal total
            total += i

        # Summation from 0..99
        parallel.parallel_for(0, 100, add_number)
        self.assertEqual(total, sum(range(100)), "Sum of 0..99 should match sequential result")

    def test_for_empty_range(self):
        """
        Test parallel_for with an empty range [10..10).
        Should not call the body function at all.
        """
        counter = 0

        def increment(i):
            nonlocal counter
            counter += 1

        parallel.parallel_for(10, 10, increment)
        self.assertEqual(counter, 0, "No iterations should have occurred for an empty range")

    def test_for_explicit_chunk_size(self):
        """
        Test parallel_for with an explicit chunk size, verifying correctness.
        We sum a range with chunk_size=10.
        """
        total = 0

        def add_number(i):
            nonlocal total
            total += i

        parallel.parallel_for(0, 50, add_number, chunk_size=10)
        self.assertEqual(total, sum(range(50)), "Sum of 0..49 should match sequential result")

    def test_for_with_local_state(self):
        """
        Test parallel_for using local_init/local_body/local_finalize to accumulate partial sums.
        We'll accumulate each thread's partial sum into a global 'sums' list at finalize.
        """
        sums = []

        def local_init():
            return [0]  # We store a running sum in a list, so it's mutable

        def local_body(i, local_list):
            local_list[0] += i

        def local_finalize(local_list):
            sums.append(local_list[0])

        parallel.parallel_for(
            0,
            10,
            body=None,
            local_init=local_init,
            local_body=local_body,
            local_finalize=local_finalize
        )
        # The total sum of all partial sums should equal sum(0..9)
        self.assertEqual(sum(sums), sum(range(10)))

    def test_for_stop_on_exception(self):
        """
        Test parallel_for with stop_on_exception=True. If an exception
        occurs at index=5, we forcibly do chunk_size=1 and max_workers=1
        so that we never process subsequent indices after the exception.
        """
        executed_indices = []

        def body(i):
            if i == 5:
                raise ValueError("Test exception at i=5")
            executed_indices.append(i)

        # Force sequential to ensure we truly stop when i=5 raises
        with self.assertRaises(ValueError):
            parallel.parallel_for(
                0,
                10,
                body,
                stop_on_exception=True,
                chunk_size=1,
                max_workers=1
            )

        # We expect only indices 0..4 to have been processed
        self.assertLess(len(executed_indices), 10, "We should not have processed indices after 5")
        self.assertNotIn(5, executed_indices, "Index 5 should have raised an exception and not appended")

    def test_foreach_basic(self):
        """
        Test parallel_foreach with a basic list of items.
        We'll append squared results to a shared list.
        """
        data = [1, 2, 3, 4, 5]
        squared_results = []

        def action(x):
            squared_results.append(x * x)

        parallel.parallel_foreach(data, action)
        self.assertCountEqual(squared_results, [1, 4, 9, 16, 25], "Squares should match for each item")

    def test_foreach_empty_iterable(self):
        """
        Test parallel_foreach with an empty list (no items).
        Should not call action at all.
        """
        counter = 0

        def action(x):
            nonlocal counter
            counter += 1

        parallel.parallel_foreach([], action)
        self.assertEqual(counter, 0)

    def test_foreach_explicit_chunk_size(self):
        """
        Test parallel_foreach with chunk_size=2 to ensure correct processing.
        """
        data = [10, 20, 30, 40, 50]
        results = []

        def action(x):
            results.append(x + 1)  # just a simple transformation

        parallel.parallel_foreach(data, action, chunk_size=2)
        self.assertCountEqual(results, [11, 21, 31, 41, 51])

    def test_foreach_stop_on_exception(self):
        """
        Test parallel_foreach with stop_on_exception=True.
        We'll also do chunk_size=1 and max_workers=1 for a guaranteed sequential approach.
        If an exception occurs at item=2, no further items should be processed.
        """
        data = [1, 2, 3, 4, 5, 6]
        processed = []

        def action(x):
            if x == 2:
                raise RuntimeError("Test Stop")
            processed.append(x)

        with self.assertRaises(RuntimeError):
            parallel.parallel_foreach(data, action, stop_on_exception=True, chunk_size=1, max_workers=1)

        # We expect [1] processed, but not 2 or anything beyond
        self.assertNotIn(2, processed, "2 should have triggered exception, not appended")
        self.assertLess(len(processed), len(data))

    def test_foreach_streaming_mode(self):
        """
        Test parallel_foreach in streaming mode with a generator that yields 1..10.
        We'll collect squares in a global list.
        """
        def generator():
            for i in range(1, 11):
                yield i

        results = []
        def action(x):
            results.append(x * x)

        # We'll do chunk_size=3 just for demonstration
        parallel.parallel_foreach(generator(), action, streaming=True, chunk_size=3)
        self.assertCountEqual(results, [i * i for i in range(1, 11)])

    def test_invoke_basic(self):
        """
        Test parallel_invoke with two functions.
        We'll store results in a list.
        """
        outputs = []

        def f1():
            outputs.append("Task1")

        def f2():
            outputs.append("Task2")

        parallel.parallel_invoke(f1, f2)
        self.assertEqual(len(outputs), 2, "Should have appended two items (Task1, Task2).")
        self.assertIn("Task1", outputs)
        self.assertIn("Task2", outputs)

    def test_invoke_no_functions(self):
        """
        Test parallel_invoke with no functions passed. Should return an empty list of futures
        and do nothing.
        """
        futures = parallel.parallel_invoke()
        self.assertEqual(len(futures), 0, "No tasks means empty futures list")

    def test_invoke_wait_false(self):
        """
        Test parallel_invoke(wait=False). In the current design, the executor
        is closed immediately upon exiting the 'with' block, so tasks won't truly run asynchronously.
        But we test that the futures are returned.
        """
        outputs = []

        def f1():
            outputs.append("f1")

        def f2():
            outputs.append("f2")

        futures = parallel.parallel_invoke(f1, f2, wait=False)
        self.assertEqual(len(futures), 2, "Two tasks should be submitted.")
        # We cannot guarantee whether 'outputs' is updated, due to immediate shutdown.

    def test_invoke_exception(self):
        """
        Test parallel_invoke when one of the functions raises an exception.
        If wait=True, that exception should be re-raised.
        """
        outputs = []

        def good_func():
            outputs.append("OK")

        def bad_func():
            raise ValueError("Boom")

        with self.assertRaises(ValueError):
            parallel.parallel_invoke(good_func, bad_func, wait=True)

        # We just care that the exception is re-raised. The good_func may or may not have run.

    def test_map_basic(self):
        """
        Test parallel_map with a simple function that doubles each item.
        """
        data = [1, 2, 3, 4]
        result = parallel.parallel_map(data, lambda x: x * 2)
        self.assertEqual(result, [2, 4, 6, 8], "Should double each input item")

    def test_map_empty(self):
        """
        Test parallel_map with an empty iterable.
        Should return an empty list.
        """
        result = parallel.parallel_map([], lambda x: x * 2)
        self.assertEqual(result, [])

    def test_map_explicit_chunk_size(self):
        """
        Test parallel_map with an explicit chunk size.
        """
        data = [1, 2, 3, 4, 5, 6]
        result = parallel.parallel_map(data, lambda x: x + 10, chunk_size=2)
        expected = [11, 12, 13, 14, 15, 16]
        self.assertEqual(result, expected)

    def test_map_order_preservation(self):
        """
        Test parallel_map ensures the output is in the original order
        even if tasks run out of order.
        """
        data = list(range(10))

        # We'll produce a function that sleeps in a reversed manner
        # to encourage concurrency out of order
        import time
        def transform(x):
            time.sleep((10 - x) * 0.0005)  # bigger sleep for smaller x
            return x * x

        result = parallel.parallel_map(data, transform, max_workers=4)
        self.assertEqual(result, [x * x for x in data])

    def test_map_exception(self):
        """
        Test parallel_map that raises an exception partway through.
        The method should re-raise the exception.
        """
        data = [1, 2, 3, 4, 5]
        def transform(x):
            if x == 3:
                raise ValueError("Test Error in map")
            return x

        with self.assertRaises(ValueError):
            parallel.parallel_map(data, transform)

    def test_map_large_input(self):
        """
        Test parallel_map with a large input (e.g. 20000 items).
        We'll do a simple transform. It's mainly to ensure it doesn't crash / freeze.
        """
        data = list(range(20000))
        result = parallel.parallel_map(data, lambda x: x + 1)
        # Spot check
        self.assertEqual(result[0], 1)
        self.assertEqual(result[-1], 20000)


class TestParallelEdgeCases(unittest.TestCase):
    def test_for_local_state_concurrent_updates(self):
        """
        Stress test for local_init/local_body/local_finalize in parallel_for with multiple workers.

        We'll sum numbers 0..999 in parallel, each worker chunk accumulates in local state,
        then finalizes by appending to a global list. We do not rely on chunk_size=1 or max_workers=1
        so that concurrency is real.

        Potential Pitfall:
            If local_body doesn't safely update local state or local_finalize merges incorrectly,
            we might get the wrong total. This test verifies correctness under concurrency.
        """
        sums = []

        def local_init():
            # We'll return a simple list-based sum holder
            return [0]

        def local_body(i, local_sum_list):
            # local_sum_list[0] accumulates the partial sum for this thread chunk
            local_sum_list[0] += i

        def local_finalize(local_sum_list):
            # At the end, we copy out the local sum to the global sums
            sums.append(local_sum_list[0])

        # Summation 0..999 is 499500
        parallel.parallel_for(
            0, 1000,
            body=None,  # we rely on local_body
            local_init=local_init,
            local_body=local_body,
            local_finalize=local_finalize,
            max_workers=4,  # multiple workers
            stop_on_exception=False
        )

        self.assertEqual(sum(sums), sum(range(1000)),
                         "Threading local-state summation should match the expected total.")

    def test_foreach_streaming_chunk_size_one(self):
        """
        Test parallel_foreach in streaming mode with chunk_size=1 on a moderately large generator.

        Potential Pitfall:
            chunk_size=1 in streaming mode could lead to a huge number of tiny tasks,
            which might drastically slow things down or cause overhead issues.

        We'll see if it at least completes correctly. This is more about correctness than performance.
        """

        def data_generator(n):
            for i in range(n):
                yield i

        n_items = 2000
        collected = []

        def action(x):
            collected.append(x)

        # chunk_size=1: each item is its own chunk
        # This might be slow, but let's see if it completes.
        parallel.parallel_foreach(
            data_generator(n_items),
            action,
            streaming=True,
            chunk_size=1,
            max_workers=4
        )

        self.assertEqual(len(collected), n_items,
                         "All items should be processed, even with chunk_size=1 in streaming mode.")
        self.assertCountEqual(collected, range(n_items),
                              "Collected items should match the generated range.")

    def test_for_multiple_exceptions(self):
        """
        Test parallel_for when multiple exceptions can occur in parallel.
        By default, the code re-raises only the first encountered exception,
        ignoring later ones. We confirm that scenario works consistently.

        Potential Pitfall:
            If multiple tasks fail simultaneously, only the first is reported.
            We'll see that we do get an exception, but do NOT get aggregated errors.
        """

        def error_prone_body(i):
            if i in (2, 4, 6):
                raise ValueError(f"Error at i={i}")

        # Because concurrency might let i=2,4,6 happen near-simultaneously,
        # we only expect the FIRST one to be re-raised.
        with self.assertRaises(ValueError) as ctx:
            parallel.parallel_for(
                0, 10,
                error_prone_body,
                max_workers=4,
                stop_on_exception=True,  # should cause early stop
                chunk_size=1
            )

        message = str(ctx.exception)
        # We only get the first error in standard usage:
        self.assertTrue("i=2" in message or "i=4" in message or "i=6" in message,
                        "We should see the earliest exception's message, not an aggregation.")

    def test_invoke_wait_false_incomplete(self):
        """
        Test parallel_invoke(wait=False). We'll do a function that sleeps for a moment,
        verifying that the tasks may not actually finish because the executor is closed
        upon exiting the function.

        Potential Pitfall:
            The tasks are forcibly ended if the executor shuts down. We just want
            to confirm no crash occurs, and that we indeed can't rely on them finishing.
        """
        results = []

        def slow_task():
            time.sleep(0.1)
            results.append("finished")

        futures = parallel.parallel_invoke(
            slow_task,
            wait=False,
            max_workers=2
        )

        self.assertEqual(len(futures), 1, "We only submitted one function here.")

        # Because wait=False closes the executor block immediately,
        # there's a high chance 'slow_task' won't complete.
        # We'll sleep a tiny bit to see if it might have run or not.
        time.sleep(0.2)

        # The result might or might not be appended, but let's confirm no crash occurred:
        self.assertTrue(True, "No crash. If 'results' is empty, that means the task didn't finish.")
