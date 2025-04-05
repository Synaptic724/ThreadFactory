

> **GENERAL BENCHMARKS**  
> The below benchmarks are designed to evaluate the performance of various queue implementations under different conditions.

## 🔥 Benchmark Results (1,000,000 ops — 10 Producers / 10 Consumers)

| Queue Type                                   | Time (sec) | Throughput (ops/sec) | Notes                                                                           |
|----------------------------------------------|------------|----------------------|---------------------------------------------------------------------------------|
| `multiprocessing.Queue`                      | 12.53      | ~79,779              | IPC-focused queue, underperforms significantly with threading.  |
| `thread_factory.ConcurrentBuffer` | **2.34**   | **~427,350**         | ⚡Fastest. Bit-flip balanced with even-shard windowing. 10 Shards                |
| `thread_factory.ConcurrentQueue`             | 3.72       | ~268,817             | Strong performer using adaptive locking, well-suited for balanced loads.                              |
| `collections.deque`                          | 6.49       | ~154,085             | Simple and reliable, but limited by internal lock contention. |

### 💡 Observations:
- `ConcurrentBuffer` is **5.35× faster** than `multiprocessing.Queue`.
- `ConcurrentBuffer` is **~1.85× faster** than `deque`.
- `ConcurrentQueue` maintains good performance but is consistently beaten by `ConcurrentBuffer`.
- All queues emptied correctly (`final length = 0`).


---

## 🔥 Benchmark Results (2,000,000 ops — 20 Producers / 10 Consumers)

| Queue Type                        | Time (sec) | Throughput (ops/sec) | Notes                                                                                       |
|-----------------------------------|------------|----------------------|---------------------------------------------------------------------------------------------|
| `multiprocessing.Queue`           | 25.57      | ~78,295              | Performance limited due to process-safe locks unsuitable for thread-only workloads.             |
| `thread_factory.ConcurrentBuffer` | 10.70      | ~186,916             | Performs well with moderate concurrency. Optimal with 10 shard configuration. |
| `thread_factory.ConcurrentQueue`  | **7.19** | **~278,164** | ⚡ Best performer here. Lock adaptation handles higher producer counts efficiently.                                      |
| `collections.deque`               | 11.67      | ~171,379             | Performs acceptably, but scaling is limited by its global lock.           |

### 💡 Observations:
- `ConcurrentQueue` was the fastest in this benchmark.
- `ConcurrentQueue` is **~3.56× faster** than `multiprocessing.Queue`.
- `ConcurrentQueue` is **~1.68× faster** than `deque`.
- `ConcurrentBuffer` performed well but was beaten by `ConcurrentQueue` in this test with a higher producer count.
- All queues emptied correctly (`final length = 0`).

---

## 🔥 Benchmark Results (1,000,000 ops — 10 Producers / 20 Consumers)

| Queue Type                        | Time (sec) | Throughput (ops/sec) | Notes                                                                                      |
|-----------------------------------|------------|----------------------|--------------------------------------------------------------------------------------------|
| `multiprocessing.Queue`           | 12.63      | ~79,177              | Threads suffer due to multiprocessing overheads.              |
| `thread_factory.ConcurrentBuffer` | 9.54       | ~104,822             | Performance degrades under high consumer pressure with 10 shards.                             |
| `thread_factory.ConcurrentBuffer` | 6.73       | ~148,586             | Better performance using 4 shards. Balances well under consumer-heavy load. |
| `thread_factory.ConcurrentQueue`  | **5.35**   | **~186,916**         |⚡ Fastest. Adaptive locking handles high consumer counts smoothly.                                    |
| `collections.deque`               | 9.55       | ~104,712             | Baseline performance. Suffers from lock contention with many consumers.            |

