"""Run the full experiment matrix: scenarios x runs x schemes.

For every combination this starts receiver.py, proxy.py and sender.py (in that
order) on localhost, waits for all three to finish, checks the logs, and leaves
the CSVs under <root>/<scenario>/<scheme>/run_NN -- the layout analyze.py and
generate_fake_data.py already use.

Fairness rules (from the README / LOG_SPEC):
  * every scheme in the same (scenario, run) gets the same seed and payload count
  * schemes are interleaved per run, so an interrupted batch still has complete
    plain/fixed/adaptive triples
  * every execution uses a fresh run directory; finished runs are marked with a
    .done file and skipped on re-run, anything half-finished is moved aside to
    <root>_incomplete/ instead of being deleted or appended to

Example:
    python run_experiment.py --runs 10                  # full matrix
    python run_experiment.py --runs 1 --packets 300 --scenarios loss_05
    python run_experiment.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import config

REPO = Path(__file__).resolve().parent

# Scenario name -> proxy arguments. Names matter to analyze.py:
#   "loss_NN"  -> static plots (NN is the loss percentage)
#   "changing" -> the level-versus-loss time plot
# The changing schedule is in seconds of wall-clock time since the proxy started,
# so it needs a run long enough to cover it (see --changing-packets).
SCENARIOS: dict[str, list[str]] = {
    "loss_02": ["--model", "bernoulli", "--loss", "0.02"],
    "loss_05": ["--model", "bernoulli", "--loss", "0.05"],
    "loss_10": ["--model", "bernoulli", "--loss", "0.10"],
    "loss_20": ["--model", "bernoulli", "--loss", "0.20"],
    "bursty": ["--model", "gilbert"],
    "changing": ["--model", "time-varying", "--schedule", "0:0.02,6:0.10,12:0.20,18:0.05"],
}
SCHEMES = ("plain", "fixed", "adaptive")
MANIFEST_FIELDS = [
    "scenario", "scheme", "run", "seed", "packets", "packet_rows",
    "arrived_rows", "wall_seconds", "status",
]


class Proc:
    """A child Python script whose output is drained in the background."""

    def __init__(self, name: str, script_args: list[str], ready_marker: str | None = None):
        self.name = name
        self.lines: list[str] = []
        self.ready = threading.Event()
        self._marker = ready_marker
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.popen = subprocess.Popen(
            [sys.executable, *script_args], cwd=REPO, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        assert self.popen.stdout is not None
        for line in self.popen.stdout:
            line = line.rstrip()
            self.lines.append(line)
            if self._marker and self._marker in line:
                self.ready.set()

    def wait_ready(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ready.wait(0.05):
                return
            if self.popen.poll() is not None:
                break
        raise RuntimeError(f"{self.name} did not become ready:\n" + "\n".join(self.lines))

    def wait(self, timeout: float) -> int | None:
        try:
            return self.popen.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self) -> None:
        if self.popen.poll() is None:
            self.popen.terminate()
            try:
                self.popen.wait(3)
            except subprocess.TimeoutExpired:
                self.popen.kill()
                self.popen.wait()

    def output(self) -> str:
        return "\n".join(self.lines)


def busy_ports() -> list[int]:
    """Ports already bound by something else (e.g. a leftover process).

    The sender binds its feedback port with SO_REUSEADDR, so a stale process
    would not stop it -- it would silently split the feedback and corrupt a run.
    """
    busy = []
    for host, port in (
        (config.PROXY_HOST, config.PROXY_PORT),
        (config.RECEIVER_HOST, config.RECEIVER_PORT),
        (config.FEEDBACK_HOST, config.FEEDBACK_PORT),
    ):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind((host, port))
        except OSError:
            busy.append(port)
        finally:
            probe.close()
    return busy


def build_commands(args, scenario: str, scheme: str, run: int, run_dir: Path, seed: int, packets: int):
    sender = [
        "sender.py", "--scheme", scheme, "--scenario", scenario, "--run", str(run),
        "--packets", str(packets), "--seed", str(seed), "--run-dir", str(run_dir),
    ]
    if scheme == "fixed":
        sender += ["--fixed-level", str(args.fixed_level)]
    return {
        "receiver": ["receiver.py", "--run-dir", str(run_dir)],
        "proxy": ["proxy.py", *SCENARIOS[scenario], "--seed", str(seed)],
        "sender": sender,
    }


def count_rows(run_dir: Path) -> tuple[int, int]:
    with (run_dir / "packets.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return len(rows), sum(1 for row in rows if row["arrive_time"])


def move_aside(run_dir: Path, root: Path) -> Path:
    stash = root.parent / f"{root.name}_incomplete"
    stash.mkdir(parents=True, exist_ok=True)
    label = "__".join(run_dir.relative_to(root).parts)
    target = stash / f"{label}__{datetime.now():%Y%m%d_%H%M%S}"
    shutil.move(str(run_dir), str(target))
    return target


def execute(args, root: Path, scenario: str, scheme: str, run: int) -> dict:
    run_dir = root / scenario / scheme / f"run_{run:02d}"
    packets = args.changing_packets if scenario == "changing" else args.packets
    seed = args.base_seed + run + 1000 * list(SCENARIOS).index(scenario)
    commands = build_commands(args, scenario, scheme, run, run_dir, seed, packets)
    record = {
        "scenario": scenario, "scheme": scheme, "run": run, "seed": seed,
        "packets": packets, "packet_rows": 0, "arrived_rows": 0,
        "wall_seconds": 0.0, "status": "failed",
    }
    started = time.monotonic()
    procs: list[Proc] = []
    problems: list[str] = []
    try:
        receiver = Proc("receiver", commands["receiver"], "receiver listening")
        procs.append(receiver)
        receiver.wait_ready()
        proxy = Proc("proxy", commands["proxy"], "proxy listening")
        procs.append(proxy)
        proxy.wait_ready()
        sender = Proc("sender", commands["sender"])
        procs.append(sender)

        # Worst case is level 3 (r=4) for the whole run; allow generous slack.
        expected = packets / config.K * (config.K + 4) * config.SEND_INTERVAL
        sender_rc = sender.wait(expected * 3 + 60)
        if sender_rc != 0:
            problems.append(f"sender exit code {sender_rc}\n{sender.output()}")
        for child in (receiver, proxy):
            rc = child.wait(60)
            if rc != 0:
                problems.append(f"{child.name} exit code {rc}\n{child.output()}")

        rows, arrived = count_rows(run_dir)
        record["packet_rows"], record["arrived_rows"] = rows, arrived
        if rows != packets:
            problems.append(f"expected {packets} packet rows, found {rows}")
        if arrived == 0:
            problems.append("no packet was ever received")
    except Exception as exc:  # noqa: BLE001 - report and keep the batch going
        problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        for proc in procs:
            proc.stop()
    record["wall_seconds"] = round(time.monotonic() - started, 1)
    if problems:
        for problem in problems:
            # Tracebacks end with the useful line, so keep the tail of long output.
            print("    " + "\n    ".join(problem.splitlines()[-10:]))
        if run_dir.exists():
            print(f"    moved incomplete run to {move_aside(run_dir, root)}")
    else:
        (run_dir / ".done").write_text("ok\n")
        record["status"] = "ok"
    return record


def append_manifest(root: Path, record: dict) -> None:
    path = root / "manifest.csv"
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(record)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="runs", help="output folder (default: runs)")
    parser.add_argument("--runs", type=int, default=10, help="runs per scenario and scheme")
    parser.add_argument("--packets", type=int, default=1000, help="data packets per run")
    parser.add_argument("--changing-packets", type=int, default=4000,
                        help="data packets for the 'changing' scenario (needs ~24 s to cover its schedule)")
    parser.add_argument("--scenarios", nargs="+", choices=list(SCENARIOS), default=list(SCENARIOS))
    parser.add_argument("--schemes", nargs="+", choices=SCHEMES, default=list(SCHEMES))
    parser.add_argument("--fixed-level", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--base-seed", type=int, default=20261015)
    parser.add_argument("--dry-run", action="store_true", help="print the plan and first commands, run nothing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    plan = [
        (scenario, run, scheme)
        for scenario in args.scenarios
        for run in range(1, args.runs + 1)
        for scheme in args.schemes
    ]
    if args.dry_run:
        first = plan[0]
        run_dir = root / first[0] / first[2] / f"run_{first[1]:02d}"
        seed = args.base_seed + first[1] + 1000 * list(SCENARIOS).index(first[0])
        packets = args.changing_packets if first[0] == "changing" else args.packets
        print(f"{len(plan)} runs planned under {root}")
        for name, cmd in build_commands(args, first[0], first[2], first[1], run_dir, seed, packets).items():
            print(f"  {name:8s} python {' '.join(cmd)}")
        return

    stale = busy_ports()
    if stale:
        raise SystemExit(f"UDP port(s) {stale} already in use - stop leftover receiver/proxy/sender processes first")
    root.mkdir(parents=True, exist_ok=True)

    done = failed = skipped = 0
    batch_started = time.monotonic()
    try:
        for index, (scenario, run, scheme) in enumerate(plan, 1):
            run_dir = root / scenario / scheme / f"run_{run:02d}"
            label = f"[{index}/{len(plan)}] {scenario} {scheme} run {run:02d}"
            if (run_dir / ".done").exists():
                skipped += 1
                print(f"{label}: already done, skipping")
                continue
            if run_dir.exists():
                print(f"{label}: found unfinished run, moved to {move_aside(run_dir, root)}")
            print(f"{label}: running...", flush=True)
            record = execute(args, root, scenario, scheme, run)
            append_manifest(root, record)
            if record["status"] == "ok":
                done += 1
                elapsed = time.monotonic() - batch_started
                remaining = (len(plan) - index) * elapsed / max(done + failed, 1)
                print(f"    ok in {record['wall_seconds']} s "
                      f"({record['arrived_rows']}/{record['packets']} data packets arrived); "
                      f"about {remaining / 60:.0f} min left")
            else:
                failed += 1
    except KeyboardInterrupt:
        print("\ninterrupted - re-run the same command to resume (the unfinished run is set aside automatically)")
    print(f"\nfinished: {done} ok, {failed} failed, {skipped} skipped. Logs: {root}")
    print(f"next: python analyze.py --input {args.root} --output analysis_output")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
