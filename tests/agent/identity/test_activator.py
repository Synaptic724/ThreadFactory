import threading
import unittest
from typing import Any
from unittest import TestCase
from thread_factory.agent.identity.profiles.base import BaseProfile
from thread_factory.agent.identity.activator import AgentActivator
from thread_factory.agent.identity.profiles.general import General


def _no_op() -> None:
    """Simple target for thread initialization."""
    pass


class TestAgentActivatorWithGeneralProfile(unittest.TestCase):
    """Unit tests for AgentActivator in conjunction with the General profile."""

    def setUp(self) -> None:
        """Create a thread, profile, and activator, then patch the thread."""
        self.thread = threading.Thread(target=_no_op)
        self.profile = General()
        self.activator = AgentActivator(self.profile, self.thread)
        self.activator._patch()  # Apply profile methods/fields to the thread

    def tearDown(self) -> None:
        """Dispose the activator and join the thread if needed."""
        self.activator.dispose()

    # ──────────────────────────────────────────────────────────────────────
    # Basic Binding Assertions
    # ──────────────────────────────────────────────────────────────────────
    def test_profile_is_attached(self) -> None:
        """Validate that the profile field is present and correct."""
        self.assertIs(self.thread.profile, self.profile)
        self.assertEqual(self.thread.profile.get_description(),
                         f"Agent {self.thread.profile.get_name()} with job '{self.profile.job}' in group '{self.profile.group}'")

    def test_methods_are_patched(self) -> None:
        """Ensure key General methods are accessible on the thread."""
        self.assertTrue(callable(getattr(self.thread, "bind_to_inventory", None)))
        self.assertTrue(callable(getattr(self.thread, "get_from_inventory", None)))
        self.assertTrue(callable(getattr(self.thread, "set_shared_inventory_item", None)))
        self.assertTrue(callable(getattr(self.thread, "get_shared_inventory_item", None)))

    # ──────────────────────────────────────────────────────────────────────
    # Inventory Operations
    # ──────────────────────────────────────────────────────────────────────
    def test_private_inventory_roundtrip(self) -> None:
        """Store and retrieve a value from the private inventory."""
        self.thread.bind_to_inventory("key", 123)
        self.assertEqual(self.thread.get_from_inventory("key"), 123)

    def test_shared_inventory_roundtrip(self) -> None:
        """Store and retrieve a value in the shared inventory."""
        self.thread.set_shared_inventory_item("global", "value")
        self.assertEqual(self.thread.get_shared_inventory_item("global"), "value")

        # ──────────────────────────────────────────────────────────────────────────
        # Additional tests ‒ paste below the previous ones (same class is OK)
        # ──────────────────────────────────────────────────────────────────────────

    # Inventory: missing-key behaviour
    def test_private_inventory_missing_key_returns_default(self) -> None:
        """Accessing an unknown private key yields the provided default."""
        self.assertIsNone(self.thread.get_from_inventory("missing"))
        self.assertEqual(self.thread.get_from_inventory("missing", 99), 99)

    # Data-transfer registration & execution
    def test_data_transfer_registration_and_execution(self) -> None:
        """Register a data-transfer callable and ensure it executes correctly."""

        def _transfer():
            return "payload"

        self.thread.profile.register_data_transfer("tx", _transfer)
        self.assertIn("tx", self.thread.profile.get_data_transfer_dict())
        self.assertEqual(self.thread.profile.execute_transfer("tx"), "payload")

    # Dispose idempotency
    def test_dispose_is_idempotent(self) -> None:
        """Calling dispose() twice should not raise and leaves activator disposed."""
        self.activator.dispose()
        # second call should be a no-op
        self.activator.dispose()
        self.assertTrue(self.activator._disposed)

    # Patch record accuracy
    def test_patched_fields_recorded_and_cleared(self) -> None:
        """
        _patched_fields should contain injected attribute names while active
        and be cleared after unpatch.
        """
        initial = set(self.activator._patched_fields)
        self.assertIn("bind_to_inventory", initial)
        self.assertIn("profile", initial)

        self.activator.dispose()
        self.assertEqual(self.activator._patched_fields, [])

    # ──────────────────────────────────────────────────────────────────────
    # Save Points & Locations
    # ──────────────────────────────────────────────────────────────────────
    def test_save_point_registration_and_execution(self) -> None:
        """Register a save point and invoke it."""
        called: dict[str, Any] = {}

        def _save() -> None:
            called["flag"] = True

        self.thread.profile.register_save_point("checkpoint", _save)
        self.assertIn("checkpoint", self.thread.profile.get_save_points_dict())
        self.thread.profile.save_points["checkpoint"]()
        self.assertTrue(called.get("flag"))

    def test_location_registration_and_execution(self) -> None:
        """Register a location and invoke it."""
        called: dict[str, Any] = {}

        def _loc() -> None:
            called["loc"] = 1

        self.thread.profile.register_location("alpha", _loc)
        self.assertIn("alpha", self.thread.profile.get_locations_dict())
        self.thread.profile.locations["alpha"]()
        self.assertEqual(called.get("loc"), 1)

    # ──────────────────────────────────────────────────────────────────────
    # Unpatch / Dispose
    # ──────────────────────────────────────────────────────────────────────
    def test_unpatch_on_dispose(self) -> None:
        """Ensure dispose removes dynamic attributes from the thread."""
        self.activator.dispose()
        self.assertFalse(hasattr(self.thread, "profile"))
        self.assertFalse(hasattr(self.thread, "bind_to_inventory"))
        self.assertTrue(self.activator._disposed)

