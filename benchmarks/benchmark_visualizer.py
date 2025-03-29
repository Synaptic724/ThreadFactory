import time
import csv
import json
import matplotlib.pyplot as plt
from typing import Dict, Any, Callable, List, Optional
import numpy as np

class BenchmarkVisualizer:
    """
    A flexible visualizer that can:
      - plot bar charts, line charts, scatter plots
      - group or filter data
      - save results to CSV/JSON
    """

    def __init__(self, records: List[Dict[str, Any]]):
        self.records = records

    def show_bar_chart(
        self,
        metric: str = "throughput",
        title: str = "Benchmark Results",
        save_path: Optional[str] = None
    ):
        """
        Renders a bar chart of the given metric (e.g., throughput, duration).
        Sorted descending by metric value.
        """
        sorted_records = sorted(self.records, key=lambda r: r.get(metric, 0), reverse=True)
        names = [r["name"] for r in sorted_records]
        values = [r.get(metric, 0) for r in sorted_records]

        plt.figure()
        plt.bar(names, values)
        plt.title(title)
        plt.ylabel(metric)
        plt.xlabel("Benchmark")
        plt.xticks(rotation=15)
        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, bbox_inches='tight')
            print(f"✅ Chart saved to {save_path}")

        plt.show()

    def show_multiple_metrics(
        self,
        metrics: List[str],
        title_prefix: str = "Benchmark Results – "
    ):
        """
        Shows a separate bar chart for each metric in the list.
        """
        for metric in metrics:
            chart_title = f"{title_prefix}{metric}"
            self.show_bar_chart(metric=metric, title=chart_title)

    def filter_by_name(self, name_substring: str) -> List[Dict[str, Any]]:
        """
        Returns a filtered list of records where 'name' contains the substring.
        """
        return [r for r in self.records if name_substring in r["name"]]

    def group_by_extra_key(self, key: str):
        """
        Group the records by a specified key in the 'extra' dictionary,
        then print average throughput/duration for each group.
        """
        groups = {}
        for r in self.records:
            val = r.get("extra", {}).get(key, None)
            groups.setdefault(val, []).append(r)

        print(f"\n📦 Grouped by '{key}':")
        for val, group in groups.items():
            if not group:
                continue
            avg_throughput = sum(r["throughput"] for r in group) / len(group)
            avg_duration = sum(r["duration"] for r in group) / len(group)
            print(f"  - Value: {val} | Avg Throughput: {avg_throughput:.2f} | Avg Duration: {avg_duration:.2f}s")

    def show_grouped_bar_chart(
            self,
            title: str = "Throughput and Duration by Benchmark",
            save_path: Optional[str] = None
    ):
        """
        Shows a grouped bar chart comparing both throughput and duration for each benchmark type.
        """
        import numpy as np
        import matplotlib.pyplot as plt

        # Aggregate by benchmark name
        grouped = {}
        for r in self.records:
            name = r["name"]
            grouped.setdefault(name, {"throughput": [], "duration": []})
            grouped[name]["throughput"].append(r["throughput"])
            grouped[name]["duration"].append(r["duration"])

        names = list(grouped.keys())
        avg_throughput = [sum(vals["throughput"]) / len(vals["throughput"]) for vals in grouped.values()]
        avg_duration = [sum(vals["duration"]) / len(vals["duration"]) for vals in grouped.values()]

        x = np.arange(len(names))  # X locations
        width = 0.35  # Width of the bars

        fig, ax1 = plt.subplots()

        # Bar for throughput
        bars1 = ax1.bar(x - width / 2, avg_throughput, width, label='Throughput (ops/sec)')

        # Bar for duration (scaled to seconds)
        bars2 = ax1.bar(x + width / 2, avg_duration, width, label='Duration (s)')

        ax1.set_ylabel("Value")
        ax1.set_title(title)
        ax1.set_xticks(x)
        ax1.set_xticklabels(names, rotation=15)
        ax1.legend()
        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, bbox_inches="tight")
            print(f"✅ Saved grouped bar chart to {save_path}")

        plt.show()

    def show_dual_axis_chart(
            self,
            title: str = "Throughput vs Duration by Queue Type",
            save_path: Optional[str] = None
    ):
        grouped = {}
        for r in self.records:
            name = r["name"]
            grouped.setdefault(name, {"throughput": [], "duration": []})
            grouped[name]["throughput"].append(r["throughput"])
            grouped[name]["duration"].append(r["duration"])

        names = list(grouped.keys())
        avg_throughput = [sum(vals["throughput"]) / len(vals["throughput"]) for vals in grouped.values()]
        avg_duration = [sum(vals["duration"]) / len(vals["duration"]) for vals in grouped.values()]

        x = np.arange(len(names))
        width = 0.4

        # ✅ Increase figure size
        fig, ax1 = plt.subplots(figsize=(10, 6))

        # Left axis: Throughput
        color1 = 'tab:blue'
        ax1.bar(x - width / 2, avg_throughput, width, label='Throughput (ops/sec)', color=color1)
        ax1.set_ylabel("Throughput (ops/sec)", color=color1)
        ax1.tick_params(axis='y', labelcolor=color1)

        # Right axis: Duration
        ax2 = ax1.twinx()
        color2 = 'tab:orange'
        ax2.bar(x + width / 2, avg_duration, width, label='Duration (s)', color=color2)
        ax2.set_ylabel("Duration (seconds)", color=color2)
        ax2.tick_params(axis='y', labelcolor=color2)

        # ✅ Better x-axis label handling
        plt.title(title)
        plt.xticks(ticks=x)
        ax1.set_xticklabels(names, rotation=25, ha="right")

        fig.tight_layout()

        if save_path:
            plt.savefig(save_path, bbox_inches='tight')
            print(f"✅ Saved dual-axis chart to {save_path}")

        plt.show()

    def show_line_chart(
        self,
        x_field: str,
        y_field: str,
        title: str = "Line Chart",
        save_path: Optional[str] = None
    ):
        """
        Renders a line chart with 'x_field' on x-axis and 'y_field' on y-axis.
        Sorts by x_field so the line is meaningful.
        """
        sorted_records = sorted(self.records, key=lambda r: r.get(x_field, 0))
        x_vals = [r.get(x_field, 0) for r in sorted_records]
        y_vals = [r.get(y_field, 0) for r in sorted_records]

        plt.figure()
        plt.plot(x_vals, y_vals, marker='o')
        plt.title(title)
        plt.xlabel(x_field)
        plt.ylabel(y_field)
        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, bbox_inches='tight')
            print(f"✅ Line chart saved to {save_path}")

        plt.show()

    def show_scatter_plot(
        self,
        x_field: str,
        y_field: str,
        title: str = "Scatter Plot",
        save_path: Optional[str] = None
    ):
        """
        Renders a scatter plot to see correlation between x_field and y_field.
        """
        x_vals = [r.get(x_field, 0) for r in self.records]
        y_vals = [r.get(y_field, 0) for r in self.records]

        plt.figure()
        plt.scatter(x_vals, y_vals)
        plt.title(title)
        plt.xlabel(x_field)
        plt.ylabel(y_field)
        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, bbox_inches='tight')
            print(f"✅ Scatter plot saved to {save_path}")

        plt.show()

    def save_as_csv(self, filepath: str):
        """
        Save current records to CSV.
        """
        if not self.records:
            print("No records to save.")
            return

        keys = list(self.records[0].keys())
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.records)
        print(f"✅ Visualizer records saved to CSV: {filepath}")

    def save_as_json(self, filepath: str):
        """
        Save current records to JSON.
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.records, f, indent=2)
        print(f"✅ Visualizer records saved to JSON: {filepath}")
