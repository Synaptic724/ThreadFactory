import copy
import pickle
import random
import threading
import unittest
from thread_factory.concurrency.sync_types.sync_ref import SyncRef
from thread_factory.concurrency.sync_types.sync_int import SyncInt   # integration check
from thread_factory.utils.interfaces.isync import ISync

TIMEOUT = 5      # seconds – join time-outs expose dead-locks quickly
BIG = 50_000     # used by a few stress tests


# ---------------------------------------------------------------------------
# Helper: spawn and join threads with a barrier start-gun
# ---------------------------------------------------------------------------
def _spawn_threads(fn, *, num=4, iterations=1):
    barrier = threading.Barrier(num + 1)

    def _wrapper():
        barrier.wait()
        for _ in range(iterations):
            fn()

    threads = [threading.Thread(target=_wrapper) for _ in range(num)]
    for t in threads:
        t.start()
    barrier.wait()                      # go!
    return threads


def _assert_threads_complete(testcase: unittest.TestCase, threads):
    for t in threads:
        t.join(timeout=TIMEOUT)
    testcase.assertTrue(
        all(not t.is_alive() for t in threads),
        "Dead-lock or timeout detected",
    )


# ---------------------------------------------------------------------------
#  Test-cases
# ---------------------------------------------------------------------------
class TestSyncRef(unittest.TestCase):

    # 1. basic get / set -----------------------------------------------------
    def test_get_set(self):
        ref = SyncRef(123)
        self.assertEqual(ref.get(), 123)
        ref.set(999)
        self.assertEqual(ref.get(), 999)

    # 2. snapshot alias property --------------------------------------------
    def test_snapshot_property(self):
        ref = SyncRef(["a"])
        snap = ref.snapshot
        ref.update(lambda lst: lst.append("b"))
        # snap still points to same list; list itself mutated
        self.assertEqual(snap, ["a", "b"])
        # create *new* list
        ref.set(["x"])
        self.assertEqual(snap, ["a", "b"])
        self.assertEqual(ref.get(), ["x"])

    # 3. update returns live object -----------------------------------------
    def test_update_mutates_in_place(self):
        d = {"hits": 0}
        ref = SyncRef(d)
        returned = ref.update(lambda x: x.update(hits=x["hits"] + 1))
        self.assertIs(returned, d)
        self.assertEqual(d["hits"], 1)

    # 4. modify functional style --------------------------------------------
    def test_modify_replaces_value(self):
        ref = SyncRef(1)
        out = ref.modify(lambda x: x + 1)
        self.assertEqual(out, 2)
        self.assertEqual(ref.get(), 2)

    # 5. transform (read-only) ----------------------------------------------
    def test_transform_is_read_only(self):
        ref = SyncRef([1, 2, 3])
        total = ref.transform(sum)
        self.assertEqual(total, 6)
        self.assertEqual(ref.get(), [1, 2, 3])  # unchanged

    # 6. map alias ----------------------------------------------------------
    def test_map_alias(self):
        ref = SyncRef("abc")
        self.assertEqual(ref.map(str.upper), "ABC")

    # 7. swap returns old ----------------------------------------------------
    def test_swap(self):
        ref = SyncRef("old")
        old = ref.swap("new")
        self.assertEqual(old, "old")
        self.assertEqual(ref.get(), "new")

    # 8. CAS success ---------------------------------------------------------
    def test_cas_success(self):
        payload = ["x"]
        ref = SyncRef(payload)
        self.assertTrue(ref.cas(payload, ["y"]))
        self.assertEqual(ref.get(), ["y"])

    # 9. CAS fail ------------------------------------------------------------
    def test_cas_fail(self):
        payload = ["x"]
        ref = SyncRef(payload)
        self.assertFalse(ref.cas(["x"], ["y"]))  # identity check
        self.assertEqual(ref.get(), ["x"])

    # 10. __enter__ / __exit__ ----------------------------------------------
    def test_context_manager(self):
        ref = SyncRef([])
        with ref as lst:
            lst.append(1)
        self.assertEqual(ref.get(), [1])

    # 11. locked() contextmanager -------------------------------------------
    def test_locked_cm(self):
        ref = SyncRef({"total": 0})
        with ref.locked() as d:
            d["total"] += 5
        self.assertEqual(ref.get()["total"], 5)

    # 12. equality vs other SyncRef -----------------------------------------
    def test_equality_sync(self):
        a = SyncRef([1, 2])
        b = SyncRef([1, 2])
        self.assertTrue(a == b)
        b.update(lambda lst: lst.append(3))
        self.assertFalse(a == b)

    # 13. hash non-hashable fallback to id -----------------------------------
    def test_hash_nonhashable(self):
        ref = SyncRef([])
        self.assertIsInstance(hash(ref), int)

    # 14. repr contains payload ---------------------------------------------
    def test_repr(self):
        ref = SyncRef(42)
        self.assertIn("42", repr(ref))

    # 15. deepcopy & copy ----------------------------------------------------
    def test_copy_roundtrip(self):
        ref = SyncRef([1])
        dcp = copy.deepcopy(ref)
        self.assertEqual(dcp.get(), [1])
        self.assertIsNot(dcp.get(), ref.get())

    # 16. pickle roundtrip ---------------------------------------------------
    def test_pickle_roundtrip(self):
        ref = SyncRef({"a": 1})
        data = pickle.dumps(ref)
        new = pickle.loads(data)
        self.assertEqual(new.get(), {"a": 1})
        new.set({"b": 2})
        self.assertEqual(ref.get(), {"a": 1})

    # 17. concurrent update (list append) ------------------------------------
    def test_concurrent_list_appends(self):
        ref = SyncRef([])
        def worker():
            ref.update(lambda lst: lst.append(1))
        threads = _spawn_threads(worker, num=16, iterations=BIG // 16)
        _assert_threads_complete(self, threads)
        self.assertEqual(len(ref.get()), BIG)

    # 18. concurrent modify (int increment) ----------------------------------
    def test_concurrent_modify(self):
        ref = SyncRef(0)
        def bump():
            ref.modify(lambda x: x + 1)
        threads = _spawn_threads(bump, num=8, iterations=BIG // 8)
        _assert_threads_complete(self, threads)
        self.assertEqual(ref.get(), BIG)

    # 19. dead-lock free against another SyncRef -----------------------------
    def test_dual_lock_order(self):
        a = SyncRef(0)
        b = SyncRef(0)
        barrier = threading.Barrier(3)
        def t1():
            barrier.wait()
            for _ in range(10_000):
                with ISync._acquire_two(a, b)[0]._lock, ISync._acquire_two(a, b)[1]._lock:
                    a.swap(a.get() + 1)
                    b.swap(b.get() + 1)
        def t2():
            barrier.wait()
            for _ in range(10_000):
                with ISync._acquire_two(b, a)[0]._lock, ISync._acquire_two(b, a)[1]._lock:
                    a.swap(a.get() + 1)
                    b.swap(b.get() + 1)
        threads = _spawn_threads(lambda: None, num=0)  # placeholder list
        threads += [threading.Thread(target=t1), threading.Thread(target=t2)]
        for t in threads: t.start()
        barrier.wait()
        _assert_threads_complete(self, threads)

    # 20. huge random stress (mixed ops) -------------------------------------
    def test_random_mix(self):
        ref = SyncRef(0)
        ops = [ref.modify, ref.swap, ref.update]
        def worker():
            for _ in range(20_000):
                op = random.choice(ops)
                if op is ref.modify:
                    op(lambda x: x + 1)
                elif op is ref.swap:
                    op(random.randint(0, 99))
                else:
                    op(lambda x: None)  # no-op update
        threads = _spawn_threads(worker, num=4)
        _assert_threads_complete(self, threads)

    # 21. swap while readers --------------------------------------------------
    def test_swap_with_readers(self):
        ref = SyncRef(0)
        stop = threading.Event()
        def reader():
            while not stop.is_set():
                _ = ref.get()
        r_threads = _spawn_threads(reader, num=4, iterations=1)
        for _ in range(1000):
            old = ref.swap(ref.get() + 1)
            self.assertIsInstance(old, int)
        stop.set()
        _assert_threads_complete(self, r_threads)
        self.assertEqual(ref.get(), 1000)

    # 22. CAS in tight loop ---------------------------------------------------
    # ------------------ test_heavy_swap (fixed) ------------------
    def test_heavy_modify(self):
        ref = SyncRef(0)

        def bumper():
            for _ in range(10_000):
                ref.modify(lambda x: x + 1)

        threads = _spawn_threads(bumper, num=4)
        _assert_threads_complete(self, threads)
        self.assertEqual(ref.get(), 4 * 10_000)

    # ------------------ test_stress_cas (fixed) ------------------
    def test_stress_cas(self):
        ref = SyncRef([])
        original = ref.get()  # capture *once*
        success = 0
        for _ in range(100):
            if ref.cas(original, original + [1]):
                success += 1
        self.assertEqual(success, 1)  # only the first CAS can win

    # 23. locked() nested (RLock re-entrance) ---------------------------------
    def test_reentrant_lock(self):
        ref = SyncRef(0)
        with ref.locked():
            with ref.locked():
                ref.set(10)
        self.assertEqual(ref.get(), 10)

    # 24. pointer integrity inside with-block ---------------------------------
    def test_live_pointer_mutation(self):
        payload = {"x": 1}
        ref = SyncRef(payload)
        with ref as d:
            d["x"] = 2
        self.assertIs(payload, ref.get())
        self.assertEqual(ref.get()["x"], 2)

    # 25. cross-type integration: SyncInt uses SyncRef ------------------------
    def test_cross_type_interop(self):
        counter = SyncInt(0)
        ref = SyncRef(counter)
        ref.get().increment()
        self.assertEqual(counter.get(), 1)
        # swap with fresh object
        ref.swap(SyncInt(5))
        self.assertEqual(counter.get(), 1)
        self.assertEqual(ref.get().get(), 5)

    # 26. hash stable even after mutation -------------------------------------
    def test_hash_stability(self):
        ref = SyncRef([1, 2])
        h1 = hash(ref)
        ref.update(lambda lst: lst.append(3))
        h2 = hash(ref)
        # Non-hashable payload -> hash(ref) is id-based, stays same
        self.assertEqual(h1, h2)

    # 27. modify returns new object identity ----------------------------------
    def test_modify_new_identity(self):
        ref = SyncRef([1])
        old_obj = ref.get()
        new_obj = ref.modify(lambda lst: lst + [2])
        self.assertIsNot(old_obj, new_obj)
        self.assertEqual(ref.get(), [1, 2])

    # 28. transform inside multi-thread reads ---------------------------------
    def test_concurrent_transform(self):
        ref = SyncRef(list(range(100)))
        def reader():
            for _ in range(10_000):
                self.assertEqual(ref.transform(len), 100)
        threads = _spawn_threads(reader, num=8, iterations=1)
        _assert_threads_complete(self, threads)

    # 29. swap performance under heavy churn ----------------------------------


    # 30. modify function may raise -------------------------------------------
    def test_modify_exception_propagates(self):
        ref = SyncRef(1)
        with self.assertRaises(ZeroDivisionError):
            ref.modify(lambda x: 1 / 0)
        # value unchanged
        self.assertEqual(ref.get(), 1)

    # 31. update should return same object identity ---------------------------
    def test_update_returns_same_identity(self):
        lst = []
        ref = SyncRef(lst)
        ret = ref.update(lambda x: x.append(1))
        self.assertIs(lst, ret)

    # 32. lock held during update proved by shared flag -----------------------
    def test_update_lock_held(self):
        ref = SyncRef(0)
        inside = threading.Event()
        proceed = threading.Event()

        def mutator():
            def fn(x):
                inside.set()
                proceed.wait()
                return None
            ref.update(fn)

        t = threading.Thread(target=mutator)
        t.start()
        inside.wait()
        # while update holds the lock, get() should block; we test via try-lock
        locked = ref._lock.acquire(blocking=False)
        self.assertFalse(locked)
        proceed.set()
        t.join(timeout=TIMEOUT)
        self.assertFalse(t.is_alive())

    # 33. __eq__ with non-Sync ------------------------------------------------
    def test_eq_non_sync(self):
        ref = SyncRef({"a": 1})
        self.assertTrue(ref == {"a": 1})
        self.assertFalse(ref == {"a": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
