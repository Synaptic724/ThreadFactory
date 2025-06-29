import unittest
import threading
from thread_factory.primitives.router.router import Router
from thread_factory.utils import RouterGroup


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.lock = threading.Lock()

    def make_action(self, msg):
        def action():
            with self.lock:
                self.logs.append(msg)
        return action

    def start_threads(self, router, group_index, count):
        threads = [
            threading.Thread(target=lambda: router.run(group_index), name=f"worker-{i}")
            for i in range(count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_basic_sync(self):
        group = RouterGroup(threshold=2, actions=[self.make_action("A")])
        router = Router(groups=[group], sync=True)
        router.enable()
        self.start_threads(router, 0, 2)
        router.join()
        self.assertEqual(self.logs.count("A"), 2)

    def test_basic_nonsync(self):
        group = RouterGroup(threshold=2, actions=[self.make_action("B")])
        router = Router(groups=[group], sync=False)
        router.enable()
        self.start_threads(router, 0, 2)
        router.join()
        self.assertEqual(self.logs.count("B"), 1)

    def test_multiple_groups_sequential_execution(self):
        group1 = RouterGroup(threshold=2, actions=[self.make_action("G1")])
        group2 = RouterGroup(threshold=2, actions=[self.make_action("G2")])
        router = Router(groups=[group1, group2], sync=False)
        router.enable()

        # Start group 0
        threads_g0 = self.start_threads(router, 0, 2)
        for t in threads_g0:
            t.join()

        # Then group 1
        threads_g1 = self.start_threads(router, 1, 2)
        for t in threads_g1:
            t.join()

        router.join()
        self.assertIn("G1", self.logs)
        self.assertIn("G2", self.logs)

    def test_stop_on_exception(self):
        def raise_error():
            raise ValueError("fail")
        group = RouterGroup(threshold=2, actions=[raise_error])
        router = Router(groups=[group], stop_on_exception=True, sync=False)
        router.enable()
        self.start_threads(router, 0, 2)
        with self.assertRaises(RuntimeError):
            router.join()

    def test_does_not_stop_on_exception_if_flag_off(self):
        def raise_error():
            raise ValueError("fail")
        group = RouterGroup(threshold=2, actions=[raise_error])
        router = Router(groups=[group], stop_on_exception=False, sync=False)
        router.enable()
        self.start_threads(router, 0, 2)
        try:
            router.join()
        except RuntimeError:
            self.fail("Should not raise when stop_on_exception is False")

    def test_join_after_run_with_no_errors(self):
        group = RouterGroup(threshold=2, actions=[self.make_action("Safe")])
        router = Router(groups=[group])
        router.enable()
        self.start_threads(router, 0, 2)
        router.join()
        self.assertIn("Safe", self.logs)

    def test_multiple_groups_with_mixed_sync_flags(self):
        g1 = RouterGroup(threshold=2, actions=[self.make_action("A")])
        g2 = RouterGroup(threshold=2, actions=[self.make_action("B")])
        router = Router(groups=[g1, g2], sync=False)
        router.enable()
        self.start_threads(router, 0, 2)
        self.start_threads(router, 1, 2)
        router.join()
        self.assertEqual(self.logs.count("A"), 1)
        self.assertEqual(self.logs.count("B"), 1)

    def test_router_dispose_before_execution(self):
        group = RouterGroup(threshold=2, actions=[self.make_action("NoRun")])
        router = Router(groups=[group])
        router.dispose()
        with self.assertRaises(RuntimeError):
            router.run(0)

    def test_router_raises_for_invalid_group_index(self):
        group = RouterGroup(threshold=1, actions=[self.make_action("X")])
        router = Router(groups=[group])
        router.enable()
        result = router.run(99)
        self.assertFalse(result)

    def test_router_handles_no_groups(self):
        router = Router()
        with self.assertRaises(ValueError):
            router.enable()

if __name__ == "__main__":
    unittest.main()