import unittest
import threading
import time
from thread_factory.agent.identity.utilities.location_map import LocationMap  # Adjust import if needed


class FakeAgent:
    """
    A minimal stand-in for an agent.
    Only provides `_disposed` and `_logger`.
    """
    def __init__(self):
        self._disposed = False
        self.log = []

    def log_call(self, message: str):
        self.log.append(message)


class TestLocationMap(unittest.TestCase):
    def setUp(self):
        self.agent = FakeAgent()
        self.location_map = LocationMap(agent=self.agent)

    def tearDown(self):
        self.location_map.dispose()

    def test_register_and_transit_to_location(self):
        called = []

        def location_task():
            called.append("entered")
            return "finished"

        self.location_map.register_location("start", location_task)
        result = self.location_map.transit_to("start")

        self.assertEqual(result, "finished")
        self.assertEqual(called, ["entered"])
        self.assertEqual(self.location_map.peek_stack(), None)

    def test_stack_trace_and_depth(self):
        def location_one():
            self.assertEqual(self.location_map.stack_depth(), 1)
            self.assertIn("one", self.location_map.trace_stack())

        self.location_map.register_location("one", location_one)
        self.location_map.transit_to("one")

    def test_transit_internal(self):
        def internal_logic():
            self.assertEqual(self.location_map.stack_depth(), 1)
            self.assertIn("[system:internal_loop]", self.location_map.trace_stack())

        self.location_map.transit_internal("internal_loop", internal_logic)
        self.assertEqual(self.location_map.stack_depth(), 0)

    def test_concurrent_thread_lifecycle(self):
        def lifeloop():
            self.location_map.register_location("run", lambda: self.location_map.trace_stack())
            for _ in range(3):
                self.location_map.transit_to("run")
                time.sleep(0.01)

        t = threading.Thread(target=lifeloop)
        t.start()
        t.join(timeout=2)

        self.assertEqual(self.location_map.stack_depth(), 0)
        self.assertTrue("run" in self.location_map.get_locations())

    def test_missing_location_raises(self):
        with self.assertRaises(KeyError):
            self.location_map.transit_to("nonexistent")

    def test_dispose_blocks_registration(self):
        self.location_map.dispose()
        with self.assertRaises(RuntimeError):
            self.location_map.register_location("x", lambda: None)

    def test_get_stack_output_type(self):
        self.location_map.register_location("foo", lambda: None)
        self.location_map.transit_to("foo")
        result = self.location_map.get_stack()
        self.assertTrue(hasattr(result, "to_list") or isinstance(result, list))

    def test_register_overwrites_existing_location(self):
        """
        If a location is registered with the same name twice, it should overwrite the previous.
        """
        call_log = []

        def original():
            call_log.append("original")

        def new():
            call_log.append("new")

        self.location_map.register_location("task", original)
        self.location_map.register_location("task", new)

        self.location_map.transit_to("task")
        self.assertEqual(call_log, ["new"])

    def test_stack_is_clean_after_failure(self):
        """
        Even if the location throws, the stack must be popped cleanly.
        """
        def crashing_location():
            raise ValueError("boom")

        self.location_map.register_location("fail", crashing_location)

        with self.assertRaises(ValueError):
            self.location_map.transit_to("fail")

        self.assertEqual(self.location_map.stack_depth(), 0)

    def test_stack_trace_order(self):
        """
        Ensure stack trace prints in correct execution order.
        """
        def inner():
            trace = self.location_map.trace_stack()
            self.assertEqual(trace, "outer → inner")

        def outer():
            self.location_map.register_location("inner", inner)
            return self.location_map.transit_to("inner")

        self.location_map.register_location("outer", outer)
        self.location_map.transit_to("outer")

    def test_peek_stack_behavior(self):
        """
        Peek should reflect correct top value at each stage.
        """
        self.location_map.register_location("alpha", lambda: self.assertEqual(self.location_map.peek_stack(), "alpha"))
        self.assertIsNone(self.location_map.peek_stack())  # before transition
        self.location_map.transit_to("alpha")
        self.assertIsNone(self.location_map.peek_stack())  # after transition (stack should be clean)

    def test_dispose_multiple_times_safe(self):
        """
        Calling dispose() more than once should not error.
        """
        self.location_map.dispose()
        self.location_map.dispose()  # no crash

    def test_transit_to_nested_internal_and_user(self):
        """
        Mixing internal and user transitions should preserve stack logic.
        """
        def system_layer():
            self.location_map.register_location("core", lambda: self.assertIn("[system:main] → core", self.location_map.trace_stack()))
            self.location_map.transit_to("core")

        self.location_map.transit_internal("main", system_layer)
        self.assertEqual(self.location_map.stack_depth(), 0)

    def test_concurrent_location_register_and_transit(self):
        """
        Stress test multiple threads registering and calling locations.
        """
        def echo(i):
            return lambda: f"value-{i}"

        threads = []
        results = []
        lock = threading.Lock()

        def worker(i):
            name = f"loc_{i}"
            self.location_map.register_location(name, echo(i))
            result = self.location_map.transit_to(name)
            with lock:
                results.append(result)

        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=1)

        self.assertEqual(len(results), 10)
        for i in range(10):
            self.assertIn(f"value-{i}", results)

    def test_trace_empty_stack(self):
        """
        Trace should return an empty string if nothing is on the stack.
        """
        self.assertEqual(self.location_map.trace_stack(), "")

    def test_stack_depth_matches_manual_push_pop(self):
        """
        Depth should reflect true stack state across transitions.
        """
        self.location_map.register_location("foo", lambda: self.assertEqual(self.location_map.stack_depth(), 1))
        self.assertEqual(self.location_map.stack_depth(), 0)
        self.location_map.transit_to("foo")
        self.assertEqual(self.location_map.stack_depth(), 0)

    def test_get_returns_correct_callable(self):
        """
        LocationMap.get() should return the correct Pack for known keys.
        """
        fn = lambda: 42
        self.location_map.register_location("answer", fn)
        result = self.location_map.get("answer")
        self.assertTrue(callable(result))
        self.assertEqual(result(), 42)

    def test_lifecycle_loop_stack_trace_and_depth(self):
        """
        Simulates a realistic loop of transitions across multiple registered locations,
        verifying that:
        - stack_depth is accurate at each stage
        - trace_stack returns proper formatted output
        - transitions execute expected logic
        - stack is cleaned after each cycle
        """

        trace_log = []

        def entry():
            self.assertEqual(self.location_map.stack_depth(), 1)
            trace_log.append(f"trace@entry: {self.location_map.trace_stack()}")
            self.location_map.transit_to("middle")

        def middle():
            self.assertEqual(self.location_map.stack_depth(), 2)
            trace_log.append(f"trace@middle: {self.location_map.trace_stack()}")
            self.location_map.transit_to("deep")

        def deep():
            self.assertEqual(self.location_map.stack_depth(), 3)
            trace_log.append(f"trace@deep: {self.location_map.trace_stack()}")

        # Register locations
        self.location_map.register_location("entry", entry)
        self.location_map.register_location("middle", middle)
        self.location_map.register_location("deep", deep)

        for i in range(3):  # Run a full loop 3 times
            self.location_map.transit_to("entry")
            self.assertEqual(self.location_map.stack_depth(), 0)  # Ensure cleaned after

        # Check traces are all present and properly layered
        self.assertEqual(len(trace_log), 9)
        self.assertTrue(all("entry" in s for s in trace_log[0::3]))
        self.assertTrue(all("middle" in s for s in trace_log[1::3]))
        self.assertTrue(all("deep" in s for s in trace_log[2::3]))

        # Print captured stack traces for debugging
        for i, trace in enumerate(trace_log, 1):
            print(f"[Trace {i}] {trace}")

    def test_register_locations_bulk(self):
        """
        Ensure multiple locations are registered via register_locations().
        """
        flags = {"a": False, "b": False}

        def a(): flags["a"] = True
        def b(): flags["b"] = True

        self.location_map.register_locations({
            "loc_a": a,
            "loc_b": b
        })

        self.location_map.transit_to("loc_a")
        self.location_map.transit_to("loc_b")

        self.assertTrue(flags["a"])
        self.assertTrue(flags["b"])

    def test_register_locations_handles_overwrite(self):
        """
        register_locations should overwrite existing keys like register_location.
        """
        log = []

        self.location_map.register_location("task", lambda: log.append("old"))
        self.location_map.register_locations({
            "task": lambda: log.append("new")
        })

        self.location_map.transit_to("task")
        self.assertEqual(log, ["new"])

    def test_register_locations_rejects_after_dispose(self):
        """
        Disposed LocationMap should not allow batch registration.
        """
        self.location_map.dispose()
        with self.assertRaises(RuntimeError):
            self.location_map.register_locations({"x": lambda: None})

    def test_register_locations_with_invalid_value_raises(self):
        """
        If one of the values in the map is invalid (not callable or Pack), should raise early.
        """
        class NotCallable: pass

        with self.assertRaises(TypeError):
            self.location_map.register_locations({
                "ok": lambda: 123,
                "bad": NotCallable()
            })


if __name__ == "__main__":
    unittest.main()