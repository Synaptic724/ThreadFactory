# ThreadFactory

[![PyPI version](https://badge.fury.io/py/threadfactory.svg?v=1)](https://badge.fury.io/py/threadfactory)
[![License](https://img.shields.io/github/license/Synaptic724/threadfactory?v=1)](https://github.com/yourusername/threadfactory/blob/main/LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/threadfactory?v=1)](https://pypi.org/project/threadfactory)

[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory/month?v=1)](https://pepy.tech/projects/threadfactory)
[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory/week?v=1)](https://pepy.tech/projects/threadfactory)
[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory?v=1)](https://pepy.tech/projects/threadfactory)

[![Upload Python Package](https://github.com/Synaptic724/ThreadFactory/actions/workflows/python-publish.yml/badge.svg)](https://github.com/Synaptic724/ThreadFactory/actions/workflows/python-publish.yml)


<!--[![Coverage Status](https://coveralls.io/repos/github/Synaptic724/threadfactory/badge.svg?branch=main)](https://coveralls.io/github/Synaptic724/threadfactory?branch=main) -->
<!--[![Documentation Status](https://readthedocs.org/projects/threadfactory/badge/?version=latest)](https://threadfactory.readthedocs.io/en/latest/?badge=latest) -->
<!--[![CodeFactor](https://www.codefactor.io/repository/github/synaptic724/threadfactory/badge)](https://www.codefactor.io/repository/github/synaptic724/threadfactory) -->

High-performance **thread-safe** (No-GIL–friendly) data structures and parallel operations for Python 3.13+.

> **NOTE**  
> ThreadFactory is designed and tested against Python 3.13+ in **No-GIL** mode.  
> This library will only function on 3.13 and higher.
---
> All benchmark tests below are available if you clone the library and run the tests.
> See the [Benchmark Details 🚀](general_benchmarks.md) for more benchmark stats.

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

## 🚀 Features

## Concurrent Data Structures
### 1. ConcurrentBag  
- A thread-safe “multiset” collection that allows duplicates.  
- Methods like `add`, `remove`, `discard`, etc.  
- Ideal for collections where duplicate elements matter.

### 2. ConcurrentDict  
- A thread-safe dictionary.  
- Supports typical dict operations (`update`, `popitem`, etc.).  
- Provides `map`, `filter`, and `reduce` for safe, bulk operations.

### 3. ConcurrentList  
- A thread-safe list supporting concurrent access and modification.  
- Slice assignment, in-place operators (`+=`, `*=`), and advanced operations (`map`, `filter`, `reduce`).

### 4. ConcurrentQueue  
- A thread-safe FIFO queue built atop `collections.deque`.  
- Tested and outperforms deque alone by up to 64% in our benchmark.
- Supports `enqueue`, `dequeue`, `peek`, `map`, `filter`, and `reduce`.  
- Raises `Empty` when `dequeue` or `peek` is called on an empty queue.
- Outperforms multiprocessing queues by over 400% in some cases clone and run unit tests to see.

### 5. ConcurrentStack  
- A thread-safe LIFO stack.  
- Supports `push`, `pop`, `peek` operations.  
- Ideal for last-in, first-out (LIFO) workloads.  
- Built on `deque` for fast appends and pops.
- Similar performance to ConcurrentQueue

### 6. ConcurrentBuffer  
- A **high-performance**, thread-safe buffer using **sharded deques** for low-contention access.  
- Designed to handle massive producer/consumer loads with better throughput than standard queues.  
- Supports `enqueue`, `dequeue`, `peek`, `clear`, and bulk operations (`map`, `filter`, `reduce`).  
- **Timestamp-based ordering** ensures approximate FIFO behavior across shards.  
- Outperforms `ConcurrentQueue` by up to **60%** in mid-range concurrency in even thread Producer/Consumer configuration with 10 shards.
- Automatically balances items across shards; ideal for parallel pipelines and low-latency workloads.  
- Best used with `shard_count ≈ thread_count / 2` for optimal performance, but keep shards at or below 10.
---

## Parallel Operations
### 1. Parallel Utilities (TPL-like)  
- `parallel_for`, `parallel_foreach`, `parallel_invoke`, `parallel_map`.  
- Pure thread-based concurrency (No-GIL optimized), not tied to asyncio or multiprocessing.  
- Flexible chunking, concurrency control, local state usage, early exit on exception, and more.  
- Inspired by .NET's Task Parallel Library (TPL).

---

## ⚙️ Installation

### Option 1: Clone and Install Locally (Recommended for Development)

```bash
# Clone the repository
git clone https://github.com/yourusername/threadfactory.git
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