"""UDP sender for plain, fixed-FEC, and adaptive-FEC experiments."""

from __future__ import annotations

import argparse
import json
import random
import socket
import threading
import time
from pathlib import Path

import config
import fec
from controller import AdaptiveController
from log_store import BLOCK_FIELDS, CONTROLLER_FIELDS, PACKET_FIELDS, CsvRunStore
from packet import encode_packet


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--scheme", choices=("plain", "fixed", "adaptive"), required=True)
    parser.add_argument("--scenario", default="bernoulli_05")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--packets", type=int, default=1000)
    parser.add_argument("--fixed-level", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--payload-bytes", type=int, default=config.PAYLOAD_BYTES)
    parser.add_argument("--interval", type=float, default=config.SEND_INTERVAL)
    return parser.parse_args()


class FeedbackListener(threading.Thread):
    def __init__(self, store: CsvRunStore, scheme: str, fixed_level: int):
        super().__init__(daemon=True)
        self.store = store
        self.scheme = scheme
        self.fixed_level = fixed_level
        self.controller = AdaptiveController(store)
        self.stop_event = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((config.FEEDBACK_HOST, config.FEEDBACK_PORT))
        self.sock.settimeout(config.SOCKET_TIMEOUT)

    @property
    def level(self) -> int:
        if self.scheme == "plain":
            return 0
        if self.scheme == "fixed":
            return self.fixed_level
        return self.controller.level

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                message, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            try:
                report = json.loads(message.decode("utf-8"))
                timestamp = time.monotonic()
                measured = float(report["measured_loss"])
                true_loss = float(report.get("true_loss", 0.0))
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
            if self.scheme == "adaptive":
                self.controller.observe(timestamp, measured, true_loss)
            else:
                self.store.append_rows(
                    "controller.csv", CONTROLLER_FIELDS,
                    [{"time": f"{timestamp:.9f}", "measured_loss": f"{measured:.6f}",
                      "level": self.level, "true_loss": f"{true_loss:.6f}"}],
                )

    def close(self) -> None:
        self.stop_event.set()
        self.join(timeout=1.0)
        self.sock.close()


def payload_for(seq: int, size: int, seed: int) -> bytes:
    rng = random.Random((seed << 32) ^ seq)
    return rng.randbytes(size)


def main() -> None:
    args = parse_args()
    store = CsvRunStore(Path(args.run_dir))
    store.initialise()
    if store.has_packet_rows():
        raise SystemExit(f"run directory already contains packet rows: {Path(args.run_dir).resolve()}")
    feedback = FeedbackListener(store, args.scheme, args.fixed_level)
    feedback.start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    destination = (config.PROXY_HOST, config.PROXY_PORT)
    seq = 0
    try:
        while seq < args.packets:
            level = feedback.level
            r = config.LEVEL_TO_R[level]
            count = min(config.K, args.packets - seq)
            block_id = seq // config.K
            payloads = [payload_for(seq + i, args.payload_bytes, args.seed) for i in range(count)]
            parity_packets = fec.encode(payloads, r)
            block_send_time = time.monotonic()
            packet_rows = []
            for index, payload in enumerate(payloads):
                send_time = time.monotonic()
                packet_rows.append({
                    "scheme": args.scheme, "scenario": args.scenario, "run": args.run,
                    "seq": seq + index, "block_id": block_id, "level": level,
                    "payload_bytes": len(payload), "send_time": f"{send_time:.9f}",
                    "arrive_time": "", "recover_time": "",
                })
            store.append_rows("packets.csv", PACKET_FIELDS, packet_rows)
            store.append_rows("blocks.csv", BLOCK_FIELDS, [{
                "block_id": block_id, "level": level, "k": count, "r": r,
                "parity_bytes": sum(map(len, parity_packets)),
                "send_time": f"{block_send_time:.9f}", "received_count": 0, "recovered": 0,
            }])
            for index, (payload, row) in enumerate(zip(payloads, packet_rows)):
                header = {
                    "type": "data", "seq": seq + index, "block_id": block_id,
                    "data_index": index, "k": count, "r": r, "level": level,
                    "payload_bytes": len(payload), "send_time": float(row["send_time"]),
                }
                sock.sendto(encode_packet(header, payload), destination)
                if args.interval:
                    time.sleep(args.interval)
            for parity_index, payload in enumerate(parity_packets):
                header = {
                    "type": "parity", "block_id": block_id, "parity_index": parity_index,
                    "first_seq": seq, "k": count, "r": r, "level": level,
                    "sizes": [len(item) for item in payloads],
                }
                sock.sendto(encode_packet(header, payload), destination)
                if args.interval:
                    time.sleep(args.interval)
            seq += count
        time.sleep(2 * config.FEEDBACK_INTERVAL)
    finally:
        feedback.close()
        sock.close()
    print(f"sent {args.packets} data packets; logs: {Path(args.run_dir).resolve()}")


if __name__ == "__main__":
    main()
