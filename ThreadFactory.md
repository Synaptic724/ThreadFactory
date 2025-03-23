# 🛠️ ThreadFactory: `Work` System Blueprint

## Overview
This blueprint outlines the core design for the `Work` system in **ThreadFactory**. It combines the functionality of:
- **Task**
- **Future/Promise**
- **Cancellation Token**
- **Thread-Controlled Work Execution**

Each `Work` object encapsulates a unit of computation and its lifecycle.

---

## 🎯 Core Concepts

### `Work` Object  
A unified representation of a *future task*, with built-in:
- Callable execution
- State management (pending → running → completed/cancelled)
- Cancellation support
- Result/exception storage
- Callback/future-like interface

### ThreadFactory / Worker  
Dynamic pool of threads, pulling and executing `Work` objects.
- Supports work-stealing (optional future enhancement)
- Dynamically scales workers based on load
- Graceful shutdown and cancellation

---

## ✅ Work Lifecycle

| **State**    | **Description**                                     |
|--------------|-----------------------------------------------------|
| `PENDING`    | Work is created but not yet executed                |
| `RUNNING`    | Work is currently executing in a worker thread      |
| `COMPLETED`  | Work finished successfully, result is available     |
| `CANCELLED`  | Work was cancelled before/during execution          |
| `FAILED`     | Work raised an exception during execution           |

---

## ⚙️ Work API (Conceptual)

```python
work = Work(fn, *args, **kwargs)

# Properties
work.state                # Current state
work.is_done()            # True if completed, cancelled, or failed
work.is_cancelled()       # True if cancelled

# Methods (User Side)
work.cancel()             # Request cancellation
result = work.result(timeout=None)    # Blocks until done or timeout
exc = work.exception(timeout=None)    # Blocks until done or timeout

# Methods (Worker Side)
work.run()                # Runs the callable and handles result/exception
