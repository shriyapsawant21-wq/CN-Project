# CSV logging contract to share with the implementation teammate

Create one folder per run containing exactly these three CSVs.

## `packets.csv`

One row per **data** packet:

```text
scheme,scenario,run,seq,block_id,level,payload_bytes,send_time,arrive_time,recover_time
```

`arrive_time` is blank if the proxy dropped the packet. `recover_time` is blank
if the packet was not rebuilt or did not need rebuilding.

## `blocks.csv`

One row per block:

```text
block_id,level,k,r,parity_bytes,send_time,received_count,recovered
```

`recovered` is 1 if the block was fully rebuilt or arrived complete; it is 0
if the losses exceeded the available parity.

## `controller.csv`

One row per feedback report:

```text
time,measured_loss,level,true_loss
```

`true_loss` is the proxy's current loss setting, enabling the level-versus-loss
time plot.

## Required rules

- Use `time.monotonic()` for every timestamp. All processes run on one machine.
- Plain UDP and fixed-FEC use the same files. Plain UDP uses level 0 and zero
  parity bytes; fixed-FEC keeps its configured level constant.
- Seed the proxy random generator and reuse the same seed for all three schemes
  in each run.

The analysis defines an on-time packet as one whose arrival or recovery time is
no more than the configured playout deadline after its send time.
