#!/usr/bin/env python3
"""Minimal QEMU Guest Agent (QGA) client for the feed-validation boot tier.

Talks to the agent channel that `vm --qga-port <port>` exposes (a TCP chardev,
host-reachable because `avocado sdk run` uses --network=host). Used to verify a
booted target without ssh, since the local distro+SDK feed has no sshd.

Usage:
  qga-exec.py --port PORT --wait [--deadline SECONDS]   # block until agent live
  qga-exec.py --port PORT --run "CMD"                    # run CMD, exit w/ guest rc

--wait exits 0 once `guest-sync` round-trips, 1 on timeout. --run executes CMD
via `/bin/sh -c`, prints the guest's stdout, and exits with the guest's exit
code (or 1 on agent/transport error).
"""

import argparse
import base64
import json
import socket
import sys
import time

HOST = "127.0.0.1"


def _connect(port, timeout):
    sock = socket.create_connection((HOST, port), timeout=timeout)
    sock.settimeout(timeout)
    return sock


def _rpc(sock, command, arguments=None):
    msg = {"execute": command}
    if arguments is not None:
        msg["arguments"] = arguments
    sock.sendall((json.dumps(msg) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.split(b"\n", 1)[0].decode())


def _sync(sock):
    # guest-sync echoes the id back once the stream is aligned.
    uid = int(time.time() * 1000) & 0x7FFFFFFF
    return _rpc(sock, "guest-sync", {"id": uid}).get("return") == uid


def wait_for_agent(port, deadline):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        try:
            sock = _connect(port, timeout=3.0)
            try:
                if _sync(sock):
                    return True
            finally:
                sock.close()
        except (OSError, ValueError):
            pass
        time.sleep(2)
    return False


def run(port, cmd, exec_timeout):
    sock = _connect(port, timeout=5.0)
    try:
        if not _sync(sock):
            print("qga: guest-sync failed", file=sys.stderr)
            return 1
        started = _rpc(
            sock,
            "guest-exec",
            {"path": "/bin/sh", "arg": ["-c", cmd], "capture-output": True},
        )
        pid = started["return"]["pid"]
        end = time.monotonic() + exec_timeout
        while time.monotonic() < end:
            status = _rpc(sock, "guest-exec-status", {"pid": pid}).get("return", {})
            if status.get("exited"):
                out = base64.b64decode(status.get("out-data", "") or b"")
                err = base64.b64decode(status.get("err-data", "") or b"")
                sys.stdout.write(out.decode(errors="replace"))
                sys.stderr.write(err.decode(errors="replace"))
                return int(status.get("exitcode", 1))
            time.sleep(0.5)
        print("qga: guest-exec timed out", file=sys.stderr)
        return 1
    finally:
        sock.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--deadline", type=int, default=180)
    ap.add_argument("--run")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    if args.wait:
        return 0 if wait_for_agent(args.port, args.deadline) else 1
    if args.run is not None:
        try:
            return run(args.port, args.run, args.timeout)
        except (OSError, ValueError, KeyError) as exc:
            print(f"qga: {exc}", file=sys.stderr)
            return 1
    ap.error("one of --wait or --run is required")


if __name__ == "__main__":
    sys.exit(main())
