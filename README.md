# AtomicThreading

High-performance **thread-safe** (No-GIL–friendly) data structures and parallel operations for Python 3.13+.

> **NOTE**  
> This library is designed and tested against Python 3.13+ in No-GIL mode. It also works under the standard GIL runtime in Python 3.x, but you won't get the same concurrency benefits.

---

## Features

1. **ConcurrentBag**  
   - A thread-safe “multiset” collection that allows duplicates.  
   - Atomic counter tracks total items; methods like `add`, `remove`, `discard`, etc.

2. **ConcurrentDict**  
   - A thread-safe dictionary that updates an atomic counter for item count.  
   - Supports typical dict operations (`update`, `popitem`, `atomic_update`, etc.).

3. **ConcurrentList**  
   - A thread-safe list with atomic length tracking.  
   - Slice assignment, in-place operators (`+=`, `*=`) are supported, plus advanced methods (`map`, `filter`, `reduce`).

4. **ConcurrentQueue**  
   - A thread-safe FIFO queue built atop `collections.deque` and an atomic counter.  
   - Basic `enqueue`, `dequeue`, plus optional concurrency-friendly methods like `batch_update`, `map`, and `reduce`.

5. **Parallel** (TPL-like)  
   - `parallel_for`, `parallel_foreach`, `parallel_invoke`, `parallel_map`  
   - Flexible chunking, concurrency control, local state usage, early stop on exception, etc.

---

## Installation

1. **Clone** this repository or download the source code.
2. **Create** a Python 3.13+ virtual environment designed for NoGIL/Free Threading
3. **Install requirements**:
   ```bash
   pip install -r requirements.txt
