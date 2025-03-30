import timeit
from array import array

# Setup
list_data = list(range(1_000_000))
array_data = array('Q', range(1_000_000))
index = 500_000

# Benchmark 1: Single Index Access
list_indexing_time = timeit.timeit(lambda: list_data[index], number=1_000_000)
array_indexing_time = timeit.timeit(lambda: array_data[index], number=1_000_000)

# Benchmark 2: Full Iteration
list_iteration_time = timeit.timeit(lambda: [x for x in list_data], number=10)
array_iteration_time = timeit.timeit(lambda: [x for x in array_data], number=10)

# Report
print("=== Benchmark Results ===")
print(f"List Indexing   : {list_indexing_time:.6f} seconds total | {list_indexing_time / 1_000_000:.10f} avg per op")
print(f"Array Indexing  : {array_indexing_time:.6f} seconds total | {array_indexing_time / 1_000_000:.10f} avg per op")
print(f"List Iteration  : {list_iteration_time:.6f} seconds total | {list_iteration_time / 10:.6f} avg per full pass")
print(f"Array Iteration : {array_iteration_time:.6f} seconds total | {array_iteration_time / 10:.6f} avg per full pass")
