# ThreadFactory

[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory)](https://pepy.tech/projects/threadfactory)
[![PyPI version](https://badge.fury.io/py/threadfactory.svg)](https://badge.fury.io/py/threadfactory)
[![License](https://img.shields.io/github/license/Synaptic724/threadfactory)](https://github.com/yourusername/threadfactory/blob/main/LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/threadfactory)](https://pypi.org/project/threadfactory)

High-performance **thread-safe** (No-GIL–friendly) data structures and parallel operations for Python 3.13+.

> **NOTE**  
> ThreadFactory is designed and tested against Python 3.13+ in **No-GIL** mode.  
> This library will only function on 3.13 and higher.
---

## 🚀 Features

### 1. ConcurrentBag  
- A thread-safe “multiset” collection that allows duplicates.  
- Methods like `add`, `remove`, `discard`, etc.  
- Ideal for collections where duplicate elements matter.

### 2. ConcurrentDict  
- A thread-safe dictionary.  
- Supports typical dict operations (`update`, `popitem`, etc.).  
- Provides `batch_update`, `map`, `filter`, and `reduce` for safe, bulk operations.

### 3. ConcurrentList  
- A thread-safe list supporting concurrent access and modification.  
- Slice assignment, in-place operators (`+=`, `*=`), and advanced operations (`map`, `filter`, `reduce`).

### 4. ConcurrentQueue  
- A thread-safe FIFO queue built atop `collections.deque`.  
- Supports `enqueue`, `dequeue`, `peek`, `batch_update`, `map`, `filter`, and `reduce`.  
- Raises `Empty` when `dequeue` or `peek` is called on an empty queue.

### 5. ConcurrentStack  
- A thread-safe LIFO stack.  
- Supports `push`, `pop`, `peek`, and common batch operations.  
- Ideal for last-in, first-out (LIFO) workloads.  
- Built on `deque` for fast appends and pops.

### 6. Parallel Utilities (TPL-like)  
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

# Install the library in editable mode
pip install threadfactory
```
