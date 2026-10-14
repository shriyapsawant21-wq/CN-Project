"""Seeded UDP loss proxy: Bernoulli, Gilbert-Elliott, or time-varying."""

from __future__ import annotations

import argparse
import random
import socket
import time

import config
from packet import PacketError, decode_packet, encode_packet


def schedule_value(schedule: list[tuple[float, float]], elapsed: float) -> float:
    value = schedule[0][1]
    for start, candidate in schedule:
        if elapsed < start:
            break
        value = candidate
    return value


def parse_schedule(raw: str) -> list[tuple[float, float]]:
    result = []
    for item in raw.split(","):
        start, loss = item.split(":", 1)
        result.append((float(start), float(loss)))
    result.sort()
    if not result or result[0][0] != 0:
        raise argparse.ArgumentTypeError("schedule must start at 0 seconds")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("bernoulli", "gilbert", "time-varying"), default="bernoulli")
    parser.add_argument("--loss", type=float, default=0.05)
    parser.add_argument("--schedule", type=parse_schedule, default=parse_schedule("0:0.02,5:0.10,10:0.20,15:0.05"))
    parser.add_argument("--p-good-bad", type=float, default=0.02)
    parser.add_argument("--p-bad-good", type=float, default=0.25)
    parser.add_argument("--good-loss", type=float, default=0.01)
    parser.add_argument("--bad-loss", type=float, default=0.60)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--idle-timeout", type=float, default=3.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.PROXY_HOST, config.PROXY_PORT))
    sock.settimeout(config.SOCKET_TIMEOUT)
    destination = (config.RECEIVER_HOST, config.RECEIVER_PORT)
    start = time.monotonic()
    last_packet: float | None = None
    bad_state = False
    forwarded = dropped = 0
    print(f"proxy listening on UDP {config.PROXY_PORT}; seed={args.seed}")
    try:
        while True:
            try:
                datagram, _ = sock.recvfrom(65535)
            except socket.timeout:
                if last_packet is not None and time.monotonic() - last_packet >= args.idle_timeout:
                    break
                continue
            now = time.monotonic()
            last_packet = now
            elapsed = now - start
            if args.model == "bernoulli":
                true_loss = args.loss
            elif args.model == "time-varying":
                true_loss = schedule_value(args.schedule, elapsed)
            else:
                if bad_state:
                    if rng.random() < args.p_bad_good:
                        bad_state = False
                elif rng.random() < args.p_good_bad:
                    bad_state = True
                true_loss = args.bad_loss if bad_state else args.good_loss
            if rng.random() < true_loss:
                dropped += 1
                continue
            try:
                header, payload = decode_packet(datagram)
                header["true_loss"] = true_loss
                datagram = encode_packet(header, payload)
            except PacketError:
                pass
            sock.sendto(datagram, destination)
            forwarded += 1
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f"proxy stopped: forwarded={forwarded}, dropped={dropped}")


if __name__ == "__main__":
    main()
