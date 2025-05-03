# 📜 Changelog
All notable changes to this project will be documented in this file.  
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- **`Work`**  
  A future-compatible, extensible task container designed for expressive async and threaded workloads. Acts as a core unit in the execution system.

- **`AutoResetTimer`**  
  A utility class that resets automatically after expiration. Ideal for retry loops or lightweight state machines.

- **`Stopwatch`**  
  A high-resolution timing utility for measuring task durations with minimal overhead.

- **`SmartCondition`**  
  A thread synchronization primitive similar to `threading.Condition`, but enhanced with *targeted wakeups* via `factory_ids`.  
  Supports selective `notify`, `notify_all`, and predicate-based `wait_for` with ID filtering.  
  Built from scratch for full transparency and fine-grained thread control.

- **`SwitchLock`**  
  A dynamic semaphore built atop `SmartCondition`, enabling runtime-adjustable permits and ID-targeted thread blocking/unblocking.  
  Serves as the foundation for trap-and-release execution models and room-based thread routing.
- 
### Added Features
- Integrated time-tracking capabilities through `Stopwatch` and `AutoResetTimer` to support precise performance metrics and scheduled operations.
- Introduced the first version of the `Work` abstraction for structured task submission, response handling, and optional callbacks.
- Added targeted thread trapping and wakeup mechanisms via `SmartCondition`, allowing threads to wait on logical `factory_ids` and be selectively released based on those IDs.
- Introduced `SwitchLock` to orchestrate semaphore-like control with dynamic permit scaling and smart ID-based synchronization.  
  Supports granular release control, timed thread suspension, and future-safe thread disposal coordination.
- Added batch steal support to `ConcurrentQueue` and `ConcurrentStack`, allowing for efficient bulk operations and improved performance in high-contention scenarios.
- 
#### 🧠 Work Object
- Introduced the `Work` class: a disposable, hook-enabled, metadata-rich extension of `Future`.
- Features:
  - Native `await` support through `__await__` for seamless asyncio compatibility.
  - `auto_dispose` flag to enable automatic cleanup after result or exception retrieval.
  - Lifecycle hook system (`before`, `after`) for execution tracing and side-effect orchestration.
  - Full metadata tracking (task ID, timing metrics, worker/queue binding, retry count).
  - Graceful cancellation with `CancelledError` injection.
  - Thread-safe via internal `_condition` object override.

#### 🧵 Worker Prototype
- Introduced a minimal `Worker` class for executing `Work` instances on background threads.
- Provides early structure for future task orchestration under `ThreadFactory`.

#### 🏗️ ThreadFactory Framework (WIP)
- Scaffolded architecture for the `ThreadFactory` execution system.
- Early goals include:
  - Modular producer-consumer management.
  - Queue-to-worker routing logic.
  - Support for scaling policies and diagnostics interfaces.
- Will form the backbone of both sync and async thread execution systems.

#### 🎫 QueueAllocator
- Added `QueueAllocator`: a ticket-based ID allocator using `ConcurrentQueue`.
- Designed for managing worker/task/thread IDs in a pool-based system.
- Features:
  - Fast, thread-safe ticket acquisition and release.
  - Validates returned IDs for correctness and range.
  - Integrates `Disposable` lifecycle management.
  - Full context manager support with `with` blocks.
  - Enforces internal reuse of ticket IDs for efficient resource control.

### Planned
- `AsyncThreadFactory`: Fully `asyncio`-integrated version of `ThreadFactory`.
- `DiagnosticsInterface`: Real-time throughput, queue, and performance tracking.
- `Orchestrator`: Dynamic coordination of thread lifecycles, workloads, and contention resolution.


### Changes
- `ConcurrentDict` implemented an optimized version of pop.

---
# Changelog

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
