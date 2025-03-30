# benchmark_strategy.py
from abc import ABC, abstractmethod
from typing import List, Callable, Tuple


class BenchmarkStrategy(ABC):
    """
    Abstract base class for defining how benchmarks should be run
    (single run, multi-sample, grid runs, etc.).
    """

    @abstractmethod
    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        """
        Execute the benchmark runs against the provided manager,
        passing a callback for results.
        """
        pass


class SingleRunStrategy(BenchmarkStrategy):
    """
    Runs the specified benchmark exactly once with the given parameters.
    """

    def __init__(self, producers: int, consumers: int, items_per_producer: int):
        self.producers = producers
        self.consumers = consumers
        self.items_per_producer = items_per_producer

    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        manager.run_benchmark(
            name=benchmark_name,
            producers=self.producers,
            consumers=self.consumers,
            items_per_producer=self.items_per_producer,
            callback=callback
        )


class MultiSampleStrategy(BenchmarkStrategy):
    """
    Runs the specified benchmark multiple times with the same parameters.
    """

    def __init__(self, producers: int, consumers: int, items_per_producer: int, samples: int):
        self.producers = producers
        self.consumers = consumers
        self.items_per_producer = items_per_producer
        self.samples = samples

    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        for i in range(self.samples):
            print(f"\n--- [MultiSample] Running sample {i+1}/{self.samples} ---")
            manager.run_benchmark(
                name=benchmark_name,
                producers=self.producers,
                consumers=self.consumers,
                items_per_producer=self.items_per_producer,
                callback=callback
            )


class GridStrategy(BenchmarkStrategy):
    def __init__(self, producer_values: List[int], consumer_values:List[int], items_per_producer: int):
        self.producer_values = producer_values
        self.consumer_values = consumer_values
        self.items_per_producer = items_per_producer

    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        # Just do the looping yourself
        for p in self.producer_values:
            for c in self.consumer_values:
                manager.run_benchmark(
                    name=benchmark_name,
                    producers=p,
                    consumers=c,
                    items_per_producer=self.items_per_producer,
                    callback=callback
                )


class ScalableTest(BenchmarkStrategy):
    def __init__(self, **kwargs):
        self.min_producer = kwargs.get("min_producer")
        self.max_producer = kwargs.get("max_producer")
        self.producer_step = kwargs.get("producer_step")

        self.min_items_per_producer = kwargs.get("min_items_per_producer")
        self.max_items_per_producer = kwargs.get("max_items_per_producer")
        self.items_per_producer_step = kwargs.get("items_per_producer_step")

        # ratios are now a list of (producer_ratio, consumer_ratio) tuples
        self.ratios: List[Tuple[int, int]] = kwargs.get("ratios", [])

    def run(self, manager, benchmark_name: str, callback: Callable[[dict], None]):
        if not self.ratios:
            raise ValueError("You must supply at least one ratio.")

        for p in range(self.min_producer, self.max_producer + 1, self.producer_step):
            for ratio_p, ratio_c in self.ratios:
                # compute c using the ratio
                if p % ratio_p != 0:
                    continue  # skip if p isn't divisible by ratio_p (clean scaling)

                c = (p // ratio_p) * ratio_c

                if c <= 0:
                    continue  # sanity check

                for items in range(
                    self.min_items_per_producer,
                    self.max_items_per_producer + 1,
                    self.items_per_producer_step
                ):
                    print(f"\n🌀 Ratio run: {p}P / {c}C | Ratio {ratio_p}:{ratio_c} | Items/Producer: {items}")

                    manager.run_benchmark(
                        name=benchmark_name,
                        producers=p,
                        consumers=c,
                        items_per_producer=items,
                        callback=callback
                    )
