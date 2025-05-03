# 📜 Changelog
All notable changes to this project will be documented in this file.  
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

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

## [1.2.1] - 2025-04-08

### Classes Added
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

### Added Features
- Integrated time-tracking capabilities through `Stopwatch` and `AutoResetTimer` to support precise performance metrics and scheduled operations.
- Introduced the first version of the `Work` abstraction for structured task submission, response handling, and optional callbacks.
- Added targeted thread trapping and wakeup mechanisms via `SmartCondition`, allowing threads to wait on logical `factory_ids` and be selectively released based on those IDs.
- Introduced `SwitchLock` to orchestrate semaphore-like control with dynamic permit scaling and smart ID-based synchronization.  
  Supports granular release control, timed thread suspension, and future-safe thread disposal coordination.
- Added batch steal support to `ConcurrentQueue` and `ConcurrentStack`, allowing for efficient bulk operations and improved performance in high-contention scenarios.

### Fixes
- Updated comments for `concurrent_core` to clarify the purpose and usage.
- Updated `peak()` statements in both `ConcurrentQueue` and `ConcurrentStack` with `try/finally` blocks to ensure locks are released even in the event of an exception.

### Changes
- Updated license from **MIT** to **Apache 2.0**, enabling stronger attribution controls and broader compliance with corporate and open-source ecosystems.
- Updated `NOTICE` attribution to formally acknowledge third-party libraries in compliance with Apache 2.0 distribution guidelines.

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
