"""Generate deterministic fake runs using the exact production CSV schema."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import config
from log_store import BLOCK_FIELDS, CONTROLLER_FIELDS, PACKET_FIELDS, CsvRunStore

SCENARIOS = {
    "loss_02": [(0.0, 0.02)],
    "loss_05": [(0.0, 0.05)],
    "loss_10": [(0.0, 0.10)],
    "loss_20": [(0.0, 0.20)],
    "changing": [(0.0, 0.02), (2.0, 0.10), (4.0, 0.20), (6.0, 0.05)],
}
SCHEMES = ("plain", "fixed", "adaptive")


def true_loss(schedule: list[tuple[float, float]], elapsed: float) -> float:
    value = schedule[0][1]
    for start, candidate in schedule:
        if elapsed < start:
            break
        value = candidate
    return value


def adaptive_level(loss: float) -> int:
    if loss < config.LOW_TO_MEDIUM:
        return 1
    if loss < config.MEDIUM_TO_HIGH:
        return 2
    return 3


def make_run(root: Path, scheme: str, scenario: str, run: int, packets: int, seed: int) -> None:
    run_dir = root / scenario / scheme / f"run_{run:02d}"
    store = CsvRunStore(run_dir)
    store.initialise()
    if store.has_packet_rows():
        raise FileExistsError(f"refusing to append to existing run: {run_dir}")
    schedule = SCENARIOS[scenario]
    # Reinitialising with the same seed gives every scheme the same random trace.
    base = 10_000.0 + run * 100.0
    packet_rows: list[dict] = []
    block_rows: list[dict] = []
    controller_rows: list[dict] = []
    for first_seq in range(0, packets, config.K):
        block_id = first_seq // config.K
        k = min(config.K, packets - first_seq)
        elapsed = first_seq * config.SEND_INTERVAL
        loss = true_loss(schedule, elapsed)
        level = 0 if scheme == "plain" else (2 if scheme == "fixed" else adaptive_level(loss))
        r = config.LEVEL_TO_R[level]
        # Packet-indexed streams preserve the same data-loss trace even though
        # schemes emit different numbers of parity packets.
        data_lost = [random.Random((seed << 20) ^ (first_seq + i)).random() < loss for i in range(k)]
        parity_lost = [random.Random((seed << 20) ^ 0xABC000 ^ (block_id << 4) ^ i).random() < loss for i in range(r)]
        available_parity = r - sum(parity_lost)
        can_recover = sum(data_lost) <= available_parity
        block_send = base + elapsed
        for index in range(k):
            send_time = block_send + index * config.SEND_INTERVAL
            jitter_rng = random.Random((seed << 20) ^ 0x555000 ^ (first_seq + index))
            arrive_time = "" if data_lost[index] else f"{send_time + 0.008 + jitter_rng.random() * 0.010:.9f}"
            recover_time = ""
            if data_lost[index] and can_recover:
                recovery = block_send + (k + r) * config.SEND_INTERVAL + 0.012 + jitter_rng.random() * 0.008
                recover_time = f"{recovery:.9f}"
            packet_rows.append({
                "scheme": scheme, "scenario": scenario, "run": run,
                "seq": first_seq + index, "block_id": block_id, "level": level,
                "payload_bytes": config.PAYLOAD_BYTES, "send_time": f"{send_time:.9f}",
                "arrive_time": arrive_time, "recover_time": recover_time,
            })
        block_rows.append({
            "block_id": block_id, "level": level, "k": k, "r": r,
            "parity_bytes": r * config.PAYLOAD_BYTES, "send_time": f"{block_send:.9f}",
            "received_count": k + r - sum(data_lost) - sum(parity_lost),
            "recovered": int(can_recover),
        })
        if block_id % max(1, round(config.FEEDBACK_INTERVAL / (config.K * config.SEND_INTERVAL))) == 0:
            report_rng = random.Random((seed << 20) ^ 0xFEE000 ^ block_id)
            measured = max(0.0, min(1.0, loss + report_rng.gauss(0, 0.012)))
            controller_rows.append({
                "time": f"{block_send:.9f}", "measured_loss": f"{measured:.6f}",
                "level": level, "true_loss": f"{loss:.6f}",
            })
    store.append_rows("packets.csv", PACKET_FIELDS, packet_rows)
    store.append_rows("blocks.csv", BLOCK_FIELDS, block_rows)
    store.append_rows("controller.csv", CONTROLLER_FIELDS, controller_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="fake_runs")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--packets", type=int, default=1600)
    parser.add_argument("--seed", type=int, default=20261013)
    args = parser.parse_args()
    root = Path(args.output)
    for scenario in SCENARIOS:
        for run in range(1, args.runs + 1):
            shared_seed = args.seed + run + 10_000 * list(SCENARIOS).index(scenario)
            for scheme in SCHEMES:
                make_run(root, scheme, scenario, run, args.packets, shared_seed)
    print(f"generated {len(SCENARIOS) * len(SCHEMES) * args.runs} runs under {root.resolve()}")


if __name__ == "__main__":
    main()
