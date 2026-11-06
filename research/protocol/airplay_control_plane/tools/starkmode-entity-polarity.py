#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StarkMode entity 极性裁决: 从固件原始字节推导 wire 1/2 的语义。

背景
----
AirPlaySender (iOS 侧固件) 里有两套 entity 数值空间, 容易混淆:
  * struct 空间: APStarkModeCreateDictionaryRepresentation 的输入, 名字由
    APStarkModeChangeRequestToString 给出 -> 0='N/A', 1='Car', 2='iOS'
  * wire  空间: 真正出现在 modesChanged 字典里的 "entity"/"permanentEntity" 数值

写侧 (struct -> wire) 做了 1<->2 互换, 所以两套空间的取值含义是相反的。
判断 wire 语义必须用"读侧"证据, 不能用打印映射直接套。

本脚本对两处读侧代码做符号化求值, 输出裁决表。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def csel(xn, xm, cond):
    """ARM64 CSEL: cond ? xn : xm"""
    return xn if cond else xm


def cset(cond):
    """ARM64 CSET: cond ? 1 : 0"""
    return 1 if cond else 0


def write_side(value):
    """APStarkModeCreateDictionaryRepresentation (0x251afa798) 的 struct->wire 转换。

    原始指令 (每处资源/appState 都重复一次):
        cmp   w22, #2
        cset  w8, eq          ; w8 = (v == 2)
        cmp   w22, #1
        mov   w9, #2
        csel  x22, x9, x8, eq ; v==1 ? 2 : (v==2 ? 1 : 0)
    """
    w8 = cset(value == 2)
    return csel(2, w8, value == 1)


def read_side(value):
    """APStarkModeInitialOwnerRequestMakeFromDictionary (0x251afabc8) 的 wire->struct 转换。

    原始指令:
        cmp   w0, #2
        cset  w8, eq          ; w8 = (v == 2)
        cmp   w0, #1
        mov   w9, #2
        csel  w8, w9, w8, eq  ; v==1 ? 2 : (v==2 ? 1 : 0)
    """
    w8 = cset(value == 2)
    return csel(2, w8, value == 1)


def struct_name(value):
    """APStarkModeChangeRequestToString / SendCommand.cold.3 的名字表 (struct 空间)。

    三处独立位置共用同一张表:
      ldr w8,[x0]; cmp #2 -> 'iOS'; cmp #1 -> 'Car'; cmp #0 -> 'N/A'
    """
    return {0: "N/A", 1: "Car", 2: "iOS"}.get(value, "<invalid>")


def main():
    print("=== struct 空间 (写侧输入, ToString 给出名字) ===")
    for v in (0, 1, 2):
        print("  struct %d = %s" % (v, struct_name(v)))

    print()
    print("=== 写侧 struct->wire ===")
    for v in (0, 1, 2):
        print("  struct %d (%-4s) -> wire %d" % (v, struct_name(v), write_side(v)))

    print()
    print("=== 读侧 wire->struct (与写侧应互逆) ===")
    for v in (0, 1, 2):
        print("  wire %d -> struct %d" % (v, read_side(v)))

    print()
    print("=== 互逆性校验 ===")
    ok = True
    for v in (0, 1, 2):
        got = read_side(write_side(v))
        flag = "OK" if got == v else "MISMATCH"
        if got != v:
            ok = False
        print("  struct %d -> wire %d -> struct %d  %s" % (v, write_side(v), got, flag))

    print()
    print("=== 裁决: wire entity 语义 ===")
    for wire in (0, 1, 2):
        print("  wire %d -> struct %d = %s" % (wire, read_side(wire), struct_name(read_side(wire))))

    if not ok:
        print()
        print("!! 写读两侧不互逆, 说明反汇编推导有误, 禁止据此改代码。")
        return 1
    print()
    print("结论: wire 1 = iOS(手机), wire 2 = Car(车机)。")
    print("      我们发 entity=1 表示手机持有资源, 极性正确。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
