#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AirPlaySender / accessoryd 镜像的 ADRP 交叉引用与函数反汇编。

用法:
    python3 tools/xref.py <image> <target-hex>          # 谁引用了这个地址
    python3 tools/xref.py <image> --dump <addr> [n]     # 反汇编 n 条指令
    python3 tools/xref.py <image> --strings <substring>  # 找字符串并列出引用者
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "source", "metadata")
SRC = os.path.join(ROOT, "source", "firmware")

try:
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
except ImportError:
    raise SystemExit("capstone required: pip install capstone")

WINDOW = 12  # ADRP 之后最多看多少条指令


def load(img):
    segs = json.load(open(os.path.join(MD, img, "segments.json"), encoding="utf-8"))
    blob = open(os.path.join(SRC, img), "rb").read()
    text = next(s for s in segs if s["segname"] == "__TEXT")
    return segs, blob, text


def vm2off(segs, v):
    for s in segs:
        if s["vmaddr"] <= v < s["vmaddr"] + s["filesize"]:
            return s["fileoff"] + (v - s["vmaddr"])
    return None


def symbols(img):
    out = []
    p = os.path.join(MD, img, "symbols.json")
    if os.path.exists(p):
        for x in json.load(open(p, encoding="utf-8")):
            out.append((x["addr"], x["name"]))
    out.sort()
    return out


def owner(syms, addr):
    lo, hi, best = 0, len(syms) - 1, (0, "?")
    while lo <= hi:
        mid = (lo + hi) // 2
        if syms[mid][0] <= addr:
            best = syms[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def adrp_page(word, pc):
    immlo = (word >> 29) & 3
    immhi = (word >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= 1 << 21
    return ((pc >> 12) << 12) + (imm << 12)


def scan_refs(img, target):
    """返回 [(指令地址, 该指令文本)]：所有把 ADRP 页 + 立即数解析成 target 的引用。"""
    segs, blob, text = load(img)
    body = blob[text["fileoff"]: text["fileoff"] + text["filesize"]]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    base = text["vmaddr"]
    words = []
    for i in range(0, len(body) - 4, 4):
        words.append(int.from_bytes(body[i:i + 4], "little"))
    hits = []
    for idx, word in enumerate(words):
        if (word & 0x9F000000) != 0x90000000:  # ADRP
            continue
        pc = base + idx * 4
        page = adrp_page(word, pc)
        # ADD (imm) / LDR (imm) / SUB (imm)
        for k in range(1, WINDOW):
            j = idx + k
            if j >= len(words):
                break
            w2 = words[j]
            val = None
            if (w2 & 0xFF800000) == 0x91000000:
                imm12 = (w2 >> 10) & 0xFFF
                if (w2 >> 22) & 1:
                    imm12 <<= 12
                val = page + imm12
            elif (w2 & 0xFFC00000) == 0xF9400000:
                val = page + ((w2 >> 10) & 0xFFF) * 8
            elif (w2 & 0xFF800000) == 0xD1000000:
                val = page - ((w2 >> 10) & 0xFFF)
            if val == target:
                hits.append((pc, j))
                break
    return hits, body, base, words


def dump(img, addr, count):
    segs, blob, text = load(img)
    off = vm2off(segs, addr)
    if off is None:
        print("unmapped 0x%x" % addr)
        return
    chunk = blob[off: off + 4 * count]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    # CFString 名字标注
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from cfstr import build_index
        cf_index = build_index(segs, blob)
    except Exception:
        cf_index = {}
    for ins in md.disasm(chunk, addr):
        note = ""
        m = ins.op_str
        # adrp xN, #page  -> 记录 page
        if ins.mnemonic == "adrp" and "#" in m:
            try:
                page = int(m.split("#")[1].strip(), 16)
            except ValueError:
                page = None
            if page is not None:
                note = "page=0x%x" % page
        if ins.mnemonic in ("add", "ldr") and "#" in m:
            try:
                imm = int(m.split("#")[1].split("]")[0].strip(), 16)
            except ValueError:
                imm = None
            if imm is not None:
                cand = imm
                if cand in cf_index:
                    note = "CFString '%s'" % cf_index[cand][0]
        print("  0x%x  %-10s %-40s %s" % (ins.address, ins.mnemonic, ins.op_str, note))


def main():
    img = sys.argv[1]
    syms = symbols(img)
    if sys.argv[2] == "--dump":
        addr = int(sys.argv[3], 16)
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 40
        dump(img, addr, n)
        return 0
    if sys.argv[2] == "--strings":
        segs, blob, text = load(img)
        needle = sys.argv[3].encode()
        idx = -1
        while True:
            idx = blob.find(needle, idx + 1)
            if idx < 0:
                break
            vm = None
            for s in segs:
                if s["fileoff"] <= idx < s["fileoff"] + s["filesize"]:
                    vm = s["vmaddr"] + (idx - s["fileoff"])
                    break
            if vm is None:
                continue
            hits, _, _, _ = scan_refs(img, vm)
            owners = sorted({owner(syms, pc)[1] for pc, _ in hits})
            print("0x%x  %r  refs=%d  %s" % (vm, needle.decode(), len(hits), owners[:6]))
        return 0
    target = int(sys.argv[2], 16)
    hits, _, _, _ = scan_refs(img, target)
    print("image=%s target=0x%x hits=%d" % (img, target, len(hits)))
    seen = set()
    for pc, j in hits:
        a, name = owner(syms, pc)
        if name in seen:
            continue
        seen.add(name)
        print("  0x%x  +0x%x  [%s @0x%x]" % (pc, (j - (pc - text_vm(img))) * 4 if False else 0, name, a))
    return 0


def text_vm(img):
    segs, _, text = load(img)
    return text["vmaddr"]


if __name__ == "__main__":
    raise SystemExit(main())
