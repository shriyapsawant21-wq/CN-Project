"""Compute the four metrics, summary table, and four required plots."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

import config


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def percentile(values: list[float], probability: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def metrics(run_dir: Path, deadline: float) -> dict[str, float | str | int]:
    packets = read_csv(run_dir / "packets.csv")
    blocks = read_csv(run_dir / "blocks.csv")
    if not packets:
        raise ValueError(f"no packet rows in {run_dir}")
    delivered_bytes = 0
    unrecovered = 0
    recovery_delays: list[float] = []
    for row in packets:
        sent = float(row["send_time"])
        arrival = float(row["arrive_time"]) if row["arrive_time"] else None
        recovery = float(row["recover_time"]) if row["recover_time"] else None
        delivery = arrival if arrival is not None else recovery
        if delivery is None or delivery - sent > deadline:
            unrecovered += 1
        else:
            delivered_bytes += int(row["payload_bytes"])
        if recovery is not None:
            recovery_delays.append(recovery - sent)
    send_times = [float(row["send_time"]) for row in packets]
    duration = max(send_times) - min(send_times)
    if duration <= 0:
        duration = 1e-9
    payload_total = sum(int(row["payload_bytes"]) for row in packets)
    parity_total = sum(int(row["parity_bytes"]) for row in blocks)
    first = packets[0]
    return {
        "scheme": first["scheme"], "scenario": first["scenario"], "run": int(first["run"]),
        "unrecovered_loss_pct": 100.0 * unrecovered / len(packets),
        "recovery_delay_mean_ms": 1000.0 * statistics.mean(recovery_delays) if recovery_delays else math.nan,
        "recovery_delay_p95_ms": 1000.0 * percentile(recovery_delays, 0.95),
        "useful_throughput_mbps": delivered_bytes * 8.0 / duration / 1_000_000,
        "redundancy_overhead_pct": 100.0 * parity_total / payload_total,
    }


def mean_sd(values: list[float]) -> tuple[float, float]:
    clean = [value for value in values if not math.isnan(value)]
    if not clean:
        return math.nan, math.nan
    return statistics.mean(clean), statistics.stdev(clean) if len(clean) > 1 else 0.0


def fmt(value: float) -> str:
    return "NA" if math.isnan(value) else f"{value:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="fake_runs")
    parser.add_argument("--output", default="analysis_output")
    parser.add_argument("--deadline", type=float, default=config.PLAYOUT_DEADLINE)
    args = parser.parse_args()
    root, output = Path(args.input), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    run_dirs = sorted(path.parent for path in root.rglob("packets.csv"))
    results = [metrics(path, args.deadline) for path in run_dirs]
    if not results:
        raise SystemExit(f"no packets.csv files found below {root}")
    metric_names = [
        "unrecovered_loss_pct", "recovery_delay_mean_ms", "recovery_delay_p95_ms",
        "useful_throughput_mbps", "redundancy_overhead_pct",
    ]
    with (output / "per_run_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader(); writer.writerows(results)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for result in results:
        grouped[(str(result["scheme"]), str(result["scenario"]))].append(result)
    summary_rows = []
    for (scheme, scenario), rows in sorted(grouped.items()):
        summary = {"scheme": scheme, "scenario": scenario}
        for metric in metric_names:
            mean, sd = mean_sd([float(row[metric]) for row in rows])
            summary[f"{metric}_mean"] = mean
            summary[f"{metric}_sd"] = sd
            summary[f"{metric}_mean_sd"] = f"{fmt(mean)} ± {fmt(sd)}"
        summary_rows.append(summary)
    fields = ["scheme", "scenario"] + [f"{metric}_mean_sd" for metric in metric_names]
    with (output / "summary_mean_sd.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(summary_rows)

    schemes = [scheme for scheme in ("plain", "fixed", "adaptive") if any(r["scheme"] == scheme for r in results)]
    static = [name for name in sorted({str(r["scenario"]) for r in results}) if name.startswith("loss_")]
    loss_rates = [float(name.split("_", 1)[1]) / 100 for name in static]

    plt.figure(figsize=(7, 4.5))
    for scheme in schemes:
        values = [mean_sd([float(r["unrecovered_loss_pct"]) for r in grouped[(scheme, scenario)]])[0] for scenario in static]
        plt.plot([100 * value for value in loss_rates], values, marker="o", label=scheme)
    plt.xlabel("Configured loss rate (%)"); plt.ylabel("Unrecovered loss (%)")
    plt.grid(alpha=.3); plt.legend(); plt.tight_layout(); plt.savefig(output / "01_unrecovered_loss.png", dpi=180); plt.close()

    plt.figure(figsize=(7, 4.5))
    width = .25
    x = range(len(static))
    for offset, scheme in enumerate(schemes):
        values = [mean_sd([float(r["redundancy_overhead_pct"]) for r in grouped[(scheme, scenario)]])[0] for scenario in static]
        plt.bar([i + (offset - 1) * width for i in x], values, width, label=scheme)
    plt.xticks(list(x), static); plt.ylabel("Redundancy overhead (%)")
    plt.legend(); plt.tight_layout(); plt.savefig(output / "02_overhead.png", dpi=180); plt.close()

    plt.figure(figsize=(7, 4.5))
    for scheme in schemes:
        values = [mean_sd([float(r["recovery_delay_mean_ms"]) for r in grouped[(scheme, scenario)]])[0] for scenario in static]
        plt.plot([100 * value for value in loss_rates], values, marker="o", label=scheme)
    plt.xlabel("Configured loss rate (%)"); plt.ylabel("Mean recovery delay (ms)")
    plt.grid(alpha=.3); plt.legend(); plt.tight_layout(); plt.savefig(output / "03_recovery_delay.png", dpi=180); plt.close()

    controller_candidates = sorted(root.glob("changing/adaptive/run_*/controller.csv"))
    if controller_candidates:
        rows = read_csv(controller_candidates[0])
        times = [float(row["time"]) for row in rows]
        origin = times[0]
        fig, axis = plt.subplots(figsize=(8, 4.5))
        axis.step([value - origin for value in times], [int(row["level"]) for row in rows], where="post", label="FEC level")
        axis.set_xlabel("Time (s)"); axis.set_ylabel("Redundancy level"); axis.set_yticks([0, 1, 2, 3])
        loss_axis = axis.twinx()
        loss_axis.step([value - origin for value in times], [100 * float(row["true_loss"]) for row in rows], where="post", color="tab:red", label="True loss")
        loss_axis.set_ylabel("Proxy loss setting (%)", color="tab:red")
        fig.tight_layout(); fig.savefig(output / "04_level_vs_loss.png", dpi=180); plt.close(fig)
    print(f"analysed {len(results)} runs; outputs: {output.resolve()}")


if __name__ == "__main__":
    main()
