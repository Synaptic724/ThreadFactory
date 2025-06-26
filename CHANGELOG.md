# 📜 Changelog
All notable changes to this project will be documented in this file.  
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.2.9] - 2025-06-26

### 🚀 Classes Added

- **`ValueWork`**  
  A structured, thread-safe, and `inverted-Future`-like unit of work supporting full lifecycle tracking, cancellation, and hooks.  
  Ideal for orchestrated background task systems and integrates deeply with the `DynamicWorker`.

- **`Dynaphore`**  
    A dynamic semaphore that allows runtime adjustment of permit limits, enabling flexible concurrency control.  
    It allows for scaling up or down based on system load, making it suitable for adaptive threading scenarios.

- **`SmartCondition`**  
  A custom synchronization primitive extending `threading.Condition` with *targeted wakeups* via factory IDs (`ULID` or `"MainThread"`).  
  Supports selective `notify`, `notify_all`, and `wait_for()` by ID — enabling *fine-grained thread routing*.  
  ✔️ Tightly integrated with `SwitchLock` and `DynamicWorker`.

- **`SwitchLock`**  
  A dynamic semaphore built atop `SmartCondition`, offering runtime-adjustable permit scaling and ID-targeted wakeups.  
  Serves as the orchestration core for trap-and-release systems and room-based thread routing.  
  ✔️ Acts as a direct control layer for `DynamicWorker` coordination and queue contention management.

- **`SignalCondition`**  
  A minimal `Condition`-like primitive optimized for simplicity and clarity.  
  - No targeting, no IDs  
  - Always executes callbacks in the *awaited thread*  
  - Designed for producer-consumer signaling and lightweight embedded wake logic

- **`AutoResetTimer`**  
  A compact timer that automatically resets after expiration.  
  Useful for retry loops, timed backoffs, polling gates, or simple coordination between workers.

- **`Stopwatch`**  
  High-resolution timing utility for *nanosecond-level precision*.  
  Used throughout the framework to record task durations, queue latency, and worker throughput.

---

### 🧠 Work Abstraction

- Introduced the **`ValueWork`** class:
  - Auto-dispose behavior for cleanup after result collection
  - Lifecycle hook system (`before`, `after`) for side-effect orchestration
  - Metadata: timestamps, task ID
  - Cancellation via `CancelledError`
---

### 🧵 Dynamic Execution Engine

- Added **`DynamicWorker`** prototype:
  - Executes `ValueWork` with lifecycle awareness
  - Waits using `SwitchLock` with ID-based control
  - Supports checkpointing and behavior swapping via named callables
  - Controlled wake/sleep logic via `SmartCondition`

---

### 🎛️ Queue + Locking Enhancements

- **`ConcurrentQueue`** and **`ConcurrentStack`**
  - Added `is_empty()` for zero-contention guard checks
  - Batch-steal support for improved throughput under high load
---

### 🧪 Performance Notes

#### ⏱ Lock Timing Comparisons
- threading.Lock │ 0.07 µs
- SwitchLock (this) │ 4.40 µs
- Thread Spawn (bare) │ 195.8 µs

#### 🧠 SmartCondition vs. RLock
- Raw RLock.acquire()/release(): ~0.00196s
- SignalCondition wait()/notify(): ~0.01256s
- SignalCondition is ~6.4× slower in low contention.


### ⚙️ Tight Coupling & System Design

- **SmartCondition**, **SwitchLock**, and **DynamicWorker** form the core *orchestration axis* of ThreadFactory.
  - `DynamicWorker` suspends on `SwitchLock`, which routes permit release through `SmartCondition`.
  - This trio enables precise worker control, contention resolution, and targeted awakenings.

---

### 🏗️ ThreadFactory (Scaffolded)

- Introduced initial structure for the `ThreadFactory` execution framework:
  - Modular producer-consumer threading
  - Queue-to-worker routing logic
  - Plans for scaling policies, diagnostics, and `multithreaded-asyncio` integration

---

### ✅ Improvements & Fixes

- Added `__slots__` to all concurrency classes:
  - Reduced memory overhead
  - Improved attribute access speed
  - Lowered GC churn under heavy threading loads

