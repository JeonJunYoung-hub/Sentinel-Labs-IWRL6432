#!/usr/bin/env python3
"""Decode the IWRL6432 Presence/Tracking demo UART output.

Every layout here is transcribed from MMWAVE_L_SDK 05.05.04.02 sources, not
guessed:

  MmwDemo_output_message_header       motion_detect.h:1350   magic[8] + 8x u32
  MmwDemo_output_message_point_unit   motion_detect.h:344    4x f32 + 2x u16
  MmwDemo_output_message_UARTpoint    motion_detect.h:371    4x i16 + 2x u8
  trackerProc_Target (GTRACK_3D)      trackerproc.h:261      u32 + 27x f32
  enhanced presence payload           motion_detect.c:1216   "0th index - No. of
      zones processed, 1st index onwards - 2bits state per zone from LSB"
"""
import struct

MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])  # {0x0102,0x0304,0x0506,0x0708} LE
HDR_LEN = 40

EXT = 300
POINTS = EXT + 1            # 301
RANGE_PROFILE_MAJOR = EXT + 2
RANGE_PROFILE_MINOR = EXT + 3
STATS = EXT + 6             # 306
PRESENCE_INFO = EXT + 7
TARGET_LIST = EXT + 8       # 308
TARGET_INDEX = EXT + 9
ENHANCED_PRESENCE = EXT + 15  # 315

NAMES = {
    POINTS: "DETECTED_POINTS", RANGE_PROFILE_MAJOR: "RANGE_PROFILE_MAJOR",
    RANGE_PROFILE_MINOR: "RANGE_PROFILE_MINOR", EXT + 4: "HEAT_MAP_MAJOR",
    EXT + 5: "HEAT_MAP_MINOR", STATS: "STATS", PRESENCE_INFO: "PRESENCE_INFO",
    TARGET_LIST: "TARGET_LIST", TARGET_INDEX: "TARGET_INDEX",
    EXT + 10: "MICRO_DOPPLER_RAW", EXT + 11: "MICRO_DOPPLER_FEATURES",
    EXT + 12: "RADAR_CUBE_MAJOR", EXT + 13: "RADAR_CUBE_MINOR",
    EXT + 14: "POINT_CLOUD_INDICES", ENHANCED_PRESENCE: "ENHANCED_PRESENCE",
    EXT + 16: "ADC_SAMPLES", EXT + 17: "CLASSIFIER_INFO",
    EXT + 18: "RX_CHAN_COMP", EXT + 19: "QUICK_EVAL", EXT + 20: "PC_ANT_SYMBOLS",
}

POINT_UNIT = struct.Struct("<4f2H")   # 20 bytes
POINT = struct.Struct("<4h2B")        # 10 bytes
TARGET_3D = struct.Struct("<I27f")    # 112 bytes
TARGET_2D = struct.Struct("<I18f")    # 76 bytes -- GTRACK_2D build

ZONE_STATE = {0: "none", 1: "minor", 2: "major", 3: "?"}


def split(buf):
    """Pull complete frames out of a byte stream.

    Returns (frames, remainder). Framing trusts the header's own totalPacketLen
    rather than scanning for the next magic word, so a magic-looking byte pair
    inside a payload cannot desync us.
    """
    out, i = [], buf.find(MAGIC)
    if i < 0:
        # Keep only a possible partial magic at the tail.
        return out, buf[-len(MAGIC):] if len(buf) > len(MAGIC) else buf
    while i + HDR_LEN <= len(buf):
        total = struct.unpack_from("<I", buf, i + 12)[0]
        if not HDR_LEN <= total <= 65536:
            i = buf.find(MAGIC, i + len(MAGIC))   # bogus length, resync
            if i < 0:
                return out, b""
            continue
        if i + total > len(buf):
            break                                  # frame still arriving
        out.append(buf[i:i + total])
        i += total
        if buf[i:i + len(MAGIC)] != MAGIC:
            j = buf.find(MAGIC, i)
            if j < 0:
                return out, buf[i:]
            i = j
    return out, buf[i:]


def header(frame):
    _, ver, total, plat, num, cycles, ndet, ntlv = struct.unpack_from("<8s7I", frame)
    sub = struct.unpack_from("<I", frame, 36)[0]
    return dict(version=ver, totalPacketLen=total, platform=plat, frameNumber=num,
                timeCpuCycles=cycles, numDetectedObj=ndet, numTLVs=ntlv,
                subFrameNumber=sub)


def tlvs(frame):
    """Yield (type, payload). Stops cleanly on a truncated or lying length."""
    total = struct.unpack_from("<I", frame, 12)[0]
    off = HDR_LEN
    while off + 8 <= total:
        t, ln = struct.unpack_from("<II", frame, off)
        if off + 8 + ln > total:
            break
        yield t, frame[off + 8:off + 8 + ln]
        off += 8 + ln


