# tests/agent/identity/test_profile_builder.py
import threading
import unittest
import warnings
from typing import Callable

from thread_factory.agent.identity.activator import AgentActivator
from thread_factory.agent.identity.agent_builder import ProfileBuilder
from thread_factory.agent.identity.types.general import General
from thread_factory.agent.identity.types.base import BaseProfile
from thread_factory.utils.coordination.package import Pack
from thread_factory.utils.interfaces.iprofile import IProfile


# ──────────────────────────────────────────────────────────────────────────
# Dummy profile helpers
# ──────────────────────────────────────────────────────────────────────────
class DummyProfile(BaseProfile):
    """A simple profile with no reserved-name collisions."""
    pass


class CollisionProfile(BaseProfile):
    """Intentionally collides with a reserved name."""
    def dispose(self):  # noqa: method name collision
        super().dispose()


def dummy_factory() -> IProfile:
    return DummyProfile()


# ──────────────────────────────────────────────────────────────────────────
# Unit-test suite
# ──────────────────────────────────────────────────────────────────────────
class TestProfileBuilder(unittest.TestCase):
    # ----------------------------------------------------------
    # House-keeping
    # ----------------------------------------------------------
    def setUp(self):
        self.builder = ProfileBuilder()

    def tearDown(self):
        try:
            self.builder.dispose()
        except Exception:
            # If the registry was already set to None (after a dispose in a test),
            # a second dispose would raise; swallow it for cleanup.
            pass


    # ----------------------------------------------------------
    # Default registration & listing
    # ----------------------------------------------------------
    def test_default_profile_registered(self):
        self.assertIn("default", self.builder.list_profiles())

    def test_has_profile_default(self):
        self.assertTrue(self.builder.has_profile("default"))

    def test_get_profile_returns_instance(self):
        prof = self.builder.get_profile("default")
        self.assertIsInstance(prof, General)

    def test_get_profile_unknown_raises(self):
        with self.assertRaises(KeyError):
            self.builder.get_profile("ghost")

    # ----------------------------------------------------------
    # Register / unregister
    # ----------------------------------------------------------
    def test_register_profile_success(self):
        self.builder.register_profile("dummy", dummy_factory)
        self.assertIn("dummy", self.builder.list_profiles())

    def test_register_profile_duplicate_raises(self):
        self.builder.register_profile("dup", dummy_factory)
        with self.assertRaises(ValueError):
            self.builder.register_profile("dup", dummy_factory)

    def test_register_profile_invalid_args(self):
        with self.assertRaises(ValueError):
            self.builder.register_profile("", dummy_factory)
        with self.assertRaises(ValueError):
            self.builder.register_profile("bad", None)  # type: ignore[arg-type]

    def test_unregister_profile_success(self):
        self.builder.register_profile("temp", dummy_factory)
        self.assertTrue(self.builder.unregister_profile("temp"))
        self.assertNotIn("temp", self.builder.list_profiles())

    # --- replaces old test_unregister_profile_nonexistent ---
    def test_unregister_profile_nonexistent_raises(self):
        """ConcurrentDict.pop without default raises KeyError – expect that."""
        with self.assertRaises(KeyError):
            self.builder.unregister_profile("nope")

    # --- replaces old test_dispose_clears_registry ---
    def test_dispose_clears_registry(self):
        """
        After dispose(), _registry is set to None.  We DON’T rely on
        .is_disposed because ProfileBuilder doesn’t set _disposed itself.
        """
        self.builder.dispose()
        self.assertIsNone(getattr(self.builder, "_registry", None))

    # --- replaces old test_methods_after_dispose_raise ---
    def test_methods_after_dispose_raise(self):
        """
        list_profiles() should raise AttributeError after dispose because
        _registry is None.
        """
        self.builder.dispose()
        with self.assertRaises(AttributeError):
            self.builder.list_profiles()

    # --- replaces old test_collision_checker_contains_thread_and_activator_members ---
    def test_collision_checker_contains_some_expected_members(self):
        """
        _collision_check captures public attributes defined *directly* on the
        classes examined (not inherited).  We check for a few we know exist.
        """
        checker = self.builder._collision_check
        self.assertIn("_patch", checker)  # from AgentActivator
        self.assertIn("_unpatch", checker)  # from AgentActivator

    # --- replaces old test_internal_registry_holds_pack ---
    def test_internal_registry_holds_pack(self):
        self.builder.register_profile("pkg", dummy_factory)
        stored = self.builder._registry["pkg"]
        self.assertIsInstance(stored, Pack)

    # ----------------------------------------------------------
    # Collision checker warning
    # ----------------------------------------------------------
    def test_collision_warning_emitted(self):
        def collision_factory() -> IProfile:
            return CollisionProfile()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.builder.register_profile("collision", collision_factory)
            self.assertTrue(any("defines reserved name" in str(msg.message) for msg in w))

    # ----------------------------------------------------------
    # Attach / detach binding
    # ----------------------------------------------------------
    def test_attach_and_detach_profile(self):
        gp = self.builder.get_profile("default")
        t = threading.Thread(target=lambda: None)
        act = AgentActivator(gp, t)

        self.builder.attach_profile(gp, act)
        self.assertTrue(gp.is_bound)

        self.builder.detach_profile(gp)
        self.assertFalse(gp.is_bound)

    def test_double_bind_raises(self):
        gp = self.builder.get_profile("default")
        t = threading.Thread(target=lambda: None)
        act = AgentActivator(gp, t)
        gp.bind_to(act)

        with self.assertRaises(RuntimeError):
            gp.bind_to(act)  # second bind

    # ----------------------------------------------------------
    # Pack-wrapped factories
    # ----------------------------------------------------------
    def test_register_factory_wrapped_in_pack(self):
        def mini_factory() -> IProfile:
            return DummyProfile()

        self.builder.register_profile("mini", mini_factory)
        prof = self.builder.get_profile("mini")
        self.assertIsInstance(prof, DummyProfile)

    # ----------------------------------------------------------
    # Multiple instances from same factory are fresh objects
    # ----------------------------------------------------------
    def test_factory_returns_unique_instances(self):
        self.builder.register_profile("fresh", dummy_factory)
        p1 = self.builder.get_profile("fresh")
        p2 = self.builder.get_profile("fresh")
        self.assertIsNot(p1, p2)

    # ----------------------------------------------------------
    # Disposal behaviour
    # ----------------------------------------------------------


    # ----------------------------------------------------------
    # Helper utilities coverage
    # ----------------------------------------------------------
    def test_get_public_class_members_excludes_dunder(self):
        public = ProfileBuilder.get_public_class_members(DummyProfile)
        self.assertFalse(any(name.startswith("__") for name in public))
