"""Re-check the 5702 sender contract against the original 24A446 accessoryd bytes.

Why this exists
---------------
[91](../spec/91-wifisharing-start-feature-5702.md) claims three things that are easy to lose
later, because they look like implementation detail and are actually firmware contract:

* `0x5702` is sent **once** per iAP session — there is no resend path in the sender;
* the only call site is `_iap2_wifisharing__startFeatureFromDevice`, i.e. it is the *start
  action* of feature 22 (WiFiSharing), not a polled request;
* it is gated on the car having declared {5702 we send, 5703 we receive}.

If any of those stops being true — a re-extracted binary, a different IPSW, someone "helpfully"
adding a retry loop on the phone side — the claim has to be reopened instead of quietly
diverging. This script re-derives all three from the bytes and exits non-zero when they differ.

Read-only: it never writes, never runs the original code, never touches the firmware cache.

Usage
-----
  python research/connection/tools/inspect_wifisharing_start_feature.py
  python research/connection/tools/inspect_wifisharing_start_feature.py --binary /tmp/accessoryd
  python research/connection/tools/inspect_wifisharing_start_feature.py --quiet
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[3]

# The firmware submodule keeps extracted components under this prefix. The binary itself is not
# tracked in the research repo, so a missing file is a SKIP, not a failure.
BINARY = ROOT / (
    "firmware/extracted/24A446/components/24A446__iPhone18,1/root/"
    "System/Library/PrivateFrameworks/CoreAccessories.framework/Support/accessoryd"
)
FUNCTIONS = ROOT / "firmware/analysis/24A446/accessoryd-functions.json"

EXPECTED_SHA256 = "2b0a2010e6d2605e07d87f05659c932e03de34476a76431196a9bb58da7dc4fe"

SENDER = 0x100170BB0
SENDER_END = 0x100170C3C  # next function: __createFeature
START_FEATURE = 0x100170CB8
START_FEATURE_END = 0x100170D80  # next function: _checkIdentificationInfo
DESCRIPTOR = 0x1001B40C0
TEXT_BASE = 0x100000000
TEXT_SPAN = 0x218000

SEND_HELPER = 0x100005130  # _iap2_sessionControl_sendOutgoingMessage
INIT_HELPER = 0x100003424  # _iAP2MsgInit
GATE_HELPER = 0x100050C2C  # _iap2_identification_checkRequiredMsgIDs
FEATURE_GET = 0x100003360  # _iap2_feature_getFeature

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        failures.append(message)


def disasm(data: bytes, md, start: int, end: int) -> list:
    return list(md.disasm(data[start - TEXT_BASE:end - TEXT_BASE], start))


def imm_target(ins) -> int | None:
    """Last immediate operand of a branch — good enough for bl/b/cbz/cbnz here."""
    target = None
    for operand in ins.operands:
        if operand.type == 2:  # ARM64_OP_IMM
            target = operand.imm
    return target


def bl_sites(data: bytes, target: int) -> list[int]:
    """Every BL in __TEXT whose destination is [target].

    Scanning rather than trusting the call graph keeps this honest: an indirect call through a
    vtable would still be invisible, but a plain duplicated `bl` cannot hide.
    """
    sites = []
    span = min(len(data), TEXT_SPAN)
    for offset in range(0, span - 4, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if (word & 0xFC000000) != 0x94000000:
            continue
        imm = word & 0x03FFFFFF
        if imm & 0x02000000:
            imm -= 0x04000000
        if TEXT_BASE + offset + imm * 4 == target:
            sites.append(TEXT_BASE + offset)
    return sites


def descriptor_entries(data: bytes, address: int, count: int) -> list[tuple[int, int, int]]:
    base = address - TEXT_BASE
    return [struct.unpack_from("<III", data, base + i * 12) for i in range(count)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=BINARY)
    parser.add_argument("--functions", type=Path, default=FUNCTIONS)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if not args.binary.is_file():
        print(f"SKIP accessoryd not extracted at {args.binary}")
        print("     check out the firmware submodule, or pass --binary")
        return 0

    data = args.binary.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    say = (lambda *a: None) if args.quiet else print

    say(f"binary   {args.binary}")
    say(f"sha256   {digest}")
    check(len(data) >= TEXT_SPAN, f"truncated: {len(data)} bytes, __TEXT alone is {TEXT_SPAN}")
    check(digest == EXPECTED_SHA256,
          f"sha256 differs from the 24A446 baseline recorded in 91 ({EXPECTED_SHA256}); "
          "re-derive the addresses before trusting any conclusion here")

    try:
        import capstone
    except ImportError:
        print("SKIP capstone is not installed (pip install capstone==5.0.7)")
        return 0
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True

    sender = disasm(data, md, SENDER, SENDER_END)
    starter = disasm(data, md, START_FEATURE, START_FEATURE_END)

    # 1. The send helper is called exactly once in the sender, and nothing loops back to it.
    sends = [i for i in sender if i.mnemonic == "bl" and imm_target(i) == SEND_HELPER]
    checks = [i for i in sender if i.mnemonic == "bl" and imm_target(i) == GATE_HELPER]
    inits = [i for i in sender if i.mnemonic == "bl" and imm_target(i) == INIT_HELPER]
    say(f"sender   {len(sender)} insns, gate={len(checks)} init={len(inits)} send={len(sends)}")
    check(len(checks) == 1, f"expected 1 required-message gate, found {len(checks)}")
    check(len(inits) == 1, f"expected 1 _iAP2MsgInit, found {len(inits)}")
    check(len(sends) == 1, f"expected exactly 1 send, found {len(sends)} — the once-only claim is gone")

    if sends:
        # Only *backward* branches matter. This function legitimately jumps forward to its
        # epilogue from three places (null session, gate failed, after logging); those are exits,
        # not loops. A resend would have to jump backwards into the construct-then-send block.
        last_init = inits[-1].address if inits else SENDER
        back_edges = [
            i for i in sender
            if i.mnemonic in ("b", "cbz", "cbnz", "tbz", "tbnz")
            and imm_target(i) is not None
            and last_init <= imm_target(i) < i.address
        ]
        say(f"back-edges into the send block: {[hex(i.address) for i in back_edges]}")
        check(not back_edges,
              "a branch jumps back into the send block; the firmware no longer sends once")

    # 2. The only way in is startFeatureFromDevice, guarded by feature 22.
    callers = bl_sites(data, SENDER)
    say(f"call sites to 0x{SENDER:x}: {[hex(c) for c in callers]}")
    check(callers == [0x100170D58],
          f"expected the single call site 0x100170d58, got {[hex(c) for c in callers]}")

    feature_ids = [i for i in starter if i.mnemonic == "mov" and i.op_str.startswith("w1, #0x16")]
    say(f"feature id loaded before getFeature: {[hex(i.address) for i in feature_ids]}")
    check(bool(feature_ids), "feature 22 (0x16) is no longer the argument to _iap2_feature_getFeature")

    # 3. The gate group is {5702 we send, 5703 we receive}.
    entries = descriptor_entries(data, DESCRIPTOR, 2)
    say("required group: " + ", ".join(
        f"0x{i:04x}(dir={d},flag={f})" for i, d, f in entries))
    check([e[0] for e in entries] == [0x5702, 0x5703],
          f"required group is no longer 5702/5703: {[hex(e[0]) for e in entries]}")
    check([e[1] for e in entries] == [1, 0],
          "direction fields changed: 5702 should be phone->car (1), 5703 car->phone (0)")

    if args.functions.is_file():
        index = {int(f["address"], 16): f["name"] for f in
                 json.loads(args.functions.read_text(encoding="utf-8"))}
        for address, label in ((SENDER, "sender"), (START_FEATURE, "start"), (SEND_HELPER, "send"),
                               (GATE_HELPER, "gate"), (INIT_HELPER, "init"), (FEATURE_GET, "getFeature")):
            say(f"  {address:#x} {label:10} {index.get(address, '<missing>')}")
            check(address in index, f"{label} at {address:#x} is not a known function start")

    if failures:
        print()
        for message in failures:
            print(f"FAIL {message}")
        return 1
    say("PASS the firmware still sends 0x5702 once, from feature 22 start, behind the 5702/5703 group")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
