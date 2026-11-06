#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 / 反查 CFString 槽位 (__DATA_CONST / __AUTH_CONST 里的 CFString 常量)。

用法:
    python3 tools/cfstr.py <image> <slot-hex> [slot-hex ...]      # 读槽位
    python3 tools/cfstr.py <image> --range <start-hex> <count>     # 连续槽位(步长 0x20)
    python3 tools/cfstr.py <image> --find <substring>              # 反查: 哪些槽位指向该字符串

CFString 布局 (64bit, 步长 0x20):
    +0x00 isa
    +0x08 info/flags
    +0x10 char* (tagged pointer: 0x00200000_XXXXXXXXXX)
    +0x18 length
tagged pointer 解码: 字符串地址 = 0x180000000 + (ptr & 0x0000FFFFFFFFFFFF)
"""
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "source", "metadata")
SRC = os.path.join(ROOT, "source", "firmware")
PTR_BASE = 0x180000000


def load(img):
    segs = json.load(open(os.path.join(MD, img, "segments.json"), encoding="utf-8"))
    blob = open(os.path.join(SRC, img), "rb").read()
    return segs, blob


def vm2off(segs, v):
    for s in segs:
        if s["vmaddr"] <= v < s["vmaddr"] + s["filesize"]:
            return s["fileoff"] + (v - s["vmaddr"])
    return None


def read_cstr(segs, blob, addr, maxlen=256):
    off = vm2off(segs, addr)
    if off is None:
        return None
    end = blob.find(b"\x00", off, off + maxlen)
    if end < 0:
        return None
    try:
        return blob[off:end].decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode_slot(segs, blob, slot):
    off = vm2off(segs, slot)
    if off is None:
        return None
    raw = blob[off:off + 32]
    if len(raw) < 32:
        return None
    ptr, length = struct.unpack_from("<QQ", raw, 16)
    addr = PTR_BASE + (ptr & 0x0000FFFFFFFFFFFF)
    s = read_cstr(segs, blob, addr)
    if s is None:
        # 无法映射 -> 内联小字符串, 内容跟在 CFString 头之后
        data = raw[32:32 + length]
        try:
            return data.decode("utf-8"), length, "inline"
        except UnicodeDecodeError:
            return None, length, "unmapped@0x%x" % addr
    return s, length, "0x%x" % addr


def cmd_read(segs, blob, args):
    if args[0] == "--range":
        start, count = int(args[1], 16), int(args[2])
        for i in range(count):
            slot = start + i * 0x20
            r = decode_slot(segs, blob, slot)
            if r is None:
                print("0x%x  <unreadable>" % slot)
                continue
            s, length, kind = r
            print("0x%x  len=%-4s %-30r  %s" % (slot, length, s, kind))
    else:
        for a in args:
            slot = int(a, 16)
            r = decode_slot(segs, blob, slot)
            if r is None:
                print("0x%x  <unreadable>" % slot)
                continue
            s, length, kind = r
            print("0x%x  len=%-4s %-30r  %s" % (slot, length, s, kind))


def cmd_find(segs, blob, needle):
    """扫描所有可映射段, 找出内容匹配 needle 的 CFString 槽位。"""
    hits = []
    for s in segs:
        if s["segname"] in ("__LINKEDIT",):
            continue
        off, size = s["fileoff"], s["filesize"]
        for i in range(0, size - 32, 0x20):
            raw = blob[off + i:off + i + 32]
            if len(raw) < 32:
                continue
            ptr, length = struct.unpack_from("<QQ", raw, 16)
            if length == 0 or length > 200:
                continue
            addr = PTR_BASE + (ptr & 0x0000FFFFFFFFFFFF)
            txt = read_cstr(segs, blob, addr)
            if txt is None:
                continue
            if needle in txt:
                hits.append((s["vmaddr"] + i, txt, length, addr))
    for slot, txt, length, addr in hits:
        print("0x%x  len=%-4d %-32r  str@0x%x" % (slot, length, txt, addr))


def build_index(segs, blob):
    """返回 {slot_addr: (name, length)} —— 全部可识别的 CFString 槽位。"""
    idx = {}
    for s in segs:
        if s["segname"] == "__LINKEDIT":
            continue
        off, size = s["fileoff"], s["filesize"]
        for i in range(0, size - 32, 0x20):
            raw = blob[off + i:off + i + 32]
            if len(raw) < 32:
                continue
            ptr, length = struct.unpack_from("<QQ", raw, 16)
            if length == 0 or length > 200:
                continue
            addr = PTR_BASE + (ptr & 0x0000FFFFFFFFFFFF)
            txt = read_cstr(segs, blob, addr)
            if txt is None:
                continue
            if not all(32 <= ord(c) < 127 for c in txt):
                continue
            idx[s["vmaddr"] + i] = (txt, length)
    return idx


def cmd_index(segs, blob, args):
    idx = build_index(segs, blob)
    if args and args[0] == "--all":
        for slot in sorted(idx):
            name, length = idx[slot]
            print("0x%x  len=%-4d %r" % (slot, length, name))
        return
    start, count = int(args[0], 16), int(args[1])
    for i in range(count):
        slot = start + i * 0x20
        name, length = idx.get(slot, ("<none>", 0))
        print("0x%x  len=%-4d %r" % (slot, length, name))


def main():
    img = sys.argv[1]
    segs, blob = load(img)
    args = sys.argv[2:]
    if args[0] == "--find":
        cmd_find(segs, blob, args[1])
    elif args[0] == "--index":
        cmd_index(segs, blob, args[1:])
    else:
        cmd_read(segs, blob, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
