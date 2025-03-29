# 📜 Changelog
All notable changes to this project will be documented in this file.  
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- Thread role assignment framework (Producer, Consumer, Orchestrator).
- ThreadSwitch logic for dynamic execution context migration.
- Queue state management using Active and Empty stacks.
- Contention mode system (0-10 scale) with dynamic tuning.
- Work stealing optimization with concurrent list handling.

---

## [1.1.1] - 2025-03-30

### Classes Added

#### 1. ConcurrentCollection  
- An unordered, thread-safe alternative to `ConcurrentBuffer`.  
- Optimized for high-concurrency scenarios where strict FIFO is not required.  
- Uses fair circular scans seeded by bit-mixed monotonic clocks to distribute dequeues evenly.  
- Benchmarks (10 producers / 20 consumers, 2M ops) show **~5.6% higher throughput** than `ConcurrentBuffer`:  
    - **ConcurrentCollection**: 108,235 ops/sec  
    - **ConcurrentBuffer**: 102,494 ops/sec  
    - Better scaling under thread contention.

### Added Features

- **Performance Boost**  
    Optimized `ConcurrentBuffer` with a window-based enqueue strategy alternating between even shard groups.  
    Improves enqueue performance by reducing per-operation overhead while preserving approximate FIFO behavior.  
    The change is **low risk**, adds no consumer complexity, and maintains API compatibility.

- **Shard Consistency Enforcement**  
    `ConcurrentBuffer` now requires an **even number of shards** (≥2) to enable the windowing strategy.  
    Odd shard counts (>1) will now raise a `ValueError`.  
    Single shard mode is still supported.

- **Benchmark-Validated**  
    Internal benchmarks confirm `ConcurrentBuffer` improvements:
    - **6× faster** than `multiprocessing.Queue`.
    - **~2.6× faster** than `collections.deque` (with Lock).
    - **~60% faster** than `ConcurrentQueue`.
    - Tests performed under balanced workloads (10 Producers / 10 Consumers, 1M operations).

### Fixes
- Removed lock from `peek()` in `ConcurrentQueue` and `ConcurrentStack` to improve performance.

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
