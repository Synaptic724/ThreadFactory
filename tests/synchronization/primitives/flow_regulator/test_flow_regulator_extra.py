import queue
import time
import unittest
from time import perf_counter
from thread_factory import FlowRegulator, Pack
import ulid
import threading
from typing import Callable, Optional

class Agent:
    """
    A simple wrapper around threading.Thread to simulate the `factory_id`
    attribute and provide a compatible interface for the tests.
    """
    def __init__(self, target: Callable, name: Optional[str] = None):
        self._target = target
        # Generate factory_id once during Agent initialization
        self._factory_id = str(ulid.ULID())
        self._thread = threading.Thread(target=self._run_wrapper, name=name)
        self._is_alive = False

    def _run_wrapper(self):
        # Set the factory_id on the current thread BEFORE executing the target
        # This ensures FlowRegulator can correctly identify the acquiring entity.
        threading.current_thread().factory_id = self._factory_id
        try:
            self._target()
        finally:
            # Clean up the factory_id from the thread object when done.
            # This is good practice but not strictly necessary for this specific test's fix.
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
        # Agent's factory_id property should reflect the one set on the actual thread.
        # For consistency, we can return the stored _factory_id.
        return self._factory_id

    def start(self):
        self._thread.start()
        self._is_alive = True

    def join(self, timeout: Optional[float] = None):
        self._thread.join(timeout)
        if not self._thread.is_alive():
            self._is_alive = False

    def is_alive(self) -> bool:
        return self._thread.is_alive()
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
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #
def wait_for_waiters(lock: FlowRegulator, expected: int, timeout: float = 2.0):
    """Spin-wait until at least `expected` threads are registered as waiters."""
    start = time.time()
    while time.time() - start < timeout:
        if len(lock.get_all_waiting_factory_ids()) >= expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"Waiters not registered in time. Expected {expected}, "
        f"got {len(lock.get_all_waiting_factory_ids())}"
    )


class TestFlowRegulatorExtra(unittest.TestCase):

    def setUp(self):
        self.center = CommandCenter(total_max_workers=800)

    def tearDown(self):
        self.center.shutdown()
