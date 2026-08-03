#!/usr/bin/env python3
"""Configure an IWRL6432BOOST running the Presence_Demo, and prove it streams.

Everything here exists because of one fact: the demo multiplexes the CLI and the
TLV data stream onto a SINGLE uart (the XDS110 "Application/User" port). The
second XDS110 port is not wired to the SoC.

Usage: radar.py <cfg-file> [port]
       echo version | radar.py - [port]
"""
import fcntl
import os
import select
import struct
import sys
import termios
import time

PROMPT = b"mmwDemo:/>"
MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])  # 0x0102 0304 0506 0708, little-endian
IOSSIOSPEED = 0x80085402  # _IOW('T', 2, unsigned long) -- macOS arbitrary baud
DEFAULT_PORT = "/dev/cu.usbmodemRI321"
BOOT_BAUD = 115200


def open_raw(path, baud=BOOT_BAUD):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0  # iflag, oflag, lflag: fully raw
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    termios.tcsetattr(fd, termios.TCSANOW, a)
    set_baud(fd, baud)
    return fd


def set_baud(fd, baud):
    """IOSSIOSPEED, not termios -- 1250000 has no Bxxx constant on macOS."""
    fcntl.ioctl(fd, IOSSIOSPEED, struct.pack("L", baud))
    termios.tcflush(fd, termios.TCIOFLUSH)


def write_slow(fd, text, per_char=0.001):
    """The demo echoes each char from a polling loop and drops input if a whole
    line lands at once -- silently, since the mangled line just never returns
    'Done'. Trickle it."""
    for ch in text.encode():
        os.write(fd, bytes([ch]))
        time.sleep(per_char)


def send(fd, line, timeout):
    """Write one CLI line, read until the prompt returns. Returns raw reply."""
    write_slow(fd, line + "\n")
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if select.select([fd], [], [], 0.1)[0]:
            buf += os.read(fd, 4096)
            if buf.rstrip().endswith(PROMPT):
                break
    return buf


def failed(reply):
    """Only an explicit 'Done' counts. Absence of 'Error' does not: at the wrong
    baud, and while TLV data is streaming, replies contain neither word."""
    return b"Done" not in reply


def connect(port, bauds=(BOOT_BAUD, 1250000)):
    """Find the speed the device is actually at, and silence it.

    We can never assume: a previous run's `baudRate` sticks until reset, and
    while the sensor streams, CLI replies are buried in binary. sensorStop is
    idempotent and halts the stream, so it doubles as the probe.
    """
    for baud in bauds:
        fd = open_raw(port, baud)
        # A wrong-baud attempt leaves half a garbage line in the device's
        # parser, which would swallow the next command. Newline ends it first.
        for _ in range(2):
            send(fd, "", 0.5)
            if not failed(send(fd, "sensorStop 0", 2.0)):
                return fd, baud
        os.close(fd)
    raise SystemExit(f"no reply at {bauds} -- power-cycle the EVM and retry")


def reset(fd, port):
    """The OOB demo cannot be reconfigured in place. A second cfg is accepted --
    every line returns 'Done' -- but the sensor then never streams a frame. Only
    a reset makes a new cfg take effect. Returns a fresh fd at the boot baud.

    Needs lowPowerCfg 0: in low-power mode the device sleeps between frames and
    stops servicing uart RX, so nothing (not even this) gets through once
    sensorStart has run. Then only NRST or a USB replug recovers it.
    """
    send(fd, "sensorWarmRst 0", 2.0)  # reboots; no reply comes back
    os.close(fd)
    time.sleep(2.0)
    fd = open_raw(port, BOOT_BAUD)
    send(fd, "", 0.5)
    return fd


def drain(fd, secs):
    buf = b""
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs:
        if select.select([fd], [], [], 0.1)[0]:
            buf += os.read(fd, 65536)
    return buf, time.monotonic() - t0


def report(buf, elapsed):
    frames = buf.count(MAGIC)
    print(f"  {len(buf)} bytes in {elapsed:.1f}s, {frames} frames ({frames/elapsed:.1f} fps)")
    if not frames:
        print("  no magic word -- sensor not streaming")
        return 1
    # Header right after the magic: version, totalPacketLen, platform, frameNumber
    off = buf.find(MAGIC) + len(MAGIC)
    ver, plen, plat, frame = struct.unpack_from("<IIII", buf, off)
    print(f"  version=0x{ver:08x} platform=0x{plat:08x} packetLen={plen} frame={frame}")
    return 0


def send_cfg(fd, port, lines):
    """Returns (fd, list-of-rejected-lines). fd may be new: a baudRate line
    changes this port's speed too, and reset() reopens it."""
    bad = []
    for ln in lines:
        cmd = ln.split()[0]

        if cmd == "baudRate":
            # Answered at the NEW speed, so nothing is readable here. Switch,
            # then prove the link with a command that does reply.
            write_slow(fd, ln + "\n")
            time.sleep(0.2)
            set_baud(fd, int(ln.split()[1]))
            alive = not failed(send(fd, "version", 3.0))
            print(f"  {'ok  ' if alive else 'FAIL'}  {ln}  (link {'ok' if alive else 'lost'})")
            if not alive:
                bad.append(ln)
            continue

        reply = send(fd, ln, 15.0 if cmd == "sensorStart" else 3.0)
        if failed(reply):
            bad.append(ln)
            body = reply.decode("utf-8", "replace").replace(ln, "", 1).strip()[:200]
            print(f"  FAIL  {ln}\n        {body}")
        else:
            print(f"  ok    {ln}")
    return fd, bad


def main():
    cfg_path = sys.argv[1]
    port = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PORT
    text = sys.stdin.read() if cfg_path == "-" else open(cfg_path).read()
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%")]
    one_shot = cfg_path == "-"

    fd, baud = connect(port)
    print(f"  --    connected at {baud}")
    if not one_shot:
        fd = reset(fd, port)
        print(f"  --    warm reset, back at {BOOT_BAUD}")

    fd, bad = send_cfg(fd, port, lines)
    print(f"\n  {len(lines) - len(bad)}/{len(lines)} accepted")

    rc = 1 if bad else 0
    if not bad and not one_shot:
        rc = report(*drain(fd, 3.0))
    os.close(fd)
    return rc


def _selfcheck():
    assert failed(b"Error: bad arg\nmmwDemo:/>")
    assert failed(b"")                            # silence == dead link
    assert failed(b"}w{w}w}[ou{{u\xef\xbf\xbd")   # garbage == wrong baud
    assert not failed(b"channelCfg 7 3 0\nDone\nmmwDemo:/>")


if __name__ == "__main__":
    _selfcheck()
    sys.exit(main())
