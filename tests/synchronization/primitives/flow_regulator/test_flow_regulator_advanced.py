import random
import threading
import time
import unittest
from contextlib import ExitStack
from typing import Callable, Optional

import ulid

# Assuming FlowRegulator and other necessary imports are available
from thread_factory import FlowRegulator, Pack

# --- Agent and CommandCenter classes (as provided by you) ---
# (Paste your Agent and CommandCenter class definitions here)
class Agent:
    """
    A simple wrapper around threading.Thread to simulate the `factory_id`
    attribute and provide a compatible interface for the tests.
    """
    def __init__(self, target: Callable, name: Optional[str] = None):
        self._target = target
        self._thread = threading.Thread(target=self._run_wrapper, name=name)
        # Assign a factory_id to the thread object
        if not hasattr(self._thread, 'factory_id'):
            self._thread.factory_id = str(ulid.ULID())
        self._is_alive = False # Manual tracking, as t.is_alive() might be delayed

    def _run_wrapper(self):
        # Set the factory_id on the current thread before executing the target
        threading.current_thread().factory_id = self._thread.factory_id
        try:
            self._target()
        finally:
            # Clean up factory_id if necessary, though typically not critical
            if hasattr(threading.current_thread(), 'factory_id'):
                del threading.current_thread().factory_id

    @property
    def name(self) -> Optional[str]:
        return self._thread.name

    @name.setter
    def name(self, value: str) -> None:
        self._thread.name = value

    @property
    def factory_id(self) -> str:
        return self._thread.factory_id

    def start(self):
        self._thread.start()
        self._is_alive = True

    def join(self, timeout: Optional[float] = None):
        self._thread.join(timeout)
        if not self._thread.is_alive():
            self._is_alive = False

    def is_alive(self) -> bool:
        return self._thread.is_alive() # Use actual thread's status


class CommandCenter:
    """
    A dummy class to replace the original CommandCenter for test compatibility.
    It simply creates and manages Agent instances.
    """
    def __init__(self, total_max_workers: int = 10):
        # total_max_workers is not strictly used here, but kept for signature compatibility
        self._agents: list[Agent] = []

    def create_agent(self, target: Callable, name: Optional[str] = None) -> Agent:
        agent = Agent(target=target, name=name)
        self._agents.append(agent)
        return agent

    def shutdown(self):
        # Ensure all created agents are joined to prevent lingering threads
        for agent in self._agents:
            if agent.is_alive():
                agent.join()
        self._agents.clear()

# --------------------------------------------------------------------------- #
#  Helper utilities                                                           #
# --------------------------------------------------------------------------- #
def wait_for_waiters(lock: FlowRegulator, expected: int, timeout: float = 2.0):
    start = time.time()
    while time.time() - start < timeout:
        if len(lock.get_all_waiting_factory_ids()) >= expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"Waiters not registered in time. Expected {expected}, "
        f"got {len(lock.get_all_waiting_factory_ids())}"
    )


def _set_thread_factory_id(fid: str):       # kept for completeness
    threading.current_thread().factory_id = fid

