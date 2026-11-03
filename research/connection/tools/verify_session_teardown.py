"""Audit one diagnostic.log for the "every live session must announce itself to the car" rule.

Why this exists
---------------
A session that streams video and then disappears without a whole-session TEARDOWN leaves the
car's iAP state machine half-open. The next connect then dies as `iAP NO_SYN` and only a car-side
power cycle clears it (car-verified 2026-11-04). The rule is therefore structural, not cosmetic:
*any* session that reached the connected stages must end with either

  - `AirPlay whole-session TEARDOWN begin`            (we tried to tell the car), or
  - `AirPlay whole-session stop skipped: ...`         (we had no control channel left to try).

Everything else is a hole. The old build (20049) has two such holes and zero `TEARDOWN begin`
lines on the app-disconnect path, which is exactly what this script is meant to catch.

Usage
-----
  python research/connection/tools/verify_session_teardown.py research/logs/t3-20050.txt
  adb shell run-as com.baidu.carlife.xiaomi cat files/diagnostic.log > /tmp/d.log
  python research/connection/tools/verify_session_teardown.py /tmp/d.log --quiet

Exit code is 0 only when every connected session has a recorded stop attempt.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True

LINE = re.compile(r"^(?P<ts>\S+) \[(?P<id>[0-9a-f]{8}|entry)\] (?P<msg>.*)$")

# Headers that prove the AirPlay control link came up: without SETUP there is no session to stop,
# so a DETECT/BLUETOOTH failure is out of scope for this audit.
CONNECTED_STAGES = {"SETUP", "WAIT_FRAME", "STREAMING"}

TEARDOWN_BEGIN = "AirPlay whole-session TEARDOWN begin"
TEARDOWN_OK = "AirPlay whole-session TEARDOWN accepted"
TEARDOWN_UNCONFIRMED = "AirPlay whole-session TEARDOWN unconfirmed"
TEARDOWN_SKIPPED = "AirPlay whole-session stop skipped"


@dataclass
class Session:
    sid: str
    stages: set[str] = field(default_factory=set)
    last_stage: str = ""
    heartbeats: int = 0
    last_ts: str = ""
    teardown: str = ""          # begin / accepted / unconfirmed / skipped / ""
    stop_lines: list[str] = field(default_factory=list)

    @property
    def connected(self) -> bool:
        return bool(self.stages & CONNECTED_STAGES)

    @property
    def streamed(self) -> bool:
        return self.heartbeats > 0

    @property
    def verdict(self) -> str:
        # Only sessions that actually held the car's input focus matter: that is the state the car
        # cannot rebuild on its own. A SETUP that never streamed still negotiated, so it counts too.
        if not self.connected:
            return "n/a"
        if self.teardown in ("begin", "accepted", "unconfirmed", "skipped"):
            return "PASS"
        return "FAIL"

    @property
    def note(self) -> str:
        if self.teardown == "accepted":
            return "car acknowledged the stop"
        if self.teardown == "unconfirmed":
            return "stop sent, no ack (socket already gone)"
        if self.teardown == "skipped":
            return "no control channel left to send it on"
        if self.teardown == "begin":
            return "waiting for the car"
        if self.connected:
            return "session vanished without any stop attempt"
        return "never reached SETUP"


def parse(path: Path) -> dict[str, Session]:
    sessions: dict[str, Session] = {}
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            match = LINE.match(raw.rstrip("\n"))
            if not match:
                continue
            sid, msg = match.group("id"), match.group("msg")
            if sid == "entry":
                continue
            record = sessions.setdefault(sid, Session(sid))
            record.last_ts = match.group("ts")
            if msg.startswith("stage "):
                stage = msg[len("stage "):].strip()
                record.stages.add(stage)
                record.last_stage = stage
            elif msg.startswith("hb "):
                record.heartbeats += 1
            if TEARDOWN_BEGIN in msg:
                record.teardown = "begin"
                record.stop_lines.append(msg)
            elif TEARDOWN_OK in msg:
                record.teardown = "accepted"
                record.stop_lines.append(msg)
            elif TEARDOWN_UNCONFIRMED in msg:
                record.teardown = "unconfirmed"
                record.stop_lines.append(msg)
            elif TEARDOWN_SKIPPED in msg:
                record.teardown = "skipped"
                record.stop_lines.append(msg)
    return sessions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path)
    parser.add_argument("--quiet", action="store_true", help="only print the summary and failures")
    args = parser.parse_args()

    if not args.log.is_file():
        print(f"not a file: {args.log}", file=sys.stderr)
        return 2

    sessions = parse(args.log)
    ordered = sorted(sessions.values(), key=lambda s: s.last_ts)

    if not args.quiet:
        print(f"log: {args.log}  sessions: {len(ordered)}")
        print()
        print(f"{'id':<10}{'reached':<12}{'hb':>7}  {'stop':<12}verdict")
        print("-" * 62)
        for s in ordered:
            if not s.connected and s.verdict == "n/a":
                continue
            reached = s.last_stage or "?"
            print(f"{s.sid:<10}{reached:<12}{s.heartbeats:>7}  {s.teardown or '-':<12}{s.verdict}  ({s.note})")
        print()

    failures = [s for s in ordered if s.verdict == "FAIL"]
    connected = [s for s in ordered if s.connected]
    streamed = [s for s in ordered if s.streamed]
    begins = sum(1 for s in ordered if s.teardown in ("begin", "accepted", "unconfirmed"))

    tail = "" if not ordered else ordered[-1].last_ts
    print(f"connected sessions: {len(connected)}   streamed: {len(streamed)}   stop attempts: {begins}")
    print(f"last activity: {tail}")
    if failures:
        print()
        print("FAILED: these sessions held the car and never told it they were leaving")
        for s in failures:
            print(f"  {s.sid}  last stage {s.last_stage or '?'}  heartbeats {s.heartbeats}  last line {s.last_ts}")
        print()
        print("A car stuck in this state answers the next RFCOMM connect but never sends iAP SYN")
        print("(`iAP NO_SYN`), and only a car-side power cycle clears it.")
        return 1

    print()
    print("OK: every connected session recorded a stop attempt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