# ---------------------------------------------------------------------------
# EXTRA UNIT TESTS ‒ append to your existing test_activator.py file
# ---------------------------------------------------------------------------


class _StubCommandCenter:
    """Minimal stub just for _resolve_worker_by_id tests."""
    def __init__(self, mapping):
        self._mapping = mapping

    def get_agent_by_id(self, fid):
        return self._mapping.get(fid)


class TestBaseProfileAndActivatorInternals(TestCase):
    # ──────────────────────────────────────────────────────────────────────
    # BaseProfile core
    # ──────────────────────────────────────────────────────────────────────
    def setUp(self):
        self.base = BaseProfile()
        self.gen1 = General()
        self.gen2 = General()
        self.thread1 = threading.Thread(target=_no_op)
        self.thread2 = threading.Thread(target=_no_op)
        self.act1 = AgentActivator(self.gen1, self.thread1)
        self.act2 = AgentActivator(self.gen2, self.thread2)
        self.act1._patch()
        self.act2._patch()

    def tearDown(self):
        self.act1.dispose()
        self.act2.dispose()

    def test_factory_id_unique(self):
        self.assertNotEqual(self.base.factory_id, BaseProfile().factory_id)

    def test_get_factory_id(self):
        fid = self.base.factory_id
        self.assertTrue(isinstance(fid, str) and len(fid) == 26)

    def test_default_name_and_description(self):
        self.assertEqual(self.base.get_name(), "This is a BaseProfile, and thus is nameless.")
        self.assertTrue("purpose is to provide a base" in self.base.get_description())

    def test_bind_to_and_unbind(self):
        self.base.bind_to(self.act1)
        self.assertTrue(self.base.is_bound)
        self.base.unbind()
        self.assertFalse(self.base.is_bound)

    def test_bind_to_double_bind_raises(self):
        self.base.bind_to(self.act1)
        with self.assertRaises(RuntimeError):
            self.base.bind_to(self.act1)

    def test_bind_to_invalid_type(self):
        with self.assertRaises(TypeError):
            self.base.bind_to(object())  # not an AgentActivator/Agent

    def test_repr_and_str_include_factory_id(self):
        rep = repr(self.base)
        self.assertIn(self.base.factory_id, rep)
        self.assertTrue(str(self.base).startswith("AgentActivator<"))

    def test_bind_essentials_sets_refs(self):
        dummy = AgentActivator(self.gen1, self.thread1)
        self.base.bind_essentials(self.thread1, "CC", dummy)
        self.assertIs(self.base._thread_target, self.thread1)
        self.assertEqual(self.base._command_center, "CC")
        self.assertIs(self.base._activator, dummy)

    # ──────────────────────────────────────────────────────────────────────
    # General profile defaults & definitions
    # ──────────────────────────────────────────────────────────────────────
    def test_define_defaults_positional(self):
        g = General()
        g.define_defaults("id1", "Bob", "builder", "crew")
        self.assertEqual((g.id, g.name, g.job, g.group), ("id1", "Bob", "builder", "crew"))

    def test_define_defaults_keywords(self):
        g = General()
        g.define_defaults(job="mage", group="blue")
        self.assertEqual(g.job, "mage")
        self.assertEqual(g.group, "blue")

    def test_bind_defaults_generates_id(self):
        g = General()
        g.bind_defaults()
        self.assertIsNotNone(g.id)
        self.assertEqual(g.name, "UnnamedAgent")

    # ──────────────────────────────────────────────────────────────────────
    # General: data transfer registry
    # ──────────────────────────────────────────────────────────────────────
    def test_data_transfer_registry_roundtrip(self):
        g = General()

        def fn():
            return 77

        g.register_data_transfer("give", fn)
        snapshot = g.get_data_transfer_dict()
        self.assertIn("give", snapshot)
        self.assertEqual(g.execute_transfer("give"), 77)

    def test_execute_transfer_missing_key_raises(self):
        g = General()
        with self.assertRaises(KeyError):
            g.execute_transfer("missing")

    # ──────────────────────────────────────────────────────────────────────
    # General: inventories
    # ──────────────────────────────────────────────────────────────────────
    def test_private_vs_shared_inventory_isolated(self):
        self.thread1.bind_to_inventory("x", 1)
        self.thread2.bind_to_inventory("x", 2)
        self.assertEqual(self.thread1.get_from_inventory("x"), 1)
        self.assertEqual(self.thread2.get_from_inventory("x"), 2)
    # ------------------------------------------------------------------
    # REPLACE the two failing tests with the versions below
    # ------------------------------------------------------------------

    def test_shared_inventory_is_profile_local(self) -> None:
        """
        Each `General` profile maintains its own shared-inventory namespace.
        Writing from one thread/profile should NOT leak to another.
        """
        self.thread1.set_shared_inventory_item("global", 123)

        # Different profile instance → expect None
        self.assertIsNone(self.thread2.get_shared_inventory_item("global"))

        # Same profile instance → value present
        self.assertEqual(self.thread1.get_shared_inventory_item("global"), 123)

    def test_patch_records_and_unpatch_clears(self):
        """
        _patched_fields tracks everything injected by _patch(). The list
        persists until dispose() is called. Attributes are removed by
        _unpatch(), but the record itself is kept for auditing.
        """
        fresh_thread = threading.Thread(target=_no_op)
        fresh_profile = General()
        act = AgentActivator(fresh_profile, fresh_thread)

        # Apply patches
        act._patch()
        self.assertGreater(len(act._patched_fields), 0)

        # Attributes now exist on thread
        for name in act._patched_fields:
            self.assertTrue(hasattr(fresh_thread, name))

        # Unpatch but DO NOT dispose – attributes gone, record kept
        act._unpatch()
        for name in act._patched_fields:
            self.assertFalse(hasattr(fresh_thread, name))
        self.assertGreater(len(act._patched_fields), 0)

        # Dispose – record cleared
        act.dispose()
        self.assertEqual(act._patched_fields, [])


    def test_get_shared_inventory_returns_copy(self):
        self.thread1.set_shared_inventory_item("k", "v")
        copy_dict = self.thread1.profile.get_shared_inventory()
        copy_dict["k"] = "changed"
        self.assertEqual(self.thread1.get_shared_inventory_item("k"), "v")

    # ──────────────────────────────────────────────────────────────────────
    # General: save points / locations copy integrity
    # ──────────────────────────────────────────────────────────────────────
    def test_save_point_copy_isolation(self):
        def sp():
            pass

        self.thread1.profile.register_save_point("one", sp)
        cp = self.thread1.profile.get_save_points_dict()
        cp.pop("one")
        self.assertIn("one", self.thread1.profile.save_points)

    def test_location_copy_isolation(self):
        def loc():
            pass

        self.thread1.profile.register_location("loc1", loc)
        cp = self.thread1.profile.get_locations_dict()
        cp.clear()
        self.assertIn("loc1", self.thread1.profile.locations)

    # ──────────────────────────────────────────────────────────────────────
    # BaseProfile cross-agent item by ID
    # ──────────────────────────────────────────────────────────────────────
    def test_bind_and_get_inventory_by_id(self):
        mapping = {self.gen1.factory_id: self.thread1}
        stub_cc = _StubCommandCenter(mapping)
        self.gen2._command_center = stub_cc
        self.gen1.bind_to_inventory("sharedkey", 55)
        val = self.gen2.get_from_inventory_by_id(self.gen1.factory_id, "sharedkey")
        self.assertEqual(val, 55)

    def test_bind_to_inventory_by_id(self):
        mapping = {self.gen2.factory_id: self.thread2}
        stub_cc = _StubCommandCenter(mapping)
        self.gen1._command_center = stub_cc
        self.gen1.bind_to_inventory_by_id(self.gen2.factory_id, "k", 42)
        self.assertEqual(self.thread2.get_from_inventory("k"), 42)

    def test_resolve_worker_without_command_center_returns_none(self):
        self.assertIsNone(self.base._resolve_worker_by_id("any"))

    # ──────────────────────────────────────────────────────────────────────
    # AgentActivator internals
    # ──────────────────────────────────────────────────────────────────────
    # ──────────────────────────────────────────────────────────────────────
    # Shared inventory: each profile keeps its own namespace
    # ──────────────────────────────────────────────────────────────────────
    def test_shared_inventory_is_profile_local(self) -> None:
        """
        set_shared_inventory_item should affect only the invoking profile,
        not every profile on other threads.
        """
        self.thread1.set_shared_inventory_item("global", 123)
        # Different profile instance on thread2 → expect default (None)
        self.assertIsNone(self.thread2.get_shared_inventory_item("global"))
        # Original profile sees the value
        self.assertEqual(self.thread1.get_shared_inventory_item("global"), 123)


    def test_target_run_pass_through(self):
        act = AgentActivator(self.gen1, self.thread1)
        result = act.run()  # Thread.run returns None before start()
        self.assertIsNone(result)

    def test_run_after_dispose_raises(self):
        act = AgentActivator(self.gen1, self.thread1)
        act.dispose()
        with self.assertRaises(RuntimeError):
            act.run()

    def test_is_agent_false_then_true(self):
        self.assertFalse(AgentActivator.is_agent(self.thread1))
        self.thread1._worker_type = "agentic"
        self.assertTrue(AgentActivator.is_agent(self.thread1))

    def test_call_returns_self(self):
        act = AgentActivator(self.gen1, self.thread1)
        self.assertIs(act(), act)

    def test_dispose_sets_internal_fields_none(self):
        act = AgentActivator(self.gen1, self.thread1)
        act.dispose()
        self.assertIsNone(act._profile)
        self.assertIsNone(act._target)

    def test_patched_profile_attribute_single_instance(self):
        names = [n for n in dir(self.thread1) if n == "profile"]
        self.assertEqual(len(names), 1)

    def test_patch_does_not_overwrite_existing_attributes(self):
        self.thread1.existing_attr = 5

        class Mini(General):
            def __init__(self):
                super().__init__()
                self.existing_attr = 6  # would collide if copied

        mini = Mini()
        act = AgentActivator(mini, self.thread1)
        act._patch()
        self.assertEqual(self.thread1.existing_attr, 5)

    def test_dispose_idempotent_again(self):
        act = AgentActivator(self.gen1, self.thread1)
        act.dispose()
        act.dispose()
        self.assertTrue(act._disposed)

if __name__ == "__main__":
    unittest.main()
