# 📜 Changelog
All notable changes to this project will be documented in this file.  
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

# 🧵 ThreadFactory v1.5.1 – Massive Concurrency Upgrade

ThreadFactory now introduces a modular concurrency stack built from first principles.  
This release splits the system into high-performance primitives, orchestrators, dispatchers, sync types, and agentic thread tools.

---

## 🔒 Sync Types – `concurrency.sync_types`

Thread-safe wrappers for Python’s core data types. Built for deterministic, low-contention, concurrent access across threads.
These types are also now reference types and are no longer treated like simple values (Use them cautiously).

- `SyncInt`: Atomic integer wrapper with arithmetic and bitwise support.
- `SyncBool`: Thread-safe boolean with full logical operation support.
- `SyncString`: Thread-safe mutable wrapper around Python’s `str`, with full dunder and method coverage.
- `SyncFloat`: Atomic float wrapper with arithmetic and bitwise support.
- `SyncRef`: Thread-safe, atomic reference to any object — enables safe read/write access and conditional updates.

These types are ideal for shared state in threaded environments, worker pools, and agent execution contexts.

---

## 🧠 New Primitives – `synchronization.primitives`

### 🎛 `Dynaphore`
A dynamically resizable permit gate. Ideal for adaptive queues, resource throttling, and elastic thread pools.

### 🔁 `FlowRegulator`
Smart semaphore with factory ID targeting, callback routing, and bias buffering. Great for agentic workers and dynamic wakeups.

### 🧠 `SmartCondition`
Thread-aware `Condition` alternative. Allows targeted wakeups, ULID tracking, and callback delivery to waiting threads.

### 🔔 `TransitCondition`
Minimalist wait/notify condition. Callback always executes inside the waiting thread. Lightweight and FIFO-safe.

### 🛑 `SignalLatch`
Latch with observer signaling support. Can notify a controller before blocking. Uses `SignalCondition` internally.
This object can natively connect to a `SignalController` for lifecycle management.

### 🔒 `Latch`
Classic reusable latch. Once opened, all threads are released permanently until reset.

---

## ⚡ New Coordinators – `synchronization.coordinators`

### 🎯 `TransitBarrier`
Reusable barrier with threshold coordination and optional callable execution once threshold is met.

### 🚦 `SignalBarrier`
Reusable barrier with signal-based coordination. Supports threshold, timeout, and failure states.
This object can natively connect to a `SignalController` for lifecycle management.

### ⏰ `ClockBarrier`
Barrier with global timeout. If not all threads arrive before timeout, the barrier breaks and raises.
This object can natively connect to a `SignalController` for lifecycle management.

### 🚦 `Conductor`
Reusable group synchronizer. Executes tasks after a threshold is met. Supports timeout and failure states.
This object can natively connect to a `SignalController` for lifecycle management.

### 🧠 `MultiConductor`  
Manages multiple `Group` objects with per-group tasks and a global thread threshold. Supports lock-step execution, distributed forked execution (`Fork`), and synchronized forked execution (`SyncFork`). 
Each task can produce multiple outcomes. Reusable across cycles and fully controllable via a `SignalController`.

### 🔍 `Scout`
Predicate-based monitor. One thread blocks while evaluating a predicate with timeout and success/failure callbacks.

---

## 🚉 New Execution Gates – `synchronization.execution`

### 🔀 `TransitGate`
Allows up to `N` threads to execute a pre-bound callable pipeline. Captures results via `Outcome`. Collapses once the cap is reached. Great for controlled bootstraps or one-time initializers.

---

## 🎛 New Dispatchers – `synchronization.dispatchers`

### 🔧 `Fork`
Thread dispatcher that assigns callables based on usage caps. Ensures each callable executes a fixed number of times. Good for simple routing or round-robin-like workloads.

### 🚦 `SignalFork`  
Thread dispatcher that routes threads to callables with usage caps. Executes immediately on arrival. Triggers a callback and notifies a controller when all slots are consumed.
This object can natively connect to a `SignalController` for lifecycle management.

### 🔄 `SyncFork`
Dispatcher that coordinates N threads into callable groups. All callables execute simultaneously once all slots are filled. Supports timeouts and reuse.

### 🔄 `SyncSignalFork`
Dispatcher that coordinates N threads into callable groups just like the SyncFork. It can also execute a callable as a signal.
This object can natively connect to a `SignalController` for lifecycle management.
---

## 🧠 New Controllers – `synchronization.controller`

### 🎮 `SignalController`
Central registry for lifecycle-managed objects. Supports:
- `register()` / `unregister()`
- `invoke()` with pre/post hooks
- Event notification (`notify`)
- Full-thread-safe `dispose()` that recursively tears down all managed objects

It forms the backbone for global coordination, status tracking, and command dispatch.

[//]: # (---)

[//]: # ()
[//]: # (## 🧱 Work Abstractions – `thread_factory.core.work`)

[//]: # ()
[//]: # (### 🪄 `Help_request`)

[//]: # (Inverted `Future` managed by threads themselves. Tracks status &#40;`pending`, `running`, `completed`, `cancelled`, `failed`&#41; and timestamps. Can be used with dynamic workers for agentic execution and result orchestration.)

---

## ⏱️ Timing Utilities – `thread_factory.utilities.timing_tools`

### ⏲️ `AutoResetTimer`
Timer that auto-resets after use. Useful for cyclic backoff, loop pacing, and heartbeat monitoring.

### 🕰️ `Stopwatch`
Simple nanosecond-precision profiler. Used for queue stats, lock contention tracking, and execution spans.

---

## ⏱️ Utilities – `thread_factory.utils.coordination.package`

### ⏲️ `Package`
Thread-safe delegate style wrapper for callables.

---

## 📦 Queues and Stacks – `thread_factory.concurrency`

### 🪜 `ConcurrentQueue` / `ConcurrentStack`
New features:
- `is_empty()` added for shutdown checks
- `batch_steal()` support for optimized consumer loops
- Thread-safe with no-lock peek/guard patterns

---

## ✅ Structural Improvements

- 🔐 **All concurrency classes now use `__slots__`**
  - Reduced memory footprint
  - Faster attribute access
  - Less GC churn under stress

- 📁 **New Folder Structure**
- synchronization/
- ├── primitives/
- ├── orchestrators/
- ├── dispatchers/
- ├── execution/
- └── controller/


Each category maps directly to purpose:
- `primitives`: Low-level synchronization building blocks
- `orchestrators`: Group coordination & flow control
- `dispatchers`: Thread-callable routing logic
- `execution`: Execution gates & work-limited runners
- `controller`: Lifecycle and command management

---

## 📌 Developer Notes

- Prefer `FlowRegulator` + `SmartCondition` for worker-oriented design.
- Use `ValueWork` as the new core unit of thread-initiated tasks.
- For fork-like behavior, use `Fork` or `SyncFork`.
- Adopt `Stopwatch` and `AutoResetTimer` for instrumentation.
- Use `SignalCondition` for simplicity, `SmartCondition` for targeting.
- Use `ConcurrentQueue.is_empty()` to manage graceful shutdowns.
- 

---

## Important Changes

- *ActionBarrier* renamed to 'TransitBarrier' to better reflect its purpose.
- *SignalCondition* renamed to 'TransitCondition' for consistency with the new naming scheme.

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
