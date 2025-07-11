[![PyPI version](https://badge.fury.io/py/threadfactory.svg)](https://badge.fury.io/py/threadfactory)
[![License](https://img.shields.io/github/license/Synaptic724/threadfactory)](https://github.com/Synaptic724/threadfactory/blob/production/LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/threadfactory)](https://pypi.org/project/threadfactory)

[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory/month)](https://pepy.tech/projects/threadfactory)
[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory/week)](https://pepy.tech/projects/threadfactory)
[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory)](https://pepy.tech/projects/threadfactory)

[![Upload Python Package](https://github.com/Synaptic724/ThreadFactory/actions/workflows/python-publish.yml/badge.svg)](https://github.com/Synaptic724/threadfactory/actions/workflows/python-publish.yml)
[![Docs](https://readthedocs.org/projects/threadfactory/badge/?version=latest)](https://threadfactory.readthedocs.io/en/latest/)


<!--[![Coverage Status](https://coveralls.io/repos/github/Synaptic724/threadfactory/badge.svg?branch=main)](https://coveralls.io/github/Synaptic724/threadfactory?branch=main) -->
<!--[![CodeFactor](https://www.codefactor.io/repository/github/synaptic724/threadfactory/badge)](https://www.codefactor.io/repository/github/synaptic724/threadfactory) -->

High-performance concurrency toolkit — built **exclusively** for No-GIL Python 3.13+.  
Scale across threads. Control the flow. Welcome to Python’s next generation of parallelism.

## ✨ Why ThreadFactory? Unlocking Peak Concurrency Performance

Tired of battling race conditions and deadlocks in your multiprocessing Python applications? ThreadFactory provides a meticulously crafted suite of tools designed for **uncompromising thread safety and blazing-fast performance**.

Here's how ThreadFactory elevates your concurrency game:

* 🔒 **Sync Types: Atomic & Immutable-like Control**
    Experience effortless thread-safe manipulation of fundamental data types. Our `SyncInt`, `SyncBool`, `SyncString`, and more, act as atomic wrappers, guaranteeing data integrity without complex locking rituals.  These types are also now reference types and are no longer treated like simple values (Use them cautiously).

* 🤝 **Concurrent Collections: High-Performance Shared Data Structures**
    Transform your shared data management. Access and modify dictionaries, lists, sets, queues, stacks, and buffers with confidence, knowing they are built for high-load, concurrent environments. **🔥 Say goodbye to data corruption!**

* 📦 **Pack / Package: Delegate-Style Callables for Agentic Threads**  
    Encapsulate sync functions with full thread-safe state control. `Pack` stores arguments, supports currying, composition (`|`, `+`), and dynamic introspection. Ideal for agent behaviors, orchestration flows, and deferred execution.  
    **→ Think `functools.partial` meets `Promise`, optimized for concurrency.**

* 🔬 **First-Principles Primitives: Building Blocks for Robust Systems**
    Dive deeper with powerful, low-level synchronization constructs like `Dynaphore` (dynamic semaphores), `SmartCondition` (intelligent condition variables), and `SignalLatch` (one-shot signal mechanisms). Engineer sophisticated thread interactions with precision.

* 🧩 **Orchestrators & Barriers: Harmonize Complex Workflows**
    Coordinate your threads with elegance. Leverage `TransitBarrier` for phased execution, `SignalBarrier` for event-driven synchronization, and `Conductor` for orchestrating intricate task flows. Ensure your threads march in perfect unison.

* ⚡ **Dispatchers & Gates: Fine-Grained Thread Control**
    Control thread execution with surgical precision. Utilize `Fork` for parallel execution, `SyncFork` for synchronized branching, and `TransitGate` for managing access to critical sections.

* 🚀 **Benchmarks that Prove the Speed: 2×–5× Faster Under Load!**
    Don't just take our word for it. ThreadFactory isn't just safer; it's *faster*. Our rigorous benchmarks consistently demonstrate **2x to 5x speed improvements** over standard library alternatives under heavy concurrent loads. All battle-tested with **10 Million to 20 Million operation** stress runs and ***zero* deadlocks**.

**ThreadFactory: Build Confidently. Run Faster.**

> **NOTE**  
> ThreadFactory is designed and tested against Python 3.13+ in **No-GIL** mode.  
> This library will only function on 3.13 and higher as it is a **No-GIL Exclusive** library.

Please see the benchmarks at the bottom of this page and if you are interested there are more in the repository.  

[Repository Benchmarks 🚀](https://github.com/Synaptic724/threadfactory/blob/production/benchmarks/benchmark_data/general_benchmarks.md)  
[Jump to Benchmarks Below🔥](#-benchmark-results-10000000-ops--10-producers--10-consumers)

---

## 🌟 Support the Project

If you find **ThreadFactory** useful, **please consider [starring the repository](https://github.com/Synaptic724/threadfactory/)** and **watching it for updates** 🔔!

Your support helps:
- Grow awareness 🧠  
- Justify deeper development 💻  
- Keep high-performance Python in the spotlight ⚡

Every ⭐ star shows there's a need for **GIL-free, scalable concurrency** in Python.  
Thank you for helping make that vision real ❤️

If you really love my work please connect with me on [LinkedIn](https://www.linkedin.com/in/mark-geleta/) and feel free to chat with me there.

> You can also [open an issue](https://github.com/Synaptic724/ThreadFactory/issues) or [start a discussion](https://github.com/Synaptic724/threadfactory/discussions) — I’d love to hear how you're using ThreadFactory or what you'd like to see next!
---

## 🚀 Features

## 🔒 Sync Types – `thread_factory.concurrency.sync_types`

ThreadFactory's **Sync Types** are thread-safe wrappers for Python’s core data types. They're built for deterministic, low-contention, concurrent access across threads, making them perfect for shared state in threaded environments, worker pools, and agent execution contexts.

* `SyncInt`: An atomic integer wrapper with full arithmetic and bitwise operation support.
* `SyncFloat`: A thread-safe float that supports all arithmetic operations, ensuring precision in concurrent calculations.
* `SyncBool`: A thread-safe boolean that handles all logical operations safely.
* `SyncString`: A thread-safe mutable wrapper around Python’s `str`, offering comprehensive dunder method and string method coverage.
* `SyncRef` : A thread-safe, atomic reference to any object with conditional updates and safe data access.

---

## 📦 Concurrent Data Structures - `thread_factory.concurrency`

ThreadFactory provides a robust suite of **Concurrent Data Structures**, designed for high-performance shared data management in multi-threaded applications.

### `ConcurrentDict`
- A thread-safe dictionary.
- Supports typical dict operations (`update`, `popitem`, etc.).
- Provides `map`, `filter`, and `reduce` for safe, bulk operations.
- **Freeze support**: When frozen, the dictionary becomes read-only. Lock acquisition is skipped during reads, dramatically improving performance in high-read workloads.

### `ConcurrentList`
- A thread-safe list supporting concurrent access and modification.
- Slice assignment, in-place operators (`+=`, `*=`), and advanced operations (`map`, `filter`, `reduce`).
- **Freeze support**: Prevents structural modifications while enabling safe, lock-free reads (e.g., `__getitem__`, iteration, and slicing). Ideal for caching and broadcast scenarios.

### `ConcurrentSet`
- A thread-safe set implementation supporting all standard set algebra operations.
- Supports `add`, `discard`, `remove`, and all bitwise set operations (`|`, `&`, `^`, `-`) along with their in-place forms.
- Provides `map`, `filter`, `reduce`, and `batch_update` to safely perform bulk transformations.
- **Freeze support**: Once frozen, the set cannot be modified — but read operations become lock-free and extremely efficient.
- Ideal for workloads where the set is mutated during setup but then used repeatedly in a read-only context (e.g., filters, routing tables, permissions).

### `ConcurrentQueue`
- A thread-safe FIFO queue built atop `collections.deque`.
- Tested and outperforms deque alone by up to 64% in our benchmark.
- Supports `enqueue`, `dequeue`, `peek`, `map`, `filter`, and `reduce`.
- Raises `Empty` when `dequeue` or `peek` is called on an empty queue.
- Outperforms multiprocessing queues by over 400% in some cases — clone and run unit tests to see.

### `ConcurrentStack`
- A thread-safe LIFO stack.
- Supports `push`, `pop`, `peek` operations.
- Ideal for last-in, first-out (LIFO) workloads.
- Built on `deque` for fast appends and pops.
- Similar performance to ConcurrentQueue.

### `ConcurrentBuffer`
- A **high-performance**, thread-safe buffer using **sharded deques** for low-contention access.
- Designed to handle massive producer/consumer loads with better throughput than standard queues.
- Supports `enqueue`, `dequeue`, `peek`, `clear`, and bulk operations (`map`, `filter`, `reduce`).
- **Timestamp-based ordering** ensures approximate FIFO behavior across shards.
- Outperforms `ConcurrentQueue` by up to **60%** in mid-range concurrency in even thread Producer/Consumer configuration with 10 shards.
- Automatically balances items across shards; ideal for parallel pipelines and low-latency workloads.
- Best used with `shard_count ≈ thread_count / 2` for optimal performance, but keep shards at or below 10.

### `ConcurrentCollection`
- An unordered, thread-safe alternative to `ConcurrentBuffer`.
- Optimized for high-concurrency scenarios where strict FIFO is not required.
- Uses fair circular scans seeded by bit-mixed monotonic clocks to distribute dequeues evenly.
- Benchmarks (10 producers / 20 consumers, 2M ops) show **~5.6% higher throughput** than `ConcurrentBuffer`:
    - **ConcurrentCollection**: 108,235 ops/sec
    - **ConcurrentBuffer**: 102,494 ops/sec
    - Better scaling under thread contention.

### `ConcurrentBag`
- A thread-safe “multiset” collection that allows duplicates.
- Methods like `add`, `remove`, `discard`, etc.
- Ideal for collections where duplicate elements matter.

---

## 🛠 Primitives & Coordination Mechanisms

ThreadFactory goes beyond collections, offering finely engineered synchronization primitives and specialized tools for orchestration, diagnostics, and thread-safe control.

### 🧠 Core Primitives – `thread_factory.synchronization.primitives`

* 🎛 `Dynaphore`: A **dynamically resizable permit gate** for adaptive resource control and elastic thread pools.
* 🔁 `FlowRegulator`: A **smart semaphore** with factory ID targeting, callback routing, and bias buffering for dynamic wakeups in agentic worker systems.
* 🧠 `SmartCondition`: A **next-generation `Condition` replacement** enabling **targeted wakeups**, ULID tracking, and direct callback delivery to waiting threads.
* 🔔 `TransitCondition`: A **minimalist wait/notify condition** where callbacks execute within the waiting thread, ensuring lightweight and FIFO-safe signaling.
* 🛑 `SignalLatch`: A **latch with observer signaling support**, capable of notifying a controller before blocking. It natively connects to a `SignalController` for streamlined lifecycle management.
* 🔒 `Latch`: A classic **reusable latch** that, once opened, permanently releases all waiting threads until explicitly reset.
* 
### ⚡ Coordinators & Barriers – `thread_factory.synchronization.coordinators`

* 🎯 `TransitBarrier`: A **reusable barrier** for sophisticated threshold coordination, with the option to execute a callable once all threads arrive.
* 🚦 `SignalBarrier`: A **reusable, signal-based barrier** that supports thresholds, timeouts, and failure states, natively connecting to a `SignalController` for integrated lifecycle management.
* ⏰ `ClockBarrier`: A **barrier with a global timeout** that breaks and raises an exception if all threads don't arrive within the specified duration. It natively connects to a `SignalController`.
* 🚦 `Conductor`: A **reusable group synchronizer** that executes tasks after a threshold is met, supporting timeouts and failure states. This object also natively connects to a `SignalController`.
* 🧠 `MultiConductor`: A **multi-group execution coordinator** that manages multiple `Group` objects with a global thread threshold. Supports synchronized execution, `Fork`-based distributed dispatch, and `SyncFork`-based barrier coordination. 
                       Each task can produce multiple outcomes. Fully reusable and natively integrated with a `SignalController`.
* 🔍 `Scout`: A **predicate-based monitor** where a single thread blocks while evaluating a custom predicate, complete with timeout, success, and failure callbacks.

### 🚉 Execution Gates – `thread_factory.synchronization.execution`

* 🔀 `BypassConductor`: Allows up to `N` threads to **execute a pre-bound callable pipeline**, capturing results via `Outcome`. It collapses once the execution cap is reached, making it ideal for controlled bootstraps or one-time initializers.

### 🎛 Dispatchers – `thread_factory.synchronization.dispatchers`

* 🔧 `Fork`: A **thread dispatcher** that assigns callables based on usage caps, ensuring each executes a fixed number of times for simple routing.
* 🔄 `SyncFork`: A **dispatcher that coordinates `N` threads** into callable groups, where all callables execute simultaneously once slots are filled. It supports timeouts and reuse.
* 🔄 `SyncSignalFork`: Similar to `SyncFork`, but with the added ability to **execute a callable as a signal**. This object natively connects to a `SignalController` for enhanced integration.
* 🚦 `SignalFork`: A **non-blocking dispatcher** that routes threads to callables immediately upon arrival. Triggers a one-time callback and controller notification once all slots are consumed.

### 🎮 Central Controllers – `thread_factory.synchronization.controller`

* ### `SignalController`
    The **central registry and backbone** for lifecycle-managed objects within ThreadFactory. It offers robust support for:
    * **`register()` / `unregister()`**: Dynamically add or remove managed objects.
    * **`invoke()` with pre/post hooks**: Trigger operations across registered components with custom logic before and after.
    * **Event notification (`notify`)**: Broadcast events to all interested managed objects.
    * **Full-thread-safe `dispose()`**: Recursively and safely tears down all managed objects, ensuring proper resource release and preventing leaks in complex systems.
    The `SignalController` forms the foundation for global coordination, status tracking, and command dispatch, providing a powerful hub for your concurrency architecture.
---

## ⚡ Parallel Utilities - `thread_factory.concurrency`

ThreadFactory provides a powerful collection of **parallel programming utilities** inspired by .NET's Task Parallel Library (TPL), simplifying common concurrent patterns.

* ### `parallel_for`
    Executes a traditional `for` loop in parallel across multiple threads. It supports automatic chunking, optional `local_init`/`local_finalize` for per-thread state, and `stop_on_exception` for early abortion on error.

* ### `parallel_foreach`
    Executes an `action` function on each item of an iterable in parallel. It handles both pre-known-length and streaming iterables, with optional `chunk_size` tuning and `stop_on_exception` to halt on errors. Ideal for efficient processing of large or streaming datasets.

* ### `parallel_invoke`
    Executes multiple independent functions concurrently. It accepts an arbitrary number of functions, returning a list of futures representing their execution, with an option to wait for all to finish. This simplifies running unrelated tasks in parallel with easy error propagation.

* ### `parallel_map`
    The **parallel equivalent of Python’s built-in `map()`**. It applies a `transform` function to each item in an iterable concurrently, maintaining result order. Work is automatically split into chunks for efficient multi-threaded execution, returning a fully materialized list of results.

### Notes for Parallel Utilities

* All utilities automatically default to `max_workers = os.cpu_count()` if unspecified.
* `chunk_size` can be manually tuned or defaults to roughly `4 × #workers` for balanced performance.
* Exceptions raised inside tasks are properly propagated to the caller.

---

## ⏱️ Utilities – `thread_factory.utilities`

ThreadFactory includes precise **utility tools** for orchestration, diagnostics, and thread-safe execution in concurrent applications.

* ⏲️ `AutoResetTimer`: A **self-resetting timer** that automatically expires and restarts — perfect for retry loops, cooldowns, debounce filters, and heartbeat monitoring.
* 🕰️ `Stopwatch`: A **high-resolution, nanosecond-accurate profiler** built on `time.perf_counter_ns()` — ideal for measuring critical path latency, thread timing, and pinpointing performance bottlenecks.
* 📦 `Package`: A **thread-safe, delegate-style callable wrapper** that stores arguments, supports currying and composition, and enables introspectable call chaining. Perfect for orchestration tools like `Conductor`, `Fork`, and `SyncFork`.


---

## 📖 Documentation

Full API reference and usage examples are available at:

➡️ [https://threadfactory.readthedocs.io](https://threadfactory.readthedocs.io)

---

## ⚙️ Installation

### Option 1: Clone and Install Locally (Recommended for Development)

```bash
# Clone the repository
git clone https://github.com/Synaptic724/ThreadFactory.git
cd threadfactory

# Create a Python 3.13+ virtual environment (No-GIL/Free concurrency recommended)
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
```

### Option 2: Install the library from PyPI
```bash
# Install the library in editable mode
pip install threadfactory
```


---

## 📈 Real-World Benchmarking

Below are benchmark results from live multi-threaded scenarios using 10–40 real threads,  
with millions of operations processed under load.

These benchmarks aren't just numbers —  
they are proof that **ThreadFactory's concurrent collections outperform traditional Python structures by 2x–5x**,  
especially in the new No-GIL world Python 3.13+ is unlocking.

Performance under pressure.  
Architecture built for the future.

These are just our Concurrent Datastructures and not even the real thing.  
Threadfactory is coming soon...

---

> All benchmark tests below are available if you clone the library and run the tests.  
> See the [Benchmark Details 🚀](https://github.com/Synaptic724/threadfactory/blob/production/benchmarks/benchmark_data/general_benchmarks.md) for more benchmark stats.


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

---

## 🧪 Coming Soon: ThreadFactory Evolves

ThreadFactory isn't stopping at collections and locks — we're building the **foundation of a full concurrency ecosystem**.

### 🔮 On the Roadmap:
- **Dynamic Executors**: Adaptive thread pools with per-worker routing, priorities, and work stealing.
- **Event Semaphores**: Async-aware signaling for mixed coroutine + thread pipelines.
- **Factory-Orchestrated Graph-based Execution**: Push-based directed graphs or generic graphs of work that dynamically scale.
- **Thread-Aware Async Hooks**: Bridging `asyncio` and raw threads using hybrid schedulers.
- **Task Affinity Routing**: Route work based on thread-local cache or historical execution profile.
- **Metrics and Diagnostics API**: Inspect thread throughput, wait time, and contention hotspots live.

> ThreadFactory isn't just a library.  
> It's becoming a platform.

Stay tuned.  
You haven't seen anything yet.