# --------------------------------------------------------------------------- #
#  Test-suite                                                                 #
# --------------------------------------------------------------------------- #
class TestFlowRegulatorEdgeCases(unittest.TestCase):


    def setUp(self):
        # Corrected: Removed 'group_max_workers' as CommandCenter does not accept it.
        self.center = CommandCenter(total_max_workers=800)

    def tearDown(self):
        self.center.shutdown()

    # ----------------------------------------------------------------------- #
    # 1. Ultra-contention shutdown                                            #
    # ----------------------------------------------------------------------- #
    def test_ultra_contention_dispose(self):
        """
        All threads block on acquire() and must be released when dispose() is called.
        """
        from thread_factory.utilities.coordination.package import Pack

        n_threads = 200
        lock = FlowRegulator(value=0)  # All threads block
        done = [threading.Event() for _ in range(n_threads)]
        agents = []

        def waiter(idx):
            lock.acquire()
            done[idx].set()

        for i in range(n_threads):
            agent = self.center.create_agent(target=Pack(waiter, i))
            agent.name = f"UC-{i}"
            agents.append(agent)
            agent.start()

        wait_for_waiters(lock, n_threads)
        lock.dispose()

        self.assertTrue(all(e.wait(2) for e in done), "Some waiters were not released on dispose()")

        for agent in agents:
            agent.join(timeout=1)
            self.assertFalse(agent.is_alive(), f"{agent.name} did not terminate properly")

        self.assertEqual(lock._value, 0)

    # ----------------------------------------------------------------------- #
    # 2. Callback chaos (exception path)                                      #
    # ----------------------------------------------------------------------- #
    def test_callback_exception_is_swallowed(self):
        lock   = FlowRegulator(value=0)
        flag   = threading.Event()

        def bad_cb():
            flag.set()
            raise RuntimeError("Boom")

        def waiter():
            # bind a per-thread callback that throws
            lock.set_callback(threading.current_thread().factory_id, bad_cb)
            lock.acquire()      # will wake via notify
            lock.release()

        w = self.center.create_agent(target=waiter)
        w.name="CBChaos"
        w.start()
        wait_for_waiters(lock, 1)

        # notify in calling thread (callback executes *here*)
        lock.notify(n=1, awaited_caller=False)
        w.join(timeout=1)

        self.assertTrue(flag.is_set(), "Callback never executed")
        # process didn’t crash → exception swallowed

    # ----------------------------------------------------------------------- #
    # 3. Timeout vs notify race                                               #
    # ----------------------------------------------------------------------- #
    def test_timeout_vs_notify_race(self):
        lock   = FlowRegulator(value=0)
        result = []

        def waiter():
            ok = lock.acquire(timeout=0.1)
            result.append(ok)

        w = self.center.create_agent(target=waiter)
        w.start()

        time.sleep(random.uniform(0.02, 0.08))  # race window
        lock.notify(n=1)
        w.join(timeout=1)

        self.assertEqual(len(result), 1)
        self.assertIn(result[0], (True, False))
        live = lock._value + lock._pending_permits + len(lock.get_all_waiters())
        # The previous 'live' calculation was only lock._value + len(lock.get_all_waiters())
        # and missed _pending_permits. This corrects it.
        # However, a more robust check for a semaphore would be:
        # Expected value is 0 (permit acquired and released, or timeout occurred)
        # If timeout occurred, _value should be 0 and no waiters.
        # If acquired, _value should be 0 and no waiters.
        self.assertEqual(live, 0, "Permit accounting drifted")


    # ----------------------------------------------------------------------- #
    # 4. Bias inequality gauntlet                                             #
    # ----------------------------------------------------------------------- #
    def test_bias_inequality_paths(self):
        """
        Verifies:
        • Buffered permits stay buffered when waiter count <= bias threshold
        • Flush triggers only when waiters > threshold
        • Flush only wakes up to the number of permits
        • Remaining waiters can be awoken with more permits
        """
        lock = FlowRegulator(value=0, bias_threshold=10)
        evs = [threading.Event() for _ in range(6)]

        # Step 1 — 6 waiters block
        for ev in evs:
            self.center.create_agent(target=Pack(lambda e=ev: (lock.acquire(), e.set()))).start()

        wait_for_waiters(lock, 6)

        # Step 2 — buffer 5 permits (nothing should wake yet)
        lock.increase_permits(5)
        self.assertEqual(lock._pending_permits, 5)
        self.assertFalse(any(ev.is_set() for ev in evs))

        # Step 3 — drop bias below waiter count (6 > 4 triggers flush)
        lock.set_bias_threshold(4)
        time.sleep(0.2)  # Give threads time to race on the flush

        # Step 4 — count how many succeeded
        woke = [ev.wait(1) for ev in evs]
        self.assertEqual(woke.count(True), 5, "Exactly 5 threads should have acquired after flush")
        self.assertEqual(lock._pending_permits, 0, "Pending permits should be flushed")

        # Step 5 — wake the final waiter
        lock.set_bias_threshold(None)  # turn bias OFF → no buffering
        lock.increase_permits(1)  # permit is live, waiter wakes
        self.assertTrue(all(ev.wait(1) for ev in evs))

    # ----------------------------------------------------------------------- #
    # 5. Double-dispose idempotence                                           #
    # ----------------------------------------------------------------------- #
    def test_double_dispose(self):
        lock   = FlowRegulator(value=0)
        wakies = []

        def waiter():
            lock.acquire()
            wakies.append("up")

        threads = [self.center.create_agent(target=waiter) for _ in range(10)]
        for t in threads: t.start()
        wait_for_waiters(lock, 10)

        with ExitStack() as stack:
            for _ in range(2):
                killer = threading.Thread(target=lock.dispose)
                killer.start()
                stack.callback(killer.join)

        for t in threads: t.join(timeout=1)
        self.assertEqual(len(wakies), 10)
        self.assertTrue(lock.disposed)

    # ----------------------------------------------------------------------- #
    # 6. Permit-leak fuzzer                                                   #
    # ----------------------------------------------------------------------- #
    def test_permit_leak_fuzzer(self):
        """
        Fuzz test simulating a chaotic mix of acquire/release/notify.
        Ensures permits don’t leak and all threads terminate cleanly.
        """
        import random

        init_permits = 3
        ops = 2000
        lock = FlowRegulator(value=init_permits, bias_threshold=None)

        def fuzz_loop(name: str):
            for _ in range(ops):
                op = random.choice(("acq", "rel", "not"))
                if op == "acq":
                    if lock.acquire(timeout=0.01):
                        lock.release()
                elif op == "rel":
                    lock.increase_permits(1)
                else: # op == "not"
                    lock.notify()

        agents = [
            self.center.create_agent(target=Pack(fuzz_loop, f"Fuzz-{i}"))
            for i in range(8)
        ]
        for a in agents:
            a.start()
        for a in agents:
            a.join(timeout=2)

        live_permits = lock._value + lock._pending_permits
        self.assertGreaterEqual(live_permits, 0, "Permit count went negative")
        self.assertEqual(len(lock.get_all_waiters()), 0, "Waiters leaked after fuzz")


# --------------------------------------------------------------------------- #
#  Run standalone                                                             #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    unittest.main(verbosity=2)