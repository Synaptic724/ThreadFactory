# 📜 Changelog
All notable changes to this project will be documented in this file.  
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]
### Added
- Thread role assignment framework (Producer, Consumer, Orchestrator)
- ThreadSwitch logic for dynamic execution context migration
- Queue state management using Active and Empty stacks
- Contention mode system (0-10 scale) with dynamic tuning
- Work stealing optimization with concurrent list handling

---

## [1.1.0] - 2025-03-26
### Classes Added
### 1. Dynaphore
- A dynamic semaphore class that allows for dynamic tuning of semaphore limits.
- Supports increase and decrease of semaphore limits at runtime.

### 2. ConcurrentBuffer
- This class is a thread-safe buffer that allows for concurrent read and write operations.
- It is not FIFO or LIFO, but rather a simple buffer that can be used for any purpose.
- It operates well under low to moderate contention and outperforms other collections in this scenario.
- For high contention, consider using a dedicated collection like ConcurrentQueue or ConcurrentStack.

### Added Features
- Added Update method to ConcurrentBag and ConcurrentList for bulk updates using iterables
- Added Remove method for ConcurrentQueue and ConcurrentStack
- Added performance testing in unittests for ConcurrentQueue for user testing if desired via clone

### Fixes
- Imports changed from relative to absolute
- Added small sleep timer to ConcurrentStack and ConcurrentQueue to provide backpressure time.sleep(0.001)
---

## [1.0.1] - 2025-03-22
### Added
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
- Supports `enqueue`, `dequeue`, `peek`, `map`, `filter`, and `reduce`.  
- Raises `Empty` when `dequeue` or `peek` is called on an empty queue.

### 5. ConcurrentStack  
- A thread-safe LIFO stack.  
- Supports `push`, `pop`, `peek` operations.  
- Ideal for last-in, first-out (LIFO) workloads.  
- Built on `deque` for fast appends and pops.

### 6. Parallel Utilities (TPL-like)  
- `parallel_for`, `parallel_foreach`, `parallel_invoke`, `parallel_map`.  
- Pure thread-based concurrency (No-GIL optimized), not tied to asyncio or multiprocessing.  
- Flexible chunking, concurrency control, local state usage, early exit on exception, and more.  
- Inspired by .NET's Task Parallel Library (TPL).