import threading
import time
import random

# Dummy Dynaphore (RLock based Semaphore-like)
class Dynaphore:
    def __init__(self, value=1):
        self._value = value
        self._lock = threading.RLock()
        self._nonzero = threading.Condition(self._lock)

    def acquire(self):
        with self._lock:
            while self._value == 0:
                self._nonzero.wait()
            self._value -= 1

    def release(self):
        with self._lock:
            self._value += 1
            self._nonzero.notify()

    def increase_permits(self, n=1):
        with self._lock:
            self._value += n
            self._nonzero.notify_all()

    def decrease_permits(self, n=1):
        with self._lock:
            if self._value < n:
                raise ValueError("Not enough permits to decrease.")
            self._value -= n

# Speedtest function
def semaphore_speedtest(sem_class, label, num_threads=50, iterations=10000):
    sem = sem_class(1)
    start = time.perf_counter()

    def worker():
        for _ in range(iterations):
            sem.acquire()
            sem.release()

    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    duration = time.perf_counter() - start
    print(f"{label}: {duration:.6f} seconds")


# Run both benchmarks
semaphore_speedtest(Dynaphore, "Dynaphore (RLock)")
semaphore_speedtest(threading.Semaphore, "threading.Semaphore")
