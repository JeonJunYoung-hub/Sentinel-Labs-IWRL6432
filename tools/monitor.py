#!/usr/bin/env python3
"""Live occupancy for one IWRL6432 board, printed to the terminal.

    python3 monitor.py iwrl6432-presence.cfg   # configure, then monitor
    python3 monitor.py                         # attach to an already-running sensor

One board covers one zone. The board's whole field of view IS the zone, so there
is no sub-zone geometry here -- set ZONE to this board's name and that is the
entire zone configuration.

Caveat worth keeping in mind: the presence demo detects MOTION, not people. A
fan, a swinging door or vibrating machinery in view reads the same as a worker.
Distinguishing them needs the SDK's micro-Doppler classifier, which needs a
tracker-enabled firmware image.

PM2.5 / PM10 are not radar values -- they come from a separate air-quality sensor
and are placeholders so the line format matches the target dashboard.
"""
import os
import select
import sys
import time

import radar
import tlv

ZONE = "A"         # this board's zone name
PRINT_EVERY = 1.0  # frames arrive at 4-5 Hz, too fast to read


def mmss(seconds):
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def render(frame_no, fps, occupied, since, now, mode, points):
    print(f"\n=== {time.strftime('%H:%M:%S')}  frame {frame_no}  {fps:.1f} fps  [{mode}] ===")
    if points:
        # Raw detections, for aiming the board: +y is straight out of the antenna
        # face, +x to its right, +z up. Wave a hand and watch which one moves.
        shown = " ".join(f"({p['x']:+.2f},{p['y']:+.2f},{p['z']:+.2f})" for p in points[:6])
        more = f" +{len(points) - 6}" if len(points) > 6 else ""
        print(f"  점 {len(points)}개 x,y,z m: {shown}{more}")
    who = "근로자 있음" if occupied else "근로자 없음"
    stay = f"체류 {mmss(now - since)}" if occupied and since else "체류 --:--"
    print(f"ZONE {ZONE} | PM2.5   -- ug/m3 | PM10.0   -- ug/m3 | {who} | {stay}")


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else None
    port = sys.argv[2] if len(sys.argv) > 2 else radar.DEFAULT_PORT

    fd, baud = radar.connect(port)
    print(f"connected at {baud}")
    if cfg_path:
        lines = [l.strip() for l in open(cfg_path)]
        lines = [l for l in lines if l and not l.startswith("%")]
        fd = radar.reset(fd, port)
        fd, bad = radar.send_cfg(fd, port, lines)
        if bad:
            os.close(fd)
            return f"cfg rejected {len(bad)} line(s): {bad}"
    else:
        # connect() stopped the sensor in order to talk to it; start it again.
        radar.set_baud(fd, 1250000)
        if radar.failed(radar.send(fd, "sensorStart 0 0 0 0", 15.0)):
            os.close(fd)
            return "could not restart the sensor -- pass a cfg file instead"

    buf, since, occupied = b"", None, False
    last_print = time.monotonic()
    frames_seen, frame_no, mode, points = 0, 0, "presence", []

    print("monitoring, ctrl-c to stop")
    try:
        while True:
            if select.select([fd], [], [], 0.2)[0]:
                buf += os.read(fd, 65536)
            got, buf = tlv.split(buf)
            for raw in got:
                d = tlv.decode(raw)
                frames_seen += 1
                frame_no = d["frameNumber"]
                points = d["points"]
                if d["targets"]:
                    mode, occupied = "tracker", True
                elif d["zones"]:
                    # Any device-side box reporting motion means the zone is
                    # occupied; one box is configured, but OR handles more.
                    mode = "presence"
                    occupied = any(z != "none" for z in d["zones"])
                else:
                    mode = "points"
                    occupied = bool(points)
                # Dwell is the zone's continuous-occupancy clock.
                # ponytail: a single empty frame resets it. Add a grace period of
                # a few frames if it turns out to flicker in the real room.
                since = (since or time.monotonic()) if occupied else None

            now = time.monotonic()
            if now - last_print >= PRINT_EVERY and frames_seen:
                render(frame_no, frames_seen / (now - last_print), occupied, since,
                       now, mode, points)
                frames_seen, last_print = 0, now
    except KeyboardInterrupt:
        print("\nstopping sensor")
        radar.send(fd, "sensorStop 0", 3.0)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
