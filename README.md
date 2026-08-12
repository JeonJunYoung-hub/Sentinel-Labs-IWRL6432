# IWRL6432 — mmWave Presence Radar

> **Sentinel Labs** — the presence-sensing half of a construction-site dust
> monitoring system, built under the **Startup for All (모두의 창업)** startup
> program.

Per-zone presence and motion detection with a TI IWRL6432BOOST (60 GHz mmWave).
Host-side Python tooling plus a placeholder Zephyr app for the nRF5340 host.

## How the data is read

**This is UART, not I2C.** The IWRL6432 is a standalone SoC (Cortex-M4F plus
hardware accelerator) — radar signal processing runs entirely on the device, and
only the **processed results** go out over UART as binary TLVs. The host never
touches raw radar data.

```
[IWRL6432 SoC]  --UART-->  [host: PC or nRF5340]
   radar firmware runs        parse magic word + header + TLV blocks
   FFT / CFAR / presence
```

Both directions share the same UART:

1. **host → radar**: ASCII CLI commands. A `.cfg` file is sent line by line to
   configure the profile, then `sensorStart` begins streaming.
2. **radar → host**: binary TLVs, one batch per frame. Each frame starts with the
   magic word `02 01 04 03 06 05 08 07`, followed by a header and then
   type-tagged payloads (point cloud, presence, target list, stats).

The current profile runs a 250 ms period, so about 4 fps.

**The key trap: CLI and data share one single UART.** This is not the
"config port + data port" arrangement familiar from the IWR6843 family. As a
result, `baudRate 1250000` inside the cfg changes the speed of *the very port you
are talking on*, and every line after it must be sent at the new speed.

## Current state

- **Stage 1 (done)** — EVM connected directly to a Mac over USB. `radar.py`
  gets 25/25 cfg lines accepted, and the TLV stream is received and decoded.
- **Stage 2 (planned)** — the nRF5340 takes the PC's place: send cfg over UART,
  parse TLVs. `src/main.c` is still an empty Zephyr skeleton.

For stage 2, **two UART wires are not enough.** The demo cannot be reconfigured
without a reset, so the nRF5340 has to drive the IWRL6432's NRST from a GPIO
(both sides are 3.3V logic, so no level shifter is needed).

## Usage

```bash
cd tools
python3 radar.py iwrl6432-presence.cfg    # warm reset -> send cfg -> verify frames
python3 monitor.py iwrl6432-presence.cfg  # live per-zone occupancy output
python3 listen.py 5                       # count frames for 5 seconds
python3 tlv.py                            # decoder self-check (no hardware needed)
```

No pyserial — stdlib `termios` / `fcntl` covered everything, so no dependency was
added. (1250000 baud has no termios constant, so it is set through the macOS
`IOSSIOSPEED` ioctl.)

## Files

| File | Role |
|---|---|
| `tools/radar.py` | Link management: baud autodetect, warm reset, per-line cfg send and verification |
| `tools/tlv.py` | Frame / TLV decoder (layouts transcribed from the SDK headers) |
| `tools/monitor.py` | Live per-zone occupancy output |
| `tools/listen.py` | Quick frame count / fps check |
| `tools/iwrl6432-presence.cfg` | Presence profile (verified working) |
| `src/main.c` | nRF5340 host app (stage 2, still empty) |

## More detail

Every trap hit during bring-up — firmware/cfg version mismatch, UART dying in
low-power mode, dropped characters, the unresolved tracker issue — is written up
in **[tools/README.md](tools/README.md)** (in Korean). Read it before starting
stage 2.

## Related repository

Air quality measurement (PM2.5 / PM10 / VOC / temperature-humidity) lives in a
separate repo:
[JeonJunYoung-hub/Sentinel-Labs-nRF5340-Wearable](https://github.com/JeonJunYoung-hub/Sentinel-Labs-nRF5340-Wearable) —
that one reads its sensors over **I2C**.
