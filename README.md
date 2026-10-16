# Adaptive UDP Forward Error Correction

A localhost UDP experiment for comparing plain UDP, fixed forward error
correction, and feedback-driven adaptive forward error correction under
controlled packet loss.

The project includes a sender, loss proxy, receiver, adaptive controller,
dependency-free GF(256) erasure coding, a reproducible fake-data generator,
and an analysis pipeline for the four required metrics and plots.

## Features

- Three schemes using one logging contract: plain UDP, fixed FEC, and adaptive FEC.
- Systematic Reed-Solomon-style erasure recovery over GF(256).
- Seeded Bernoulli, Gilbert-Elliott, and time-varying proxy loss models.
- Low, medium, and high redundancy levels with controller hysteresis.
- Monotonic timestamps shared by all processes on one machine.
- Atomic cross-process updates to three CSV files per run.
- Synthetic data generation for developing the analysis before real runs exist.
- Per-run metrics, mean +/- standard deviation summaries, and four plots.

## Architecture

```text
sender.py + controller.py
          |
          | data and parity packets, UDP 15001
          v
       proxy.py
          |
          | surviving packets, UDP 15002
          v
      receiver.py
          |
          | measured loss feedback, UDP 15003
          +---------------------------------> sender/controller
```

All programs are intended to run on the same machine. See [DIAGRAMS.md](DIAGRAMS.md)
for the numbered system, block, controller-state, and port diagrams.

## Requirements

- Python 3.11 or newer
- Windows, Linux, or macOS for the Python programs
- Matplotlib for analysis plots

Create and activate a virtual environment, then install the dependency:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Linux or macOS, activate with `source .venv/bin/activate`.

## Configuration

| Setting | Default |
|---|---:|
| Data packets per block | `k = 10` |
| Level 1 parity packets | `r = 1` |
| Level 2 parity packets | `r = 2` |
| Level 3 parity packets | `r = 4` |
| Low to medium threshold | 5% measured loss |
| Medium to high threshold | 15% measured loss |
| Downward hysteresis | 2 percentage points |
| Feedback interval | 0.5 seconds |
| Playout deadline | 250 milliseconds |
| Sender to proxy | UDP 15001 |
| Proxy to receiver | UDP 15002 |
| Receiver to controller | UDP 15003 |

Level 0 represents plain UDP and produces no parity packets. Change shared
experiment constants in [config.py](config.py).

## Run an experiment manually

Use three terminals in the repository root and activate the same virtual
environment in each terminal. Start the processes in this order.

### 1 Start the receiver

```powershell
python receiver.py --run-dir runs/loss_05/adaptive/run_01
```

### 2 Start the seeded loss proxy

```powershell
python proxy.py --model bernoulli --loss 0.05 --seed 101
```

Available proxy modes:

```powershell
# Independent 5% packet loss
python proxy.py --model bernoulli --loss 0.05 --seed 101

# Bursty two-state loss
python proxy.py --model gilbert --seed 101

# Loss setting changes with elapsed time
python proxy.py --model time-varying --schedule "0:0.02,5:0.10,10:0.20,15:0.05" --seed 101
```

### 3 Start one sender scheme

```powershell
# Adaptive FEC
python sender.py --scheme adaptive --scenario loss_05 --run 1 --packets 1000 --seed 101 --run-dir runs/loss_05/adaptive/run_01

# Fixed FEC at level 2
python sender.py --scheme fixed --fixed-level 2 --scenario loss_05 --run 1 --packets 1000 --seed 101 --run-dir runs/loss_05/fixed/run_01

# Plain UDP
python sender.py --scheme plain --scenario loss_05 --run 1 --packets 1000 --seed 101 --run-dir runs/loss_05/plain/run_01
```

The receiver and proxy stop after their configured idle timeouts. Use a new
run directory for every execution; the sender refuses to append to an existing
run containing packet rows.

For fair comparisons, reuse the same scenario, run number, payload count, and
proxy seed for all three schemes.

## Run log format

Each run directory contains exactly three CSV files:

- `packets.csv`: one row per data packet, including send, arrival, and recovery times.
- `blocks.csv`: one row per FEC block, including `k`, `r`, parity bytes, and recovery status.
- `controller.csv`: one row per feedback report, including measured loss, selected level, and the proxy loss setting.

The authoritative columns and field meanings are documented in
[LOG_SPEC.md](LOG_SPEC.md). Do not rename columns without updating the analysis.

## Generate fake experiment data

The fake-data generator creates five scenarios, three schemes, and ten runs by
default. Data-packet loss decisions are indexed by packet sequence, so schemes
receive the same synthetic data-loss trace for a given scenario and run.

```powershell
python generate_fake_data.py --output fake_runs --runs 10 --packets 1600 --seed 20261013
```

## Analyze logs

The same analysis command works with fake or real run folders:

```powershell
python analyze.py --input fake_runs --output analysis_output
```

Generated results:

- `per_run_metrics.csv`
- `summary_mean_sd.csv`
- `01_unrecovered_loss.png`
- `02_overhead.png`
- `03_recovery_delay.png`
- `04_level_vs_loss.png`

The analysis computes:

1. Unrecovered loss percentage, including packets delivered after the deadline.
2. Mean and 95th-percentile recovery delay.
3. Useful on-time payload throughput.
4. Redundancy overhead as parity bytes divided by data payload bytes.

## Tests

Run the standard-library unit tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

The tests cover packet serialization, single and multiple erasure recovery,
and unrecoverable blocks.

## Project layout

```text
analyze.py              Metric aggregation and four plots
config.py               Shared experiment constants and ports
controller.py           Adaptive redundancy state controller
fec.py                  GF(256) parity encoding and erasure recovery
generate_fake_data.py   Reproducible synthetic CSV runs
log_store.py            Atomic CSV log storage
packet.py               UDP datagram serialization and validation
proxy.py                Seeded packet-loss proxy
receiver.py             Packet collection, FEC recovery, and feedback
sender.py               Plain, fixed, and adaptive packet sender
tests/                   Protocol and FEC unit tests
DIAGRAMS.md              Numbered architecture diagrams
LOG_SPEC.md              Authoritative CSV contract
```

## Current scope

The manual runtime and analysis pipeline are ready. Automated multi-scheme
orchestration in `run_experiment.py` is intentionally deferred until the final
runtime interface and real-log behavior are agreed by the team.