---

### 📌 Notes for Developers

- Migrate worker coordination logic to `SmartCondition` and `SwitchLock`
- Use `ValueWork` as the core unit of execution across sync and async flows
- Adopt `Stopwatch` and `AutoResetTimer` for all time-based tasks and metrics
- Use `SignalCondition` for basic waits, `SmartCondition` for ID-based signaling
- Leverage `ConcurrentQueue.is_empty()` for graceful shutdown and polling guards

---

## [1.2.4] - 2025-05-02

### 🚀 Classes Added

- **`ConcurrentSet`**
  - A thread-safe set implementation designed for high-read and concurrent modification environments.
  - Supports standard set operations (`union`, `intersection`, `difference`, `symmetric_difference`) with both standard and in-place variants.
  - Includes a `freeze()` method that disables mutation and enables lock-free reads for optimal performance under read-heavy workloads.
  - Fully compatible with context managers and implements `IDispose` for lifecycle control.

### ➕ Features

- **Set Algebra Support**
  - Operators: `|`, `&`, `-`, `^` and their in-place variants (`|=`, etc.)
  - Method equivalents: `union()`, `intersection()`, `difference()`, `symmetric_difference()`

- **Functional Utilities**
  - `map(func)`, `filter(func)`, and `reduce(func)` to enable functional programming patterns with thread-safe access.

- **Lock-Aware Reads**
  - Automatically determines whether to acquire a lock or operate lock-free depending on freeze status.
  - `__iter__`, `__len__`, `__contains__`, and copies behave differently in frozen mode for performance.

- **Atomic Batch Operations**
  - `batch_update(func)` allows users to perform multiple modifications under a single lock.

- **Context Manager Integration**
  - Using `with ConcurrentSet(...) as s:` provides exclusive access to the underlying set for manual atomic operations.

- **Freeze Mode**
  - `freeze()` method allows users to lock the `ConcurrentList`, `ConcurrentDict`, or `ConcurrentSet` for read-only access, improving performance in read-heavy scenarios.
  - Once frozen, the collection cannot be modified until it is unfrozen.

### 🛠 Fixes

- **`ConcurrentQueue` and `ConcurrentStack`**
  - Updated `peek()` to use `try/finally` to ensure the lock is always released properly, even when exceptions occur.

- **Comment Improvements**
  - Clarified `concurrent_core` comments explaining the internal lock handling, dispose behavior, and access lifecycle.

### 🔄 Changes

- **License Update**
  - Switched from **MIT** to **Apache 2.0**
    - Provides better attribution enforcement and aligns with modern corporate and open-source compliance standards.

- **NOTICE File**
  - Updated to include formal attribution for all bundled third-party libraries in compliance with Apache 2.0.

- **Standardized Disposal**
  - Introduced `IDispose` base class.
  - All classes implementing disposal now include a consistent `disposed` flag and thread-safe `dispose()` method.

### 📌 Notes for Developers

- `ConcurrentSet` requires elements to be **hashable**. Types like `dict`, `list`, and `set` cannot be added directly.
  - This is a fundamental limitation of Python sets — use `frozenset(dict.items())` if you need to store dict-like data.
  - For non-hashable types, consider using `ConcurrentList` instead.

- Use `freeze()` when you no longer plan to mutate the set — it allows lock-free reads and improves performance dramatically.

- All new concurrent collections now support `IDispose` and can be used safely with `with` statements or explicit cleanup logic.


### ✅ Suggested Actions

- Upgrade to 1.2.1 to take advantage of `ConcurrentSet` and improved lock handling in existing data structures.
- Review any existing `set` usage in concurrent contexts and replace with `ConcurrentSet` where necessary.
- Use `freeze()` for cache-like read-heavy workloads.
- Consider wrapping mutation-heavy operations inside `batch_update()` for better atomicity and throughput.

---

## [1.2.0] - 2025-04-05

### Classes Added