def points(payload):
    """Point cloud -> list of dicts in metres / m per s / dB."""
    if len(payload) < POINT_UNIT.size:
        return []
    xyz_u, dop_u, snr_u, noise_u, n_major, n_minor = POINT_UNIT.unpack_from(payload)
    out = []
    for off in range(POINT_UNIT.size, len(payload) - POINT.size + 1, POINT.size):
        x, y, z, dop, snr, noise = POINT.unpack_from(payload, off)
        out.append(dict(x=x * xyz_u, y=y * xyz_u, z=z * xyz_u,
                        doppler=dop * dop_u, snr=snr * snr_u, noise=noise * noise_u))
    # numDetectedPoints is [major, minor]; the list itself is major then minor.
    for i, p in enumerate(out):
        p["motion"] = "major" if i < n_major else "minor"
    return out


def targets(payload):
    """Tracker output -> list of tracks. Picks the struct the length divides by,
    so a GTRACK_2D firmware build decodes too."""
    for spec, has_z in ((TARGET_3D, True), (TARGET_2D, False)):
        if payload and len(payload) % spec.size == 0:
            out = []
            for off in range(0, len(payload), spec.size):
                f = spec.unpack_from(payload, off)
                if has_z:
                    tid, px, py, pz, vx, vy, vz = f[0], f[1], f[2], f[3], f[4], f[5], f[6]
                    conf = f[27]
                else:
                    tid, px, py, vx, vy = f[0], f[1], f[2], f[3], f[4]
                    pz, vz, conf = 0.0, 0.0, f[18]
                out.append(dict(tid=tid, x=px, y=py, z=pz, vx=vx, vy=vy, vz=vz,
                                speed=(vx * vx + vy * vy + vz * vz) ** 0.5,
                                confidence=conf))
            return out
    return []


def presence(payload):
    """Enhanced presence -> list of per-zone state strings, zone 1 first."""
    if len(payload) < 2:
        return []
    n = payload[0]
    bits = payload[1:]
    out = []
    for z in range(n):
        byte = bits[z // 4] if z // 4 < len(bits) else 0
        out.append(ZONE_STATE[(byte >> (2 * (z % 4))) & 0x3])
    return out


def decode(frame):
    d = header(frame)
    d["tlvs"] = {}
    for t, payload in tlvs(frame):
        d["tlvs"][t] = payload
    d["points"] = points(d["tlvs"].get(POINTS, b""))
    d["targets"] = targets(d["tlvs"].get(TARGET_LIST, b""))
    d["zones"] = presence(d["tlvs"].get(ENHANCED_PRESENCE, b""))
    return d


def _selfcheck():
    assert POINT_UNIT.size == 20 and POINT.size == 10
    assert TARGET_3D.size == 112, TARGET_3D.size
    # A real captured frame: 4 TLVs, 1 point, 4 zones, totals to 640 bytes.
    body = b""
    body += struct.pack("<II", POINTS, 30) + POINT_UNIT.pack(0.01, 0.05, 0.1, 0.1, 1, 0) \
        + POINT.pack(100, 250, -30, 4, 60, 20)
    body += struct.pack("<II", RANGE_PROFILE_MINOR, 512) + bytes(512)
    body += struct.pack("<II", STATS, 24) + bytes(24)
    body += struct.pack("<II", ENHANCED_PRESENCE, 2) + bytes([4, 0b00_10_00_01])
    total = HDR_LEN + len(body)
    hdr = MAGIC + struct.pack("<7I", 0x05050300, total, 0x000a6432, 7, 0, 1, 4) \
        + struct.pack("<I", 0xFFFFFFFF)
    frame = hdr + body
    assert total == 640, total

    got, rest = split(frame + frame + MAGIC[:3])
    assert len(got) == 2 and rest == MAGIC[:3], (len(got), rest)

    d = decode(frame)
    assert d["frameNumber"] == 7 and d["numTLVs"] == 4
    assert len(list(tlvs(frame))) == 4
    p = d["points"][0]
    assert abs(p["x"] - 1.0) < 1e-6 and abs(p["y"] - 2.5) < 1e-6
    assert abs(p["doppler"] - 0.2) < 1e-6 and p["motion"] == "major"
    assert d["zones"] == ["minor", "none", "major", "none"], d["zones"]

    # Tracker path: two 3D targets round-trip.
    tl = TARGET_3D.pack(9, 1.5, 3.0, 1.2, *([0.0] * 24)) \
        + TARGET_3D.pack(10, -2.0, 5.0, 1.1, *([0.0] * 24))
    ts = targets(tl)
    assert [t["tid"] for t in ts] == [9, 10]
    assert abs(ts[0]["x"] - 1.5) < 1e-6 and abs(ts[1]["y"] - 5.0) < 1e-6


if __name__ == "__main__":
    _selfcheck()
    print("tlv.py selfcheck ok")
