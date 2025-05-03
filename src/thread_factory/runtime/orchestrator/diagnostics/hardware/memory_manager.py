import tracemalloc

def snapshot_memory():
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('filename')

    for stat in top_stats[:10]:
        print(stat)