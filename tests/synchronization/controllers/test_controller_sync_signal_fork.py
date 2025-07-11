import logging
import threading
import time
import unittest
from typing import List
from unittest.mock import MagicMock
from thread_factory import SignalController, SyncSignalFork


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────
def dummy_func_factory(name: str, log: List[str], delay: float = 0.0):
    def _fn():
        if delay:
            time.sleep(delay)
        log.append(name)
    return _fn


def thread_use_fork(fork: SyncSignalFork, log: List[str], tag: str, pre_sleep: float = 0.001):
    try:
        time.sleep(pre_sleep)
        fork.use_fork()
        log.append(f"{tag} executed")
    except RuntimeError as e:
        log.append(f"{tag} runtime: {e}")


# ────────────────────────────────────────────────────────────────────────────
# Integration tests
# ────────────────────────────────────────────────────────────────────────────
class TestControllerWithSyncSignalFork(unittest.TestCase):

    def setUp(self):
        self.log: List[str] = []
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.controller = SignalController(logger=self.mock_logger)

    def tearDown(self):
        if self.controller and not self.controller._disposed:
            self.controller.dispose()

    def _make_fork(self, slots: int, *, manual=False, timeout=None, cb=None):
        return SyncSignalFork(
            number_of_forks=1,
            callables=[(slots, dummy_func_factory("CALL", self.log))],
            manual_release=manual,
            timeout_duration=timeout,
            callback=cb,
            controller=self.controller,
            signal_callback=self.controller.on_wait_starting,
        )

    # 1
    def test_register_fork_success(self):
        fork = self._make_fork(2)
        self.assertIn(fork.id, self.controller._registry)

    # 2
    def test_invoke_reset_command(self):
        fork = self._make_fork(1)
        threading.Thread(target=thread_use_fork, args=(fork, self.log, "T")).start()
        time.sleep(0.05)
        self.controller.invoke(fork.id, "reset")
        self.assertFalse(fork._released)
        self.assertEqual(fork._blocked_thread_count, 0)

    # 3
    def test_manual_release_via_invoke(self):
        fork = self._make_fork(2, manual=True)
        ts = [threading.Thread(target=thread_use_fork, args=(fork, self.log, f"T{i}")) for i in range(2)]
        for t in ts: t.start()
        time.sleep(0.05)
        self.controller.invoke(fork.id, "release")
        for t in ts: t.join(timeout=5)
        self.assertEqual(self.log.count("CALL"), 2)

    # 4
    def test_wait_state_tracking(self):
        fork = self._make_fork(2, manual=True)
        t1 = threading.Thread(target=thread_use_fork, args=(fork, self.log, "A"))
        t1.start()
        time.sleep(0.03)
        self.assertIn(fork.id, self.controller.get_waiting_objects())
        self.controller.invoke(fork.id, "release")
        t1.join(timeout=5)
        self.assertNotIn(fork.id, self.controller.get_waiting_objects())

    # 5
    def test_subscribe_threshold_met_event(self):
        fork = self._make_fork(1)
        cb = MagicMock()
        self.controller.subscribe(fork.id, "THRESHOLD_MET", cb)
        threading.Thread(target=thread_use_fork, args=(fork, self.log, "X")).start()
        time.sleep(0.05)
        cb.assert_called_once()

    # 6
    def test_subscribe_semaphore_released_event(self):
        fork = self._make_fork(1)
        cb = MagicMock()
        self.controller.subscribe(fork.id, "SEMAPHORE_RELEASED", cb)
        threading.Thread(target=thread_use_fork, args=(fork, self.log, "Y")).start()
        time.sleep(0.05)
        cb.assert_called_once()

    # 7
    def test_callback_invoked_without_controller_actions(self):
        marker = []
        fork = self._make_fork(1, cb=lambda: marker.append("FIRED"))
        threading.Thread(target=thread_use_fork, args=(fork, self.log, "Z")).start()
        time.sleep(0.05)
        self.assertIn("FIRED", marker)

    # 8
    def test_broadcast_release(self):
        forks = [self._make_fork(1, manual=True) for _ in range(3)]
        ts = [threading.Thread(target=thread_use_fork, args=(f, self.log, f"S{i}")) for i, f in enumerate(forks)]
        for t in ts: t.start()
        time.sleep(0.05)
        self.controller.invoke_on_all("release")
        for t in ts: t.join(timeout=5)
        self.assertEqual(self.log.count("CALL"), 3)

    # 9
    def test_dispose_controller_disposes_forks(self):
        forks = [self._make_fork(1) for _ in range(2)]
        self.controller.dispose()
        for f in forks:
            self.assertTrue(f._disposed)
    # ------------------------------------------------------------------ #
    # 13 – Invalid command surfaces helpful KeyError
    # ------------------------------------------------------------------ #
    def test_invalid_command_raises_key_error(self):
        fork = self._make_fork(1)
        with self.assertRaisesRegex(KeyError, "has no command 'nope'"):
            self.controller.invoke(fork.id, "nope")

    # ------------------------------------------------------------------ #
    # 14 – name_filter works with invoke_on_all
    # ------------------------------------------------------------------ #
    def test_invoke_on_all_name_filter(self):
        f1 = self._make_fork(1, manual=True)
        f2 = self._make_fork(1, manual=True)
        # tag f2 as “special” so only it should react
        self.controller._registry[f2.id]["name"] = "special_fork"
        self.controller.invoke_on_all("release", name_filter="special_fork")
        self.assertTrue(f2._released)
        self.assertFalse(f1._released)

    # ------------------------------------------------------------------ #
    # 15 – post-hook receives *result* on success
    # ------------------------------------------------------------------ #
    # 15 – post-hook receives *result* on success  (patched: use “release”)
    def test_post_hook_receives_result_value(self):
        fork = self._make_fork(1, manual=True)      # ensure “release” is meaningful
        pre  = MagicMock()
        post = MagicMock()
        self.controller.add_pre_invoke_hook(pre)
        self.controller.add_post_invoke_hook(post)

        # invoke a valid command that returns None
        result = self.controller.invoke(fork.id, "release")

        pre.assert_called_once_with(fork.id, "release")
        post.assert_called_once()
        _, _, res, exc = post.call_args[0]
        self.assertIsNone(res)      # release() returns None
        self.assertIsNone(exc)


    # ------------------------------------------------------------------ #
    # 16 – release on auto-mode fork is a harmless no-op
    # ------------------------------------------------------------------ #
    def test_release_on_auto_fork_is_noop(self):
        fork = self._make_fork(1, manual=False)          # auto-release
        self.controller.invoke(fork.id, "release")       # should not crash
        threading.Thread(target=thread_use_fork,
                         args=(fork, self.log, "Auto")).start()
        time.sleep(0.05)
        self.assertEqual(self.log.count("CALL"), 1)      # callable still ran

    # ------------------------------------------------------------------ #
    # 17 – force-release one fork while another still waits
    # ------------------------------------------------------------------ #
    def test_independent_fork_release(self):
        f_wait = self._make_fork(2, manual=True)
        f_free = self._make_fork(1, manual=True)

        t = threading.Thread(target=thread_use_fork,
                             args=(f_wait, self.log, "Blocker"))
        t.start()
        time.sleep(0.02)  # ensure blocker is waiting

        self.controller.invoke(f_free.id, "release")     # free only f_free
        self.assertTrue(f_free._released)
        self.assertFalse(f_wait._released)

        # clean up
        self.controller.invoke(f_wait.id, "release")
        t.join(timeout=5)

    # ------------------------------------------------------------------ #
    # 18 – on_wait_starting populates waiting list exactly once per thread
    # ------------------------------------------------------------------ #
    def test_wait_starting_logged_once_per_thread(self):
        fork = self._make_fork(2, manual=True)
        before = len(self.controller.get_waiting_objects())
        threads = [threading.Thread(target=thread_use_fork,
                                    args=(fork, self.log, f"W{i}", 0.0))
                   for i in range(2)]
        for t in threads: t.start()
        time.sleep(0.03)
        self.assertEqual(
            len(self.controller.get_waiting_objects()),
            before + 1,   # fork’s ULID appears once, not per thread
        )
        self.controller.invoke(fork.id, "release")
        for t in threads: t.join(timeout=5)

    # 10
    def test_pre_post_hooks_success(self):
        fork = self._make_fork(1)
        pre = MagicMock()
        post = MagicMock()
        self.controller.add_pre_invoke_hook(pre)
        self.controller.add_post_invoke_hook(post)
        self.controller.invoke(fork.id, "reset")
        pre.assert_called_once()
        post.assert_called_once()
        self.assertIsNone(post.call_args[0][2])  # result
        self.assertIsNone(post.call_args[0][3])  # exception

    # 11
    def test_post_hook_on_failure(self):
        fork = self._make_fork(1)
        post = MagicMock()
        self.controller.add_post_invoke_hook(post)
        with self.assertRaises(TypeError):
            self.controller.invoke(fork.id, "reset", bad_kwarg=True)
        self.assertEqual(post.call_count, 1)
        self.assertIsInstance(post.call_args[0][3], TypeError)

    # 12
    def test_timeout_event_flow(self):
        fork = self._make_fork(2, timeout=0.05)
        t = threading.Thread(target=thread_use_fork, args=(fork, self.log, "W"))
        t.start()
        time.sleep(0.08)
        self.assertIn("runtime: SyncSignalFork barrier timed out.", self.log[0])
        self.assertTrue(fork._timed_out)


if __name__ == "__main__":
    unittest.main()
