# 🗺️ ThreadFactory Roadmap

## ✅ v1.2 Release (Current)
- New concurrent core:
  - `ConcurrentCollection`: High-throughput unordered container
  - `ConcurrentBuffer` shard-optimized with windowed enqueues
- `Work` object introduced:
  - Awaitable wrapper over `Future` with lifecycle hooks
  - Auto-disposal, metadata, and thread-safe operation
- `QueueAllocator` added:
  - Efficient ticket-based ID pool manager
  - Recyclable, disposable, context-safe
- Initial `Worker` scaffolding created
- Performance benchmarking suite:
  - CSV / JSON / YAML export
  - Integrated plotting system
  - Validated: up to 6× faster than `multiprocessing.Queue`, up to 2.6× faster than `deque+Lock`
- Disposable pattern implemented across all core classes

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

## 🧠 Experimental and Exploratory

### 🧵 Async-Compatible Thread Pools
- `AsyncThreadFactory`: `await factory.submit(...)`
- Zero-copy integration with `asyncio` and thread-based backends

### 📊 Diagnostics + Profiling Interface
- Real-time thread state visualizer
- In-flight task tracking, queue depth, execution metrics
- Contention index tracking

### 🧩 Orchestrator & Scheduling Modules
- DAG-based flow orchestration
- Backoff strategies, work throttling
- Per-thread metrics and feedback loop tuning

---

## 🌐 Long-Term Vision
- **ThreadFactory** as Python’s concurrency **backbone** for the Free Threading era
- Distributed thread execution (across machines)
- Cooperative task networks (actor models, reactive processing)
- Ultra-low latency execution via optional native backends (C/C++)

