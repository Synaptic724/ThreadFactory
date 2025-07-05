# tests/agent/identity/test_command_center.py
import threading
import time
import unittest
from concurrent.futures import Future
from thread_factory.agent.command_center import CommandCenter, CC
from thread_factory.agent.identity.activator import AgentActivator
from thread_factory.agent.identity.profiles.general import General
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.iprofile import IProfile


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _no_op() -> str:
    """Simple task for background submission."""
    return "ok"


class CustomProfile(General):
    def __init__(self):
        super().__init__()
        self.custom_flag = True


def custom_profile_factory() -> IProfile:
    return CustomProfile()


# ──────────────────────────────────────────────────────────────────────────
# Test suite
# ──────────────────────────────────────────────────────────────────────────
class TestCommandCenter(unittest.TestCase):
    def setUp(self):
        self.cc = CommandCenter(max_workers=2)

    def tearDown(self):
        try:
            self.cc.shutdown()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Profile-registry facade
    # ------------------------------------------------------------------
    def test_default_profile_present(self):
        self.assertIn("default", self.cc.list_profiles())

    def test_register_and_list_profiles(self):
        self.cc.register_profile("custom", custom_profile_factory)
        self.assertIn("custom", self.cc.list_profiles())

    def test_unregister_profile(self):
        self.cc.register_profile("temp", custom_profile_factory)
        self.assertTrue(self.cc.unregister_profile("temp"))
        self.assertNotIn("temp", self.cc.list_profiles())

    def test_set_default_profile_key(self):
        self.cc.register_profile("alt", custom_profile_factory)
        self.cc.set_default_profile_key("alt")
        # submit without key should now use alt
        fut = self.cc.submit(_no_op)
        fut.result(timeout=1)
        active = self.cc.get_active_agents()
        if active:  # it might finish too quickly
            self.assertIsInstance(active[0].profile, CustomProfile)

    def test_set_default_profile_key_invalid_raises(self):
        with self.assertRaises(KeyError):
            self.cc.set_default_profile_key("missing")

    # ------------------------------------------------------------------
    # submit() behaviour
    # ------------------------------------------------------------------
    def test_submit_callable_returns_result(self):
        fut = self.cc.submit(_no_op)
        self.assertIsInstance(fut, Future)
        self.assertEqual(fut.result(timeout=1), "ok")

    def test_submit_transforms_thread_to_agent(self):
        fut = self.cc.submit(lambda: AgentActivator.is_agent(threading.current_thread()))
        self.assertTrue(fut.result(timeout=1))

    def test_submit_with_custom_profile_key(self):
        self.cc.register_profile("custom", custom_profile_factory)
        fut = self.cc.submit(_no_op, profile_key="custom")
        fut.result(timeout=1)
        acts = self.cc.get_active_agents()
        if acts:
            self.assertIsInstance(acts[0].profile, CustomProfile)

    def test_submit_accepts_pack(self):
        fut = self.cc.submit(Pack.bundle(_no_op))
        self.assertEqual(fut.result(timeout=1), "ok")

    # ------------------------------------------------------------------
    # transform_thread / current
    # ------------------------------------------------------------------
    def test_transform_thread_success(self):
        th = threading.Thread(target=_no_op)
        self.assertTrue(self.cc.transform_thread(th, raise_on_main=False))
        self.assertTrue(AgentActivator.is_agent(th))

    def test_transform_thread_already_agent(self):
        th = threading.Thread(target=_no_op)
        self.cc.transform_thread(th, raise_on_main=False)
        self.assertFalse(self.cc.transform_thread(th, raise_on_main=False))

    def test_transform_thread_main_raises(self):
        with self.assertRaises(RuntimeError):
            self.cc.transform_thread(threading.main_thread())

    def test_transform_current_thread_raises_on_main(self):
        with self.assertRaises(RuntimeError):
            self.cc.transform_current_thread()

    def test_transform_thread_custom_profile(self):
        th = threading.Thread(target=_no_op)
        self.cc.register_profile("cprof", custom_profile_factory)
        self.cc.transform_thread(th, profile_key="cprof", raise_on_main=False)
        self.assertIsInstance(th.profile, CustomProfile)

    # ------------------------------------------------------------------
    # get_active_agents & registry integrity
    # ------------------------------------------------------------------
    def test_get_active_agents_snapshot(self):
        th = threading.Thread(target=_no_op)
        self.cc.transform_thread(th, raise_on_main=False)
        agents = self.cc.get_active_agents()
        self.assertEqual(len(agents), 1)

    def test_get_agent_by_id_valid(self):
        th = threading.Thread(target=_no_op)
        self.cc.transform_thread(th, raise_on_main=False)
        fid = th.factory_id
        self.assertIs(self.cc.get_agent_by_id(fid), th)

    def test_get_agent_by_id_invalid_returns_none(self):
        self.assertIsNone(self.cc.get_agent_by_id("not-real"))

    def test_get_agent_by_id_bad_arg_raises(self):
        with self.assertRaises(ValueError):
            self.cc.get_agent_by_id("")

    # -------------------------------------

if __name__ == '__main__':
    unittest.main()