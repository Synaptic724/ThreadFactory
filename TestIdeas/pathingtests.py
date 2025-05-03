import time
import random
import threading

class Node:
    __slots__ = ()
    """Represents a node in the path graph."""
    def __init__(self):
        pass
        #self.lock = threading.Lock()

def traverse_graph(graph, depth):
    """Simulates a producer traversing a graph of given depth."""
    path = random.sample(graph, depth)
    for node in path:
        pass
        # acquired = node.lock.acquire(blocking=False)
        # if not acquired:
        #     # Failed to acquire, simulate retry logic
        #     return False
    # Simulate enqueue at the end of the path
    #time.sleep(0.000001)  # pretend enqueue is ~1us
    # for node in path:
    #     node.lock.release()
    return True

def test_graph_traversal(graph_size=32, depth=2, iterations=100):
    graph = [Node() for _ in range(graph_size)]
    success = 0
    start = time.perf_counter()
    for _ in range(iterations):
        if traverse_graph(graph, depth):
            success += 1
    duration = time.perf_counter() - start
    avg_time_per_attempt_ns = (duration / iterations) * 1e9
    avg_time_per_success_ns = (duration / success) * 1e9 if success else float('inf')
    print(f"Graph Size: {graph_size} | Path Depth: {depth}")
    print(f"Total Iterations: {iterations} | Successful Paths: {success}")
    print(f"Total Time: {duration:.6f} seconds")
    print(f"Average Time per Attempt: {avg_time_per_attempt_ns:.2f} ns")
    print(f"Average Time per Successful Traversal: {avg_time_per_success_ns:.2f} ns")

print("Testing Traversal")
test_graph_traversal(graph_size=32, depth=4, iterations=100)



import time

def test_if_chain(iterations=1_000_000):
    """Simulate a producer checking 4 boolean variables with if-statements."""
    # Simulate 4 boolean switches (all True for this test)
    switches = [True, True, True, True]

    start = time.perf_counter()
    for _ in range(iterations):
        if switches[0]:
            if switches[1]:
                if switches[2]:
                    if switches[3]:
                        pass  # Success path
    duration = time.perf_counter() - start

    avg_time_per_op_ns = (duration / iterations) * 1e9
    print(f"Total Time: {duration:.6f} seconds")
    print(f"Average Time per 4-if-chain: {avg_time_per_op_ns:.2f} ns")

test_if_chain()
import threading
import time

def race_path_lambdas(flags, result, thread_id, ready_event):
    ready_event.wait()  # wait until GO
    progress = 0

    for i in range(len(flags)):
        if flags[i] == 0:
            flags[i] = thread_id  # claim slot
            progress += 1
        else:
            # Race condition detected
            result.append(("FAILED", progress))
            return

    # Finished successfully
    result.append(("SUCCESS", progress))


def test_mass_race_lambdas(num_threads=100, num_switches=5, total_runs=1000):
    successes = 0
    failures = 0
    total_progress = 0

    for run in range(total_runs):
        flags = [0 for _ in range(num_switches)]
        result = []
        ready_event = threading.Event()
        threads = []

        for thread_id in range(1, num_threads + 1):
            t = threading.Thread(target=race_path_lambdas, args=(flags, result, thread_id, ready_event))
            threads.append(t)
            t.start()

        ready_event.set()

        for t in threads:
            t.join()

        for status, progress in result:
            if status == "SUCCESS":
                successes += 1
            else:
                failures += 1
            total_progress += progress

    print(f"\n=== Aggregated Results over {total_runs} runs ===")
    print(f"Total Successes: {successes}")
    print(f"Total Failures: {failures}")
    print(f"Average Progress (steps passed before failing or success): {total_progress / (successes + failures):.2f}")

test_mass_race_lambdas(num_threads=100, num_switches=2, total_runs=1000)



print("\n=== Performance Test ===")
import time

def test_bool_list_chain(iterations=1_000_000):
    switches = [True] * 4  # simulate 4 boolean switches

    start = time.perf_counter()
    for _ in range(iterations):
        if switches[0] and switches[1] and switches[2] and switches[3]:
            pass  # pretend to enqueue or proceed
    duration = time.perf_counter() - start

    avg_time_per_op_ns = (duration / iterations) * 1e9
    print(f"Total Time: {duration:.6f} seconds")
    print(f"Average Time per 4-bool-check: {avg_time_per_op_ns:.2f} ns")

test_bool_list_chain()




import threading
import time

def thread_task(switches, iterations, results, thread_id, ready_event):
    ready_event.wait()  # Synchronize start
    start = time.perf_counter_ns()
    for _ in range(iterations):
        if switches[0] and switches[1] and switches[2] and switches[3]:
            pass  # Simulate success path
    end = time.perf_counter_ns()
    results[thread_id] = (end - start) / iterations  # Average ns per iteration

def threaded_bool_check_test(num_threads=10, iterations=100_000):
    switches = [True] * 4  # Shared switches
    results = [0] * num_threads
    ready_event = threading.Event()
    threads = []

    for thread_id in range(num_threads):
        t = threading.Thread(target=thread_task, args=(switches, iterations, results, thread_id, ready_event))
        threads.append(t)
        t.start()

    time.sleep(0.1)  # Give threads time to initialize
    print("Starting threads simultaneously...\n")
    ready_event.set()

    for t in threads:
        t.join()

    print("\n=== Threaded Results ===")
    for i, avg_ns in enumerate(results):
        print(f"Thread {i+1}: {avg_ns:.2f} ns per iteration")

    overall_avg = sum(results) / len(results)
    print(f"\nOverall average: {overall_avg:.2f} ns per iteration")

threaded_bool_check_test(num_threads=10, iterations=100_000)


import threading
import time
import collections

def thread_task2(queue, lock, results, idx, start_event):
    start_event.wait()
    enqueue_times = []
    dequeue_times = []

    # Single enqueue
    start_enqueue = time.perf_counter_ns()
    with lock:
        queue.append(1)
    end_enqueue = time.perf_counter_ns()
    enqueue_times.append(end_enqueue - start_enqueue)

    # Single dequeue
    start_dequeue = time.perf_counter_ns()
    with lock:
        _ = queue.popleft()
    end_dequeue = time.perf_counter_ns()
    dequeue_times.append(end_dequeue - start_dequeue)

    results[idx] = (sum(enqueue_times) / len(enqueue_times), sum(dequeue_times) / len(dequeue_times))

def test_enqueue_dequeue_split(num_threads=10):
    queue = collections.deque()
    lock = threading.RLock()
    start_event = threading.Event()
    threads = []
    results = [None] * num_threads

    for i in range(num_threads):
        t = threading.Thread(target=thread_task2, args=(queue, lock, results, i, start_event))
        threads.append(t)
        t.start()

    start_event.set()

    for t in threads:
        t.join()

    avg_enqueue_ns = sum(r[0] for r in results) / num_threads
    avg_dequeue_ns = sum(r[1] for r in results) / num_threads

    print(f"Average Enqueue Time: {avg_enqueue_ns:.2f} ns")
    print(f"Average Dequeue Time: {avg_dequeue_ns:.2f} ns")

test_enqueue_dequeue_split()