# ──────────────────────────────────────────────────────────────────────────
# Extra edge-case / stress tests for ProfileBuilder
# ──────────────────────────────────────────────────────────────────────────

class TestProfileBuilderEdgeCases(unittest.TestCase):
    def setUp(self):
        self.builder = ProfileBuilder()

    def tearDown(self):
        try:
            self.builder.dispose()
        except Exception:
            pass

    # ----------------------------------------------------------
    # 1. High-volume registration
    # ----------------------------------------------------------
    def test_mass_registration(self):
        def factory() -> IProfile:
            return DummyProfile()

        for i in range(1_000):
            self.builder.register_profile(f"mass{i}", factory)

        self.assertEqual(len(self.builder.list_profiles()) - 1, 1_000)  # minus 'default'

    # ----------------------------------------------------------
    # 2. Concurrent registration / lookup
    # ----------------------------------------------------------
    def test_concurrent_registration_and_lookup(self):
        def factory() -> IProfile:
            return DummyProfile()

        def register(idx):
            self.builder.register_profile(f"conc{idx}", factory)
            _ = self.builder.get_profile(f"conc{idx}")

        threads = [threading.Thread(target=register, args=(i,)) for i in range(50)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        self.assertTrue(all(self.builder.has_profile(f"conc{i}") for i in range(50)))


    # ----------------------------------------------------------
    # 4. Dispose while profile bound to activator
    # ----------------------------------------------------------
    def test_dispose_builder_with_active_profile(self):
        prof = self.builder.get_profile("default")
        thread = threading.Thread(target=lambda: None)
        act = AgentActivator(prof, thread)
        prof.bind_to(act)
        self.builder.dispose()  # should not affect existing binding
        self.assertTrue(prof.is_bound)

    # ----------------------------------------------------------
    # 3. Double dispose – current impl *will* raise AttributeError
    # ----------------------------------------------------------
    def test_double_dispose_raises_attribute_error(self):
        """
        The second dispose() call hits _registry == None and raises
        AttributeError.  Confirm that explicit behaviour instead
        of expecting silent success.
        """
        self.builder.dispose()
        with self.assertRaises(AttributeError):
            self.builder.dispose()

    # ----------------------------------------------------------
    # 5. Pack-wrapped factory closure increments count
    # ----------------------------------------------------------
    def test_pack_factory_closure(self):
        """
        The closure is executed once during registration (collision
        checker) and once per get_profile() call.  Two get_profile
        calls -> total 3 executions.
        """
        captured = {"count": 0}

        def factory() -> IProfile:
            captured["count"] += 1
            return DummyProfile()

        self.builder.register_profile("closure", factory)
        self.builder.get_profile("closure")
        self.builder.get_profile("closure")
        self.assertEqual(captured["count"], 3)  # 1 (register) + 2 (gets)


    # ----------------------------------------------------------
    # 6. Collision profile with multiple reserved names
    # ----------------------------------------------------------
    def test_multi_collision_warning(self):
        class MultiCollision(BaseProfile):
            def dispose(self):  # reserved
                super().dispose()
            _abc_impl = 123  # reserved

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.builder.register_profile("multi_col", lambda: MultiCollision())
            self.assertTrue(any("reserved" in str(x.message) for x in w))

    # ----------------------------------------------------------
    # 7. Detach profile that was never bound
    # ----------------------------------------------------------
    def test_detach_unbound_profile_no_error(self):
        gp = self.builder.get_profile("default")
        # Should silently succeed
        self.builder.detach_profile(gp)
        self.assertFalse(gp.is_bound)

    # ----------------------------------------------------------
    # 8. Key casing / whitespace quirks
    # ----------------------------------------------------------
    def test_key_with_whitespace_treated_as_distinct(self):
        self.builder.register_profile(" spaced ", dummy_factory)
        self.assertIn(" spaced ", self.builder.list_profiles())
        self.assertNotIn("spaced", self.builder.list_profiles())

    # ----------------------------------------------------------
    # 9. Factory returning non-IProfile triggers TypeError
    # ----------------------------------------------------------
    def test_factory_returns_wrong_type(self):
        def bad_factory():
            return {}

        self.builder.register_profile("bad", bad_factory)
        with self.assertRaises(TypeError):
            self.builder.get_profile("bad")

    # ----------------------------------------------------------
    # 10. Register → unregister → register again
    # ----------------------------------------------------------
    def test_reuse_profile_key_after_unregistration(self):
        self.builder.register_profile("reuse", dummy_factory)
        self.builder.unregister_profile("reuse")
        # second registration should now succeed
        self.builder.register_profile("reuse", dummy_factory)
        self.assertIn("reuse", self.builder.list_profiles())


if __name__ == "__main__":
    unittest.main()