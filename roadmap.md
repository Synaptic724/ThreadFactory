# 🗺️ ThreadFactory Roadmap

## ✅ v1.2 Release (Current)

- **New concurrent core:**
  - `ConcurrentCollection`: High-throughput unordered container  
  - `ConcurrentBuffer`: Shard-optimized with windowed enqueues  

- **`Work` object introduced:**
  - Awaitable wrapper over `Future` with lifecycle hooks  
  - Manual disposal, metadata, and thread-safe operation  

- **`QueueAllocator` added:**
  - Efficient ticket-based ID pool manager  
  - Recyclable, disposable, context-safe  

- **Initial `Worker` scaffolding created**

- **Performance benchmarking suite:**
  - CSV / JSON / YAML export  
  - Integrated plotting system  
  - Validated: up to 6× faster than `multiprocessing.Queue`, up to 2.6× faster than `deque+Lock`  

- **Disposable pattern implemented across all core classes**

---

## 🔨 In Progress (v1.2.x → v2.0)

### 🚀 ThreadFactory: Dynamic Thread Pool / Task Executor

- `ThreadFactory.submit(fn)` → `Work` instance  
- Dynamic worker scaling, priority-aware queueing  
- Support for timeouts, retries, and soft/hard cancellation  
- Custom pluggable queue backends (`deque`, `ConcurrentQueue`, work-stealing)  
- Async-aware thread orchestration  

---

### ⚙️ Advanced Synchronization Primitives

- Reader/Writer Locks with upgrade/downgrade support  
- Spinlocks and lightweight hybrid locks  
- `AsyncLock` and async-compatible synchronization  

---

### 📦 Extended Data Structures

- `ConcurrentSet` with add/remove/map/filter  
- Priority queues: min-heaps, max-heaps, bounded  
- Shared-memory data primitives (future)  
- Lock-free ring buffers (planned)  

---

### 🧠 Work Coordination + Expression Layer

#### `WorkList`

- Submit a list of callables to be executed as a unit  
- Execution modes:
  - `parallel` (all concurrently)
  - `sequential` (ordered execution)
  - `chain` (pipe result to next)
- Support policies:
  - `wait_all`
  - `first_error`
  - `first_completed`
- Returns list of `Work` objects
- Integrated with `WorkerPool` or `ThreadFactory.submit_all(...)`

#### `WorkGroup`

- Named group of `Work` objects with lifecycle controls  
- Add/remove dynamically  
- Supports teardown logic and shared metadata  

#### `WorkContinuation`

- Attach continuations like:
  ```bash
  factory.submit(task1).then(task2).then(task3)
  ```
- Chain transformations or trigger error handlers  
- Support `.then()`, `.on_success()`, `.on_failure()`

#### `WorkDirectedGraph`

- DAG-based task dependency execution  
- Automatic ordering and cycle detection  
- Supports fan-in / fan-out topology  
- Can be used for workflows, ML pipelines, etc.

#### `WorkBatch`

- Static set of independent tasks  
- Tracks completion and progress state  
- Unified cancellation and error summary  

#### `WorkBarrier`

- Waits for N `Work` units to complete before continuing  
- Useful for intermediate sync points or triggers  

---

### 🧵 Async-Compatible Thread Pools

- `AsyncThreadFactory`  
- Fully `asyncio` compatible  
- ```bash
  await factory.submit(...)
  ```
- Zero-copy integration  

---

### 📊 Diagnostics + Profiling Interface

- Real-time thread state visualizer  
- In-flight task tracking, queue depth, execution metrics  
- Contention index tracking  

---

### 🧩 Orchestrator & Scheduling Modules

- DAG-based orchestration  
- Backoff strategies and work throttling  
- Metrics feedback loop per worker  

---

## 🌐 Long-Term Vision

- **ThreadFactory** as the concurrency backbone of Python’s Free Threading era  
- Distributed execution across multiple systems  
- Cooperative task networks (actor-style, reactive)  
- Optional native backends (C/C++) for ultra-low latency workloads  
