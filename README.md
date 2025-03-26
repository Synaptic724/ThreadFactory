# ThreadFactory

[![PyPI version](https://badge.fury.io/py/threadfactory.svg)](https://badge.fury.io/py/threadfactory)
[![License](https://img.shields.io/github/license/Synaptic724/threadfactory)](https://github.com/yourusername/threadfactory/blob/main/LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/threadfactory)](https://pypi.org/project/threadfactory)

[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory/month)](https://pepy.tech/projects/threadfactory)
[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory/week)](https://pepy.tech/projects/threadfactory)
[![PyPI Downloads](https://static.pepy.tech/badge/threadfactory)](https://pepy.tech/projects/threadfactory)

<!--[![Build Status](https://travis-ci.com/Synaptic724/threadfactory.svg?branch=main)](https://travis-ci.com/Synaptic724/threadfactory) -->
<!--[![Coverage Status](https://coveralls.io/repos/github/Synaptic724/threadfactory/badge.svg?branch=main)](https://coveralls.io/github/Synaptic724/threadfactory?branch=main) -->
<!--[![Documentation Status](https://readthedocs.org/projects/threadfactory/badge/?version=latest)](https://threadfactory.readthedocs.io/en/latest/?badge=latest) -->
<!--[![CodeFactor](https://www.codefactor.io/repository/github/synaptic724/threadfactory/badge)](https://www.codefactor.io/repository/github/synaptic724/threadfactory) -->

High-performance **thread-safe** (No-GIL–friendly) data structures and parallel operations for Python 3.13+.

> **NOTE**  
> ThreadFactory is designed and tested against Python 3.13+ in **No-GIL** mode.  
> This library will only function on 3.13 and higher.
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
- Supports `enqueue`, `dequeue`, `peek`, `map`, `filter`, and `reduce`.  
- Raises `Empty` when `dequeue` or `peek` is called on an empty queue.
- Outperforms multiprocessing queues by over 300% in some cases clone and run unit tests to see.

### 5. ConcurrentStack  
- A thread-safe LIFO stack.  
- Supports `push`, `pop`, `peek` operations.  
- Ideal for last-in, first-out (LIFO) workloads.  
- Built on `deque` for fast appends and pops.


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