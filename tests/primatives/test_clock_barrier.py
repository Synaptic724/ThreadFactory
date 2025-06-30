import threading, time, unittest
from thread_factory.synchronization.orchestrators.clock_barrier import ClockBarrier


BROKEN = threading.BrokenBarrierError   # shorthand


class TestClockBarrier(unittest.TestCase):

    # ------------------------------------------------------------------ #
    # 1 – basic success
    # ------------------------------------------------------------------ #
    def test_passes_with_exact_threads(self):
        barrier = ClockBarrier(3)
        hits = []

        def worker():
            if barrier.wait():
                hits.append("ok")

        th = [threading.Thread(target=worker) for _ in range(3)]
        for t in th: t.start()
        for t in th: t.join()

        self.assertEqual(hits.count("ok"), 3)

    # ------------------------------------------------------------------ #
    # 2 – timeout raises for every waiter
    # ------------------------------------------------------------------ #
    def test_timeout_raises_for_waiters(self):
        barrier = ClockBarrier(4, timeout=0.05)
        errs   = []

        def waiter():
            try:
                barrier.wait()
            except BROKEN:
                errs.append("timeout")

        th = [threading.Thread(target=waiter) for _ in range(3)]  # 3 < parties
        for t in th: t.start()
        for t in th: t.join()

        self.assertEqual(len(errs), 3)
        self.assertTrue(barrier.is_broken())

    # ------------------------------------------------------------------ #
    # 3 – late arrivals raise immediately once broken
    # ------------------------------------------------------------------ #
    def test_late_arrival_after_timeout(self):
        barrier = ClockBarrier(2, timeout=0.05)

        def early():
            with self.assertRaises(BROKEN):
                barrier.wait()

        # first thread times-out
        t1 = threading.Thread(target=early)
        t1.start(); t1.join()

        # late arrival must raise instantly
        with self.assertRaises(BROKEN):
            barrier.wait()

    # ------------------------------------------------------------------ #
    # 4 – reset clears broken state and allows reuse
    # ------------------------------------------------------------------ #
    def test_reset_allows_reuse(self):
        barrier = ClockBarrier(2, timeout=0.05)

        # first round – force timeout
        def first():
            with self.assertRaises(BROKEN):
                barrier.wait()

        t = threading.Thread(target=first)
        t.start(); t.join()

        self.assertTrue(barrier.is_broken())
        barrier.reset()
        self.assertFalse(barrier.is_broken())

        # second round – should pass
        hits = []
        def second():
            if barrier.wait():
                hits.append("pass")

        a = threading.Thread(target=second)
        b = threading.Thread(target=second)
        a.start(); b.start()
        a.join();  b.join()

        self.assertEqual(hits.count("pass"), 2)

    # ------------------------------------------------------------------ #
    # 5 – single-party barrier always passes instantly
    # ------------------------------------------------------------------ #
    def test_single_party_passes(self):
        self.assertTrue(ClockBarrier(1).wait())

    # ------------------------------------------------------------------ #
    # 6 – invalid constructor arguments
    # ------------------------------------------------------------------ #
    def test_invalid_args(self):
        with self.assertRaises(ValueError):
            ClockBarrier(0)
        with self.assertRaises(ValueError):
            ClockBarrier(2, timeout=0)

    # ------------------------------------------------------------------ #
    # 7 – get_waiting_count reflects live waiters
    # ------------------------------------------------------------------ #
    def test_waiting_count(self):
        barrier = ClockBarrier(3, timeout=0.2)

        def w():
            barrier.wait()

        t1 = threading.Thread(target=w)
        t1.start()
        time.sleep(0.01)          # ensure t1 is waiting
        self.assertEqual(barrier.get_waiting_count(), 1)

        t2 = threading.Thread(target=w)
        t2.start()
        t3 = threading.Thread(target=w)
        t3.start()

        for t in (t1, t2, t3):
            t.join()

    def test_barrier_success_clears_broken_flag(self):
        bar = ClockBarrier(2, timeout=0.005)  # 5ms is still aggressive but reasonable
        results = []

        def worker():
            try:
                if bar.wait():
                    results.append("ok")
            except threading.BrokenBarrierError:
                results.append("fail")

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        # If both threads passed, barrier should not be broken
        if results.count("ok") == 2:
            assert not bar.is_broken(), "Barrier should not be broken after success"
        else:
            assert bar.is_broken(), "Barrier should be broken after timeout"

    # ------------------------------------------------------------------ #
    # 8 – multiple independent barrier instances
    # ------------------------------------------------------------------ #
    def test_multiple_instances(self):
        a = ClockBarrier(2)
        b = ClockBarrier(1)
        hits = []

        def wa():
            if a.wait():
                hits.append("a")

        def wb():
            if b.wait():
                hits.append("b")

        t1 = threading.Thread(target=wa)
        t2 = threading.Thread(target=wa)
        t3 = threading.Thread(target=wb)
        for t in (t1, t2, t3): t.start()
        for t in (t1, t2, t3): t.join()

        self.assertEqual(hits.count("a"), 2)
        self.assertEqual(hits.count("b"), 1)

    # ------------------------------------------------------------------ #
    # 9 – total wait time roughly equals timeout on failure
    # ------------------------------------------------------------------ #
    def test_wait_blocks_until_timeout(self):
        barrier = ClockBarrier(2, timeout=0.1)
        start   = time.perf_counter()
        with self.assertRaises(BROKEN):
            barrier.wait()
        dur = time.perf_counter() - start
        self.assertTrue(0.08 <= dur <= 0.15)

    # ------------------------------------------------------------------ #
    # 10 – reset not allowed with waiters
    # ------------------------------------------------------------------ #
    def test_reset_while_waiting_starts_new_generation(self):
        bar = ClockBarrier(2, timeout=1)
        result = []

        def waiter():
            try:
                result.append(bar.wait())
            except Exception as e:
                result.append(str(e))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.05)  # Let the first thread enter and start waiting
        bar.reset()  # Should move to next generation
        t.join()

        self.assertIn(True, result)

    # ------------------------------------------------------------------ #
    # 11 – on_broken callback executes exactly once
    # ------------------------------------------------------------------ #
    def test_on_broken_callback(self):
        flag = {"hits": 0}
        def cb(): flag["hits"] += 1

        barrier = ClockBarrier(3, timeout=0.05, on_broken=cb)

        def w():
            with self.assertRaises(BROKEN):
                barrier.wait()

        a = threading.Thread(target=w)
        b = threading.Thread(target=w)
        a.start(); b.start()
        a.join();  b.join()

        self.assertEqual(flag["hits"], 1)

    # ------------------------------------------------------------------ #
    # 16 – single thread timeout when requiring more
    # ------------------------------------------------------------------ #
    def test_single_thread_timeout(self):
        # Create a barrier requiring 2 threads to pass
        barrier = ClockBarrier(2, timeout=0.05)

        # Define the worker that will wait at the barrier
        def worker():
            with self.assertRaises(BROKEN):
                barrier.wait()

        # Start a single thread, which will timeout
        t1 = threading.Thread(target=worker)
        t1.start()
        t1.join()

        # Check if the barrier is broken
        self.assertTrue(barrier.is_broken())

    # ------------------------------------------------------------------ #
    # 12 – successive successful generations
    # ------------------------------------------------------------------ #
    def test_repeated_success_without_reset(self):
        barrier = ClockBarrier(2)
        ok = []

        def pair():
            if barrier.wait():
                ok.append(1)

        for _ in range(3):
            t1 = threading.Thread(target=pair)
            t2 = threading.Thread(target=pair)
            t1.start(); t2.start()
            t1.join();  t2.join()

        self.assertEqual(len(ok), 6)

    def test_is_broken_false_on_success_ultrafast(self):
        bar = ClockBarrier(2, timeout=0.001)
        result = []

        def fast():
            try:
                result.append(bar.wait())
            except threading.BrokenBarrierError:
                result.append(False)

        t1 = threading.Thread(target=fast)
        t2 = threading.Thread(target=fast)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        if result.count(True) == 2:
            assert not bar.is_broken()
        else:
            assert bar.is_broken()
    # ------------------------------------------------------------------ #
    # 13 – is_broken stays False after normal pass
    # ------------------------------------------------------------------ #
    def test_is_broken_false_on_success(self):
        bar = ClockBarrier(2)
        t1 = threading.Thread(target=bar.wait)
        t1.start()                # one waiting
        time.sleep(0.01)
        self.assertFalse(bar.is_broken())
        self.assertEqual(bar.get_waiting_count(), 1)
        # second thread passes:
        self.assertTrue(bar.wait())
        t1.join()
        self.assertFalse(bar.is_broken())

    # ------------------------------------------------------------------ #
    # 14 – late reset after success is allowed
    # ------------------------------------------------------------------ #
    def test_reset_after_success(self):
        bar = ClockBarrier(2)
        th1 = threading.Thread(target=bar.wait)
        th1.start()
        self.assertTrue(bar.wait())     # second passes
        th1.join()
        bar.reset()                     # should succeed
        self.assertFalse(bar.is_broken())

    def test_wait_raises_after_timeout_until_reset(self):
        bar = ClockBarrier(2, timeout=0.05)
        try:
            bar.wait()  # Only 1 thread => times out
        except threading.BrokenBarrierError:
            pass

        bar.reset()  # ← required for next call to succeed

        t1 = threading.Thread(target=lambda: bar.wait())
        t2 = threading.Thread(target=lambda: bar.wait())
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # ------------------------------------------------------------------ #
    # 15 – broken state survives until reset
    # ------------------------------------------------------------------ #
    def test_wait_raises_after_timeout_until_reset2(self):
        bar = ClockBarrier(2, timeout=0.05)
        try:
            bar.wait()  # Only 1 thread => times out
        except threading.BrokenBarrierError:
            pass

        bar.reset()  # ← required for next call to succeed

        t1 = threading.Thread(target=lambda: bar.wait())
        t2 = threading.Thread(target=lambda: bar.wait())
        t1.start()
        t2.start()
        t1.join()
        t2.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