#### ConcurrentCollection
- An unordered, thread-safe alternative to `ConcurrentBuffer`.
- Optimized for high-concurrency scenarios where strict FIFO is not required.
- Uses fair circular scans seeded by bit-mixed monotonic clocks to distribute dequeues evenly.
- Benchmarks (10 producers / 20 consumers, 2M ops) show **~5.6% higher throughput** than `ConcurrentBuffer`:
    - **ConcurrentCollection**: 108,235 ops/sec
    - **ConcurrentBuffer**: 102,494 ops/sec
    - Better scaling under thread contention.

### Added Features

#### Benchmarking System
- A fully modular and extensible **benchmarking suite** has been added to the project.
    - Provides detailed throughput, latency, and concurrency tests for all concurrent classes.
    - Supports custom strategies, ratio scaling, multi-sample tests, and grid sweeps.
    - Results can be exported to CSV, JSON, or YAML.
    - Pre-integrated with a visualization tool for plotting benchmark results.
    - Available for cloned or forked projects to simplify validation and profiling of custom concurrency classes.

#### Performance Boost
- Optimized `ConcurrentBuffer` with a window-based enqueue strategy alternating between even shard groups.
- Improves enqueue performance by reducing per-operation overhead while preserving approximate FIFO behavior.
- The change is **low risk**, adds no consumer complexity, and maintains API compatibility.

#### Shard Consistency Enforcement
- `ConcurrentBuffer` now requires an **even number of shards** (≥2) to enable the windowing strategy.
- Odd shard counts (>1) will now raise a `ValueError`.
- Single shard mode is still supported.

#### Benchmark-Validated
Internal benchmarks confirm `ConcurrentBuffer` improvements:
- **6× faster** than `multiprocessing.Queue`.
- **~2.6× faster** than `collections.deque` (with Lock).
- **~60% faster** than `ConcurrentQueue`.
- Tests performed under balanced workloads (10 Producers / 10 Consumers, 1M operations).

### Fixes
- Removed lock from `peek()` in `ConcurrentQueue` and `ConcurrentStack` to improve performance.
- Implemented the Disposable pattern from .NET into all classes for easier resource management.

---

## [1.1.0] - 2025-03-26

### Classes Added

#### 1. Dynaphore  
- A dynamic semaphore supporting runtime tuning of limits.

#### 2. ConcurrentBuffer  
- A thread-safe, general-purpose concurrent buffer.  
- Not strictly FIFO or LIFO.  
- Best suited for low to moderate contention.  
- For high contention, prefer `ConcurrentQueue` or `ConcurrentStack`.

### Added Features
- `update()` method for `ConcurrentBag` and `ConcurrentList` (bulk updates).
- `remove()` method for `ConcurrentQueue` and `ConcurrentStack`.
- Performance testing integrated into `unittest` suite.
  
### Fixes
- Changed imports from relative to absolute.
- Introduced small sleep in `ConcurrentStack` and `ConcurrentQueue` (`time.sleep(0.001)`) to provide backpressure.

---

## [1.0.1] - 2025-03-22

### Classes Added

#### 1. ConcurrentBag  
- Thread-safe multiset supporting duplicates.  
- Standard methods: `add`, `remove`, `discard`, etc.

#### 2. ConcurrentDict  
- Thread-safe dictionary supporting safe bulk operations.  
- Includes `map`, `filter`, `reduce`.

#### 3. ConcurrentList  
- Thread-safe list supporting concurrent modifications.
- Supports slice assignment, in-place operators (`+=`, `*=`), and bulk methods.

#### 4. ConcurrentQueue  
- Thread-safe FIFO queue using `deque`.  
- Supports `enqueue`, `dequeue`, `peek`, `map`, `filter`, and `reduce`.  
- Raises `Empty` when needed.

#### 5. ConcurrentStack  
- Thread-safe LIFO stack.  
- Built on `deque`.  
- `push`, `pop`, `peek` operations.

#### 6. Parallel Utilities (TPL-like)  
- `parallel_for`, `parallel_foreach`, `parallel_invoke`, `parallel_map`.  
- Pure threading-based concurrency with optional early exit, chunking, and local state support.
- Inspired by .NET's Task Parallel Library (TPL).
