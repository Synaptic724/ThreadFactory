from collections import Counter
import time
import random


def select_shard(num_shards: int) -> int:
    ns = time.monotonic_ns()
    mixed = ((ns >> 3) ^ ns) % num_shards  # ✅ modulo instead of bitmask
    return mixed


def test_select_shard_distribution(num_shards: int = 10, iterations: int = 1_000_000):
    counts = Counter()

    for _ in range(iterations):
        idx = select_shard(num_shards)
        counts[idx] += 1

    total = sum(counts.values())
    print(f"--- select_shard() Distribution over {num_shards} shards ---")
    for k in range(num_shards):
        pct = (counts[k] / total) * 100
        print(f"  Shard {k}: {counts[k]} hits ({pct:.2f}%)")


def test_select_vs_random(num_shards: int = 16, iterations: int = 10_000_000):
    print(f"\nRunning {iterations:,} iterations with {num_shards} shards...\n")

    # Time select_shard()
    start = time.perf_counter()
    for _ in range(iterations):
        _ = select_shard(num_shards)
    duration_select = time.perf_counter() - start

    # Time random.randint()
    start = time.perf_counter()
    for _ in range(iterations):
        _ = random.randint(0, num_shards - 1)
    duration_randint = time.perf_counter() - start

    # Time random.randrange()
    start = time.perf_counter()
    for _ in range(iterations):
        _ = random.randrange(num_shards)
    duration_randrange = time.perf_counter() - start   # ✅ fixed here

    # Results
    print(f"select_shard():      {duration_select:.4f} sec")
    print(f"random.randint():    {duration_randint:.4f} sec")
    print(f"random.randrange():  {duration_randrange:.4f} sec")

    print("\n⚖️  Relative Performance:")
    print(f"- select_shard is ~{duration_randint / duration_select:.2f}x faster than random.randint")
    print(f"- select_shard is ~{duration_randrange / duration_select:.2f}x faster than random.randrange")




# ✅ Run it with any shard count (even 10, 13, etc.)
test_select_shard_distribution(num_shards=10)
test_select_vs_random(10, iterations=1_000_000)
