#!/usr/bin/env python3
"""Count TLV frames on the IWRL6432 uart. Usage: listen.py [secs] [port] [baud]"""
import os
import sys

from radar import DEFAULT_PORT, drain, open_raw, report

if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    port = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PORT
    baud = int(sys.argv[3]) if len(sys.argv) > 3 else 1250000
    fd = open_raw(port, baud)
    rc = report(*drain(fd, secs))
    os.close(fd)
    sys.exit(rc)