#        t = self.center.create_agent(target=attempt)


    def test_fairness_no_starvation(self):
        """
        All 10 agents (A0–A4, B0–B4) compete for the same permit.
        After ~5s of runtime, every agent must have acquired the lock at least once.
        """
        lock = FlowRegulator(value=1)
        acquired_ctr = {f"A{i}": 0 for i in range(5)} | {f"B{i}": 0 for i in range(5)}
        stop_flag = threading.Event()
        ctr_lock = threading.Lock()

        def actor(name: str):
            threading.current_thread().factory_id = name
            while not stop_flag.is_set():
                if lock.acquire(timeout=1.0):
                    try:
                        with ctr_lock:
                            acquired_ctr[name] += 1
                        time.sleep(0.01)
                    finally:
                        lock.release()
                else:
                    time.sleep(0.005)

        agents = []
        for name in acquired_ctr:
            agent = self.center.create_agent(target=Pack(actor, name))
            agent.name = name  # ✅ Set name here, not during creation
            agents.append(agent)

        for a in agents:
            a.start()

        time.sleep(10)
        stop_flag.set()

        for a in agents:
            a.join(timeout=2)
            self.assertFalse(a.is_alive(), f"Agent {a.name} did not terminate")

        starved = [k for k, v in acquired_ctr.items() if v == 0]
        self.assertFalse(starved, f"Starvation detected: {starved}")


    def test_cleanup_wakes_waiters(self):
        """
        When FlowRegulator is cleaned while threads are waiting, all waiters
        must be woken immediately. This test confirms proper wake-up behavior.
        """
        lock = FlowRegulator(value=0)
        woke_evt = threading.Event()

        def waiter():
            lock.acquire()
            woke_evt.set()

        agent = self.center.create_agent(target=Pack(waiter))
        agent.name = "cleanupWaiter"
        agent.start()

        wait_for_waiters(lock, 1)

        # cleanup from a different thread
        threading.Thread(target=lock.cleanup, name="cleanupr").start()

        self.assertTrue(woke_evt.wait(2), "Waiter was not released by cleanup()")
        agent.join(timeout=1)
        self.assertFalse(agent.is_alive(), "Agent did not terminate after cleanup")


    def test_duplicate_factory_id_targeted_notify(self):
        lock = FlowRegulator(value=0)
        dup_id = "DUP-XYZ"
        ev1, ev2 = threading.Event(), threading.Event()

        def waiter(evt):
            threading.current_thread().factory_id = dup_id
            lock.acquire()
            evt.set()

        a1 = self.center.create_agent(target=Pack(waiter, ev1))
        a1.name = "Dup1"
        a1.start()

        a2 = self.center.create_agent(target=Pack(waiter, ev2))
        a2.name = "Dup2"
        a2.start()

        wait_for_waiters(lock, 2)

        lock.notify(n=1, factory_ids=dup_id)
        woken = sum(evt.wait(1) for evt in (ev1, ev2))
        self.assertEqual(woken, 1, "Targeted notify woke more than one duplicate")

        lock.increase_permits(1)
        self.assertTrue(all(evt.wait(1) for evt in (ev1, ev2)))

    def test_acquire_latency_ratio(self):
        """
        Compare acquire+release latency with and without contention.
        Passes if contended latency is < 50 × uncontended latency.
        """
        ITER = 1_000
        q = queue.Queue()

        def bench(name: str, lock_obj: FlowRegulator):
            # warm-up
            for _ in range(10):
                lock_obj.acquire()
                lock_obj.release()
            start = perf_counter()
            for _ in range(ITER):
                lock_obj.acquire()
                lock_obj.release()
            q.put((name, perf_counter() - start))

        # ---------- uncontended case ---------- #
        lock_fast = FlowRegulator(value=1)
        fast_worker = self.center.create_agent(target=Pack(bench, "fast", lock_fast))
        fast_worker.name = "BenchFast"
        fast_worker.start()

        # ---------- contended case ---------- #
        lock_slow = FlowRegulator(value=1)

        def blocker():
            if lock_slow.acquire(timeout=5):
                time.sleep(0.25)
                lock_slow.release()

        blockers = [
            self.center.create_agent(target=Pack(blocker))
            for i in range(20)
        ]
        for i, b in enumerate(blockers):
            b.name = f"Blocker-{i}"
            b.start()

        # Ensure there's enough contention
        wait_for_waiters(lock_slow, 10, timeout=2.0)

        slow_worker = self.center.create_agent(target=Pack(bench, "slow", lock_slow))
        slow_worker.name = "BenchSlow"
        slow_worker.start()

        # ---------- collect results ---------- #
        name1, t1 = q.get()
        name2, t2 = q.get()
        if name1 == "slow":
            fast_time, slow_time = t2, t1
        else:
            fast_time, slow_time = t1, t2

        ratio = slow_time / fast_time if fast_time else 1
        print(f"[Perf] {fast_time * 1e6:.1f} µs uncontended  "
              f"{slow_time * 1e6:.1f} µs contended  ratio ≈ {ratio:.1f}")

        self.assertLess(
            ratio, 50,
            f"Acquire under contention is too slow ({ratio:.1f}×)"
        )

        # ---------- clean up ---------- #
        fast_worker.join(timeout=2)
        slow_worker.join(timeout=2)
        for b in blockers:
            b.join(timeout=2)

    def test_bias_threshold_honors_reserve(self):
        """
        Bias threshold keeps the last `BIAS_THRESHOLD` threads in reserve
        until we explicitly bypass bias and wake only `RELEASE_COUNT`.
        """
        TOTAL_THREADS = 13
        BIAS_THRESHOLD = 10
        RELEASE_COUNT = 3

        lock = FlowRegulator(value=0, bias_threshold=BIAS_THRESHOLD)
        events = [threading.Event() for _ in range(TOTAL_THREADS)]

        def waiter(evt):
            lock.acquire()
            evt.set()

        agents = []
        for i in range(TOTAL_THREADS):
            a = self.center.create_agent(target=Pack(waiter, events[i]))
            a.name = f"BiasWaiter-{i}"
            agents.append(a)
            a.start()

        wait_for_waiters(lock, TOTAL_THREADS)

        # Buffer a bunch of permits (they stay pending because bias is active)
        lock.increase_permits(TOTAL_THREADS)

        # Now flush only 3 permits and wake exactly 3 waiters (ignore bias)
        lock.notify(n=RELEASE_COUNT)

        time.sleep(0.1)  # give them time to grab permits
        woken = sum(evt.is_set() for evt in events)
        self.assertEqual(
            woken, RELEASE_COUNT,
            f"Bias reserve broken: expected {RELEASE_COUNT} threads, got {woken}"
        )

        # Clean up remaining waiters
        lock.bypass_bias()
        for evt in events:
            evt.wait(timeout=1)


    def test_bias_threshold_notify_all_respects_reserve(self):
        """
        When notify_all is called with bias active, only threads above the
        bias threshold should be woken. The others should remain in reserve.
        """
        TOTAL_THREADS = 13
        BIAS_THRESHOLD = 10
        lock = FlowRegulator(value=0, bias_threshold=BIAS_THRESHOLD)
        events = [threading.Event() for _ in range(TOTAL_THREADS)]

        def waiter(evt):
            lock.acquire()
            evt.set()

        agents = []
        for i in range(TOTAL_THREADS):
            a = self.center.create_agent(target=Pack(waiter, events[i]))
            a.name = f"BiasWaiterAll-{i}"
            agents.append(a)
            a.start()

        wait_for_waiters(lock, TOTAL_THREADS)

        # Add enough permits for everyone
        lock.increase_permits(TOTAL_THREADS)

        # Notify all, but bias threshold should still keep 10 in reserve
        lock.notify_all()

        time.sleep(0.1)  # Give them time to claim permits
        woken = sum(evt.is_set() for evt in events)
        expected = TOTAL_THREADS - BIAS_THRESHOLD

        self.assertEqual(
            woken, expected,
            f"Bias threshold broken on notify_all: expected {expected}, got {woken}"
        )

        # Clean up remaining threads
        lock.bypass_bias()
        for evt in events:
            evt.wait(timeout=1)


# --------------------------------------------------------------------------- #
#  Run standalone                                                             #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    unittest.main(verbosity=2)