### 💡 Observations:
- `ConcurrentQueue` was the fastest in this benchmark with a higher number of consumers.
- `ConcurrentQueue` is **~2.36× faster** than `multiprocessing.Queue`.
- `ConcurrentQueue` is **~1.26× faster** than `ConcurrentBuffer`.
- `ConcurrentQueue` is **~1.78× faster** than `deque`.
- All queues emptied correctly (`final length = 0`).
- `ConcurrentBuffer` performed well but was beaten by `ConcurrentQueue` in this test with a higher consumer count.
- `ConcurrentBuffer` is still a strong contender with **4 shards** in this scenario. Other variations were tested but failed to produce results.

---

## 🔥 Benchmark Results (10,000,000 ops — 10 producers / 10 consumers)

| Queue Type                                  | Time (sec) | Throughput (ops/sec) | Notes                                                                                             |
|---------------------------------------------|------------|----------------------|---------------------------------------------------------------------------------------------------|
| `multiprocessing.Queue`                     | 119.99     | ~83,336              | Not suited for thread-only workloads, incurs unnecessary overhead.                                |
| `thread_factory.ConcurrentBuffer` | **23.27**      | **~429,651**            | ⚡ Dominant here. Consistent and efficient under moderate concurrency. |
| `thread_factory.ConcurrentQueue`  | 37.87      | ~264,014              | Performs solidly. Shows stable behavior even at higher operation counts.                                                   |
| `collections.deque`                         | 64.16      | ~155,876              | Suffers from contention. Simplicity comes at the cost of throughput.                                  |


### ✅ Highlights:
- `ConcurrentBuffer` outperformed `multiprocessing.Queue` by **96.72 seconds**.
- `ConcurrentBuffer` outperformed `ConcurrentQueue` by **14.6 seconds**.
- `ConcurrentBuffer` outperformed `collections.deque` by **40.89 seconds**.

### 💡 Observations:
- `ConcurrentBuffer` continues to be the best performer under moderate concurrency.
- `ConcurrentQueue` maintains a consistent performance but is outperformed by `ConcurrentBuffer`.
- All queues emptied correctly (`final length = 0`).
---
## 🔥 Benchmark Results (20,000,000 ops — 20 Producers / 20 Consumers)

| Queue Type                                        | Time (sec) | Throughput (ops/sec) | Notes                                                                                         |
|---------------------------------------------------|------------|----------------------|-----------------------------------------------------------------------------------------------|
| `multiprocessing.Queue`                           | 249.92     | ~80,020              | Severely limited by thread-unfriendly IPC locks.                                  |
| `thread_factory.ConcurrentBuffer`      | 138.64     | ~144,270             | 	Solid under moderate producer-consumer balance. Benefits from shard windowing.    |
| `thread_factory.ConcurrentBuffer` | 173.89     | ~115,010             | Too many shards increased internal complexity, leading to lower throughput. |
| `thread_factory.ConcurrentQueue` | **77.69**  | **~257,450**         | ⚡ Fastest overall. Ideal for large-scale multi-producer, multi-consumer scenarios.        |
| `collections.deque`                               | 190.91     | ~104,771             | Still usable, but scalability is poor compared to specialized implementations.         |

### ✅ Notes:
- `ConcurrentBuffer` performs better with **10 shards** than **20 shards** at this concurrency level.
- `ConcurrentQueue` continues to be the most stable performer under moderate-to-high thread counts.
- `multiprocessing.Queue` remains unfit for threaded-only workloads due to its heavy IPC-oriented design.

### 💡 Observations:
- **Shard count** tuning in `ConcurrentBuffer` is crucial — too many shards can reduce performance.
- **Bit-flip balancing** in `ConcurrentBuffer` helps under moderate concurrency but hits diminishing returns with excessive sharding.
- `ConcurrentQueue` is proving to be the general-purpose winner for most balanced threaded workloads.
- For **~40 threads**, `ConcurrentBuffer` shows ~**25% drop** when doubling the number of shards due to increased dequeue complexity.
- All queues emptied correctly (`final length = 0`).

