import threading
import time
from collections import Counter

import time
import threading
from collections import deque

import threading
from collections import deque
import time

def worker_enqueue_dequeue(lock, queue, iterations, results, thread_id, ready_event):
    ready_event.wait()  # Ensure all threads start at the same time
    start = time.perf_counter_ns()
    for _ in range(iterations):
        with lock:
            queue.append(1)
        with lock:
            queue.popleft()
    end = time.perf_counter_ns()
    #print(f"Time for thread {thread_id}: {end - start} ns")
    results[thread_id] = (end - start)  # Store total time for the thread

def test_deque_with_rlock(num_threads=100, iterations=500):
    lock = threading.RLock()
    queue = deque()
    results = [0] * num_threads
    threads = []
    ready_event = threading.Event()

    for i in range(num_threads):
        t = threading.Thread(target=worker_enqueue_dequeue, args=(lock, queue, iterations, results, i, ready_event))
        threads.append(t)
        t.start()

    ready_event.set()  # Let all threads start simultaneously

    for t in threads:
        t.join()

    total_time_ns = sum(results)
    total_operations = num_threads * iterations
    if total_operations > 0:
        avg_ns_per_operation = total_time_ns / total_operations
        print(f"Average time per enqueue + dequeue (across all threads): {avg_ns_per_operation:.2f} ns")
    else:
        print("No operations performed.")
print("Test")
test_deque_with_rlock(1, 1000)

import threading
from collections import Counter
import time

def race_path_lambdas(flags, result, thread_id, ready_event, end_path_lock, threads_at_end_counter):
    ready_event.wait()  # wait until GO
    progress = 0
    start = time.perf_counter_ns()

    for i in range(len(flags)):
        if flags[i] == 0:
            flags[i] = thread_id  # claim slot
            progress += 1
        else:
            # Race condition detected
            end = time.perf_counter_ns()
            result.append({
                "thread": thread_id,
                "status": "FAILED",
                "progress": progress,
                "time_ns": end - start
            })
            return

    # Finished successfully
    end = time.perf_counter_ns()
    with end_path_lock:
        threads_at_end_counter[0] += 1
        result.append({
            "thread": thread_id,
            "status": "SUCCESS",
            "progress": progress,
            "time_ns": end - start
        })

def test_mass_race_lambdas(num_threads=20, num_switches=10, rounds=1000):
    progress_counter = Counter()
    all_threads_reached_end_count = 0
    total_rounds = rounds
    threads_reached_end_per_round = []
    threads_at_end_aggregation = Counter()
    total_success_time_ns = 0
    total_successful_runs = 0

    for round_num in range(total_rounds):
        flags = [0 for _ in range(num_switches)]
        result = []
        ready_event = threading.Event()
        threads = []
        end_path_lock = threading.Lock()
        threads_at_end_counter = [0]  # Use a list to pass by reference

        for thread_id in range(1, num_threads + 1):
            t = threading.Thread(target=race_path_lambdas, args=(flags, result, thread_id, ready_event, end_path_lock, threads_at_end_counter))
            threads.append(t)
            t.start()

        ready_event.set()

        for t in threads:
            t.join()

        threads_reached_end = threads_at_end_counter[0]
        threads_reached_end_per_round.append(threads_reached_end)
        threads_at_end_aggregation[threads_reached_end] += 1
        if threads_reached_end == num_threads:
            all_threads_reached_end_count += 1

        for r in result:
            if r['status'] == "FAILED":
                progress_counter[r['progress']] += 1
            elif r['status'] == "SUCCESS":
                total_success_time_ns += r['time_ns']
                total_successful_runs += 1

    total_failures = total_rounds - all_threads_reached_end_count

    print("\n=== Final Aggregated Results ===")
    print(f"Total Rounds: {total_rounds}")
    print(f"Rounds where all {num_threads} threads reached the end: {all_threads_reached_end_count}")
    print(f"Rounds with at least one failure: {total_failures}")

    if total_successful_runs > 0:
        average_success_time_ns = total_success_time_ns / total_successful_runs
        print(f"Average time for successful traversal (across all successful threads): {average_success_time_ns:.2f} ns")
    else:
        print("No successful traversals to calculate average time.")

    print("\n=== Threads Reaching End Per Round ===")
    for i, count in enumerate(threads_reached_end_per_round):
        pass
        #print(f"Round {i + 1}: {count} threads reached the end")

    print("\n=== Aggregated Threads Reaching End Across All Rounds ===")
    for num_threads_reached, count in sorted(threads_at_end_aggregation.items()):
        print(f"{num_threads_reached} threads reached the end: {count} times")

    print("\n=== Failure Progress Distribution ===")
    total_failure_occurrences = sum(progress_counter.values())
    if total_failure_occurrences > 0:
        for i in range(num_switches + 1):
            count = progress_counter[i]
            pct = (count / total_failure_occurrences * 100) if total_failure_occurrences else 0
            print(f"Failed at switch {i}: {count} times ({pct:.2f}%)")
    else:
        print("No failures occurred.")

# Example usage:
test_mass_race_lambdas(num_threads=5, num_switches=20, rounds=1)