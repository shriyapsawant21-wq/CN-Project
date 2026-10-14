# Numbered system diagrams

## Figure 1 — End-to-end flow

```mermaid
flowchart LR
  S[Sender + adaptive controller] -->|data + parity, UDP 5001| P[Seeded loss proxy]
  P -->|surviving packets, UDP 5002| R[Receiver + FEC decoder]
  R -->|loss feedback, UDP 5003| S
  S --- L[(Three CSV logs per run)]
  R --- L
```

**Figure 1.** Shows that every data/parity packet crosses the controlled loss
proxy and that receiver feedback closes the adaptation loop.

## Figure 2 — Block structure

```mermaid
flowchart LR
  subgraph B[One FEC block]
    D1[D1] --- D2[D2] --- DX[...] --- D10[D10]
    D10 --- P1[P1]
    P1 --- PX[...]
    PX --- PR[Pr]
  end
```

**Figure 2.** Proves the block contains `k=10` data packets followed by `r`
parity packets, where `r` is 0, 1, 2, or 4 according to the scheme and level.

## Figure 3 — Controller state machine

```mermaid
stateDiagram-v2
  Low --> Medium: measured loss >= 5%
  Medium --> High: measured loss >= 15%
  Medium --> Low: measured loss < 3%
  High --> Medium: measured loss < 13%
```

**Figure 3.** Shows the low/medium/high thresholds and the two-percentage-point
downward hysteresis that prevents rapid state oscillation.

## Figure 4 — Localhost port layout

```mermaid
flowchart LR
  A[Sender] -->|destination 127.0.0.1:5001| B[Proxy]
  B -->|destination 127.0.0.1:5002| C[Receiver]
  C -->|destination 127.0.0.1:5003| A
```

**Figure 4.** Identifies the three localhost ports so a packet capture can
separate outbound traffic, forwarded traffic, and control feedback.
