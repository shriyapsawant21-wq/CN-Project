"""Receive forwarded packets, recover erasures, update logs, and report loss."""

from __future__ import annotations

import argparse
import json
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path

import config
import fec
from log_store import BLOCK_FIELDS, PACKET_FIELDS, CsvRunStore
from packet import PacketError, decode_packet


@dataclass
class Block:
    block_id: int
    first_seq: int
    k: int
    r: int
    sizes: list[int]
    created: float
    data: list[bytes | None] = field(init=False)
    parity: dict[int, bytes] = field(default_factory=dict)
    received: int = 0
    true_loss: float = 0.0

    def __post_init__(self) -> None:
        self.data = [None] * self.k


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--idle-timeout", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = CsvRunStore(Path(args.run_dir))
    store.initialise()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.RECEIVER_HOST, config.RECEIVER_PORT))
    sock.settimeout(config.SOCKET_TIMEOUT)
    feedback_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocks: dict[int, Block] = {}
    completed_blocks: set[int] = set()
    last_packet: float | None = None
    latest_true_loss = 0.0
    interval_expected = interval_received = 0
    last_feedback = time.monotonic()
    # Timestamps are taken immediately as events happen but written to the CSVs
    # once, on exit. Rewriting the CSV for every packet made the receiver fall
    # behind on long runs, which inflated delays and produced false loss.
    packet_updates: dict[int, dict] = {}
    block_updates: dict[int, dict] = {}

    def finish(block: Block) -> None:
        missing_before = [i for i, packet in enumerate(block.data) if packet is None]
        recovered = fec.recover(block.data, block.parity) if missing_before else {}
        recover_time = time.monotonic()
        for index, payload in recovered.items():
            block.data[index] = payload[: block.sizes[index]]
            seq = block.first_seq + index
            packet_updates.setdefault(seq, {})["recover_time"] = f"{recover_time:.9f}"
        complete = all(packet is not None for packet in block.data)
        block_updates[block.block_id] = {"received_count": block.received, "recovered": int(complete)}

    print(f"receiver listening on UDP {config.RECEIVER_PORT}")
    try:
        while True:
            now = time.monotonic()
            try:
                datagram, _ = sock.recvfrom(65535)
                now = time.monotonic()
                last_packet = now
                header, payload = decode_packet(datagram)
            except socket.timeout:
                header = None
                payload = b""
            except PacketError:
                continue
            if header is not None and header.get("type") in {"data", "parity"}:
                block_id = int(header["block_id"])
                if block_id in completed_blocks:
                    continue
                k = int(header["k"])
                first_seq = int(header.get("first_seq", int(header.get("seq", 0)) - int(header.get("data_index", 0))))
                block = blocks.get(block_id)
                if block is None:
                    sizes = list(map(int, header.get("sizes", [header.get("payload_bytes", 0)] * k)))
                    block = blocks[block_id] = Block(block_id, first_seq, k, int(header["r"]), sizes, now)
                block.true_loss = float(header.get("true_loss", block.true_loss))
                latest_true_loss = block.true_loss
                block.received += 1
                if header["type"] == "data":
                    index = int(header["data_index"])
                    if block.data[index] is None:
                        block.data[index] = payload
                        block.sizes[index] = int(header["payload_bytes"])
                        seq = int(header["seq"])
                        packet_updates.setdefault(seq, {})["arrive_time"] = f"{now:.9f}"
                else:
                    block.sizes = list(map(int, header["sizes"]))
                    block.parity[int(header["parity_index"])] = payload
                if all(packet is not None for packet in block.data) or len(block.parity) >= sum(packet is None for packet in block.data):
                    interval_expected += block.k
                    interval_received += sum(packet is not None for packet in block.data)
                    finish(block)
                    del blocks[block_id]
                    completed_blocks.add(block_id)
            now = time.monotonic()
            expired = [key for key, block in blocks.items() if now - block.created >= config.BLOCK_GRACE]
            for key in expired:
                block = blocks.pop(key)
                interval_expected += block.k
                interval_received += sum(packet is not None for packet in block.data)
                finish(block)
                completed_blocks.add(key)
            if now - last_feedback >= config.FEEDBACK_INTERVAL and interval_expected:
                measured_loss = 1.0 - interval_received / interval_expected
                report = json.dumps({"measured_loss": measured_loss, "true_loss": latest_true_loss}).encode()
                feedback_sock.sendto(report, (config.FEEDBACK_HOST, config.FEEDBACK_PORT))
                interval_expected = interval_received = 0
                last_feedback = now
            if last_packet is not None and not blocks and now - last_packet >= args.idle_timeout:
                break
    except KeyboardInterrupt:
        for block in list(blocks.values()):
            finish(block)
    finally:
        sock.close()
        feedback_sock.close()
        store.update_keyed("packets.csv", PACKET_FIELDS, "seq", packet_updates)
        store.update_keyed("blocks.csv", BLOCK_FIELDS, "block_id", block_updates)
    print("receiver stopped after idle timeout")


if __name__ == "__main__":
    main()
