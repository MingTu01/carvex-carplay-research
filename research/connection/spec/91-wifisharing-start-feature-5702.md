# 91 — WiFiSharing 启动时的一次性 0x5702

日期：2026-11-06。基线仍是 `iPhone18,1` / iOS 27.0.1 / `24A446`。本文把「手机发 5702、
车机不回 5703」这条链路的**发送侧**闭合到原始指令；车机侧为什么沉默不在本文范围内。

## 1. 结论与证据边界

`0x5702` 在固件里**每个 iAP 会话只发一次**，而且只在 WiFiSharing（feature 22）从车上被
启动的那一刻发。发送函数里没有循环、没有定时器、没有重发预算：

```text
_iap2_wifisharing__startFeatureFromDevice   @0x100170cb8
  └─ _iap2_feature_getFeature(session, 22)
       └─ _iap2_wifisharing_RequestAccessoryWiFiConfigurationInformation  @0x100170bb0
            ├─ _iap2_identification_checkRequiredMsgIDs(session, 0x1001b40c0, 2, &flag)
            │     └─ 组不成立 ⇒ 直接 return 0，一个字节都不发
            ├─ _iAP2MsgInit(&session->buf, 0x5702, session->link, 0xffff, 0, 0)
            └─ _iap2_sessionControl_sendOutgoingMessage(session, &session->buf)   ← 全文唯一一次
```

因此**任何形式的 5702 重发都不来自固件**。这一条的用处是给手机侧定一个明确的合同：沉默
不是「还没发够」，而是「已经发过，等待不是靠再发一次能解决的」。手机侧任何「每 N 秒再来
一轮」的循环都不是固件行为的近似，而是自造的节流。

边界：

- 本文**不**证明车机为什么对 5702 沉默。车机侧的会话占用只有车机固件或车机日志能答，
  我们两边都没有。
- 本文**不**证明静默之后固件什么时候放弃整段会话。那个预算在识别/控制会话的上层
  （见 [17](17-identification-feature-message-branches.md) FM-22/24 与
  [80](80-identification-three-way-audit.md)），不在发送函数里。
- 本文**不**给出 5702 的 payload。`_iAP2MsgInit` 的第四参数是 `0xffff`，第五、第六是 0，
  说明这条消息在构造时是空参数集；`0xffff` 的字段语义未读，标 `OPEN`。

## 2. 固件合同（逐指令）

### 2.1 发送函数

`_iap2_wifisharing_RequestAccessoryWiFiConfigurationInformation` @ `0x100170bb0`，
长 `0x8c`（下一条函数 `__createFeature` @ `0x100170c3c`）。全文 35 条指令：

| 地址 | 指令 | 作用 |
|---|---|---|
| `0x100170bb0` | `pacibsp` | 函数入口，带指针认证 |
| `0x100170bc4` | `mov x19, x0` | 保存会话指针 |
| `0x100170bc8` | `cbz x0, #0x100170c28` | 空会话直接返回 0，不发送 |
| `0x100170bd0` | `adrp x1, #0x1001b4000` | 取必填消息组基址 |
| `0x100170bd4` | `add x1, x1, #0xc0` | `x1 = 0x1001b40c0` |
| `0x100170bd8` | `add x3, sp, #0xf` | 输出标志位地址 |
| `0x100170be0` | `mov w2, #2` | 组内 2 项 |
| `0x100170be4` | `bl #0x100050c2c` | `_iap2_identification_checkRequiredMsgIDs` |
| `0x100170be8` | `cbz w0, #0x100170c24` | 组不成立 ⇒ 返回 0，**不发 5702** |
| `0x100170bf4` | `mov w1, #0x5702` | 消息 ID |
| `0x100170bf8` | `mov w3, #0xffff` | `_iAP2MsgInit` 第四参数 |
| `0x100170c04` | `bl #0x100003424` | `_iAP2MsgInit` |
| `0x100170c10` | `bl #0x100005130` | `_iap2_sessionControl_sendOutgoingMessage` |
| `0x100170c18` | `mov w0, #0x8ca8` | 诊断码 |
| `0x100170c38` | `retab` | 返回 |

关键点：`0x100003424`（构造）与 `0x100005130`（发送）各只出现一次，函数里没有任何
**向后**的 `b`/`cbz` 回到 `0x100170bf4` 之后的位置。三处前向跳转（`0x100170bc8`、
`0x100170be8`、`0x100170c20`）都是出口，不是循环：**不存在重发路径**。

### 2.2 调用点唯一

对 `__TEXT`（`0x100000000`–`0x100218000`）逐条解码 `BL` 并按立即数算出目标，指向
`0x100170bb0` 的只有一处：

```text
BL @0x100170d58   （位于 __startFeatureFromDevice 内）
```

`_iap2_wifisharing__startFeatureFromDevice` @ `0x100170cb8`，长 `0xc8`：

| 地址 | 指令 | 作用 |
|---|---|---|
| `0x100170d44` | `mov x0, x19` | 会话指针 |
| `0x100170d48` | `mov w1, #0x16` | feature **22**（WiFiSharing） |
| `0x100170d4c` | `bl #0x100003360` | `_iap2_feature_getFeature` |
| `0x100170d50` | `cbz x0, #0x100170d60` | 车上没起这个 feature ⇒ 不发 |
| `0x100170d58` | `bl #0x100170bb0` | 发 5702 |
| `0x100170d5c` | `mov w0, #1` | 返回 1 |

即：**5702 是 feature 22 的启动动作，一个会话一次。** 想让它再发，只能让这个 feature 重新
启动——而 feature 的启动挂在识别/会话建立上，会话没结束就不会重来。这正是「车机不回答时
手机端看起来什么都不会再发生」的结构性原因，而不是某种重试逻辑失灵。

扫描只看得见直接 `BL`；经 vtable 的间接调用对它不可见。本文没有穷举 vtable，这一层保留
在下面的 `OPEN` 里，不当作已排除。

### 2.3 必填消息组

`0x1001b40c0` 起 24 字节，两项，每项 12 字节（`u32 id, u32 方向, u32 标志`）：

```text
02 57 00 00 | 01 00 00 00 | 01 00 00 00     0x5702, 1, 1
03 57 00 00 | 00 00 00 00 | 01 00 00 00     0x5703, 0, 1
```

方向字段的取值靠邻组交叉确认，不是猜：`0x1001b40a8` 起是 5700/5701 组

```text
00 57 00 00 | 00 00 00 00 | 01 00 00 00     0x5700, 0, 1
01 57 00 00 | 01 00 00 00 | 01 00 00 00     0x5701, 1, 1
```

而 `0x10017020c` 的 `_iap2_wifisharing_RequestWiFiInformation` 在 `0x10017024c`–`0x100170254`
把入参消息 ID 与 `0x5700` 比较，说明 **5700 是手机收、5701 是手机发**。于是：

- `1` = 手机侧发出（5701、5702）
- `0` = 车机侧发出（5700、5703）

第三字段在两组的四项上都是 `1`，语义未读，标 `OPEN`；不外推成「必需」或「次数」。

结论（`INFERRED`，两组一致）：发 5702 的前置条件就是**车机声明过它收 5702、且发 5703**。

## 3. 与 `android/` 当前实现的对照

对照对象是子模块 `iamr0s/carvex-android` 的 `aa7b7500`，不是任何本地分支。

| 项 | 固件 24A446 | 当前实现 | 判断 |
|---|---|---|---|
| 发送次数 | 1 | 1，`Bootstrap.kt:445–446` `send(0x5702)` 只出现一次 | 一致 |
| 前置门 | `checkRequiredMsgIDs(session, {5702 收? 发, 5703})` | `IapIdentificationValidation.kt:29` `wifiHandoff = listOf(Rule(0x5702,1), Rule(0x5703,0))`，`group()` 要求两个方向都已声明；只有 `COMPLETE` 才把 22 放进 `validatedMessageFeatures` | 一致，连元组内容都相同 |
| 重发来源 | 无（只在链路层做 ACK 级重传） | 无 | 一致 |
| 沉默之后的动作 | 不重发；预算在上层，未读 | `ANNOUNCEMENT_WAIT_MS = 30_000`（`Bootstrap.kt:112`）到期后以 `HANDOFF_FAILED` 放弃（`Bootstrap.kt:477`、`498`） | **这个 30 秒没有固件对应物** |

也就是说：**「只发一次」在手机侧本来就已经成立，本文不是要求改代码，而是把这个取值从
「看起来这样写比较稳」升级成「固件就是这么规定，改动它会破坏合同」。**

### 3.1 30 秒的等待预算没有固件对应物

`ANNOUNCEMENT_WAIT_MS` 是手机侧自己的取值。发送函数里没有任何超时（§2.1），`OPEN` 的
WS-OPEN-04 也还没读出上层那条预算到底多长、失败后走哪条错误分支。因此：

- 不能据本文声称 30 秒「错了」——没有证据说明固件的预算更短或更长；
- 也不能据本文声称 30 秒「对」——它至今只是一个本地常量，不是读出来的值；
- 本条写在这里的目的是让这个数字不再隐形：它是 `OPEN`，不是 `CONFIRMED`。

按 [`AGENT.md`](../../../AGENT.md) §4，这属于「盲试固定延迟」的边缘，需要靠 WS-OPEN-04
闭合，而不是继续调数字。

## 4. 一次关于重发的分支试验（不属于本仓库）

本节记录的是本仓库之外、某个工作分支上做过的一次试验，写出来是因为它直接对应 §1 的结论；
它**不是**对本仓库当前代码的描述，也不能当成实车通用结论。

- 该分支曾在 `Bootstrap` 外层加过「每 5 秒再发一轮、25 秒预算内最多 6 帧」。2026-11-06
  22:12 的一轮里 5702 连发 6 帧，同一辆车随后断电重启。
- 撤回这段循环、恢复单发之后，同一辆车在 78 秒时自行放行，没有重启。

两次都是 `OBSERVED`，单车辆、单晚、非对照实验，样本量 1，不能外推。能说的只有一句：
**重发不是无害的重复**，它是在一辆已经卡住的车机上持续加压；这也和 §2 的静态结论同向。
车机为什么沉默、为什么 78 秒后放行，仍归 WS-OPEN-01，本文不解。

## 5. 仍然 OPEN

| 编号 | 问题 | 关闭所需 |
|---|---|---|
| WS-OPEN-01 | 车机侧会话占用与释放（为什么对 5702 沉默） | 车机固件或车机侧日志；运行侧的观察见 [92](92-car-holds-previous-session.md)，但单车辆单晚，不构成机制 |
| WS-OPEN-02 | 5702 的 `_iAP2MsgInit` 第四参数 `0xffff` 与第五/第六个 0 的字段语义 | 读 `_iAP2MsgInit` 本体的参数写入，或一条带参数的实车样本 |
| WS-OPEN-03 | 必填消息组第三字段（恒为 1）的语义 | 读 `_iap2_identification_checkRequiredMsgIDs` 对该字段的使用 |
| WS-OPEN-04 | 静默之后整段会话的放弃预算，以及会不会触发 1D03 拒绝 | 识别/控制会话状态机的定时器路径；[80](80-identification-three-way-audit.md) 只到分支，没有时间预算 |
| WS-OPEN-05 | 链路层重传（`IapLink`）与固件 `_sendOutgoingMessage` 的重传语义是否等价 | 读 `_sendOutgoingMessage` 的 ACK/重传状态机 |
| WS-OPEN-06 | 是否存在经 vtable 的间接调用也能到达 `0x100170bb0` | 枚举指向该地址的函数指针；本文只排除了直接 `BL` |

## 6. 复现方式

原始二进制的入库位置是固件子模块 `iamr0s/carvex-ios-firmware`：

```text
extracted/24A446/components/24A446__iPhone18,1/root/System/Library/PrivateFrameworks/
  CoreAccessories.framework/Support/accessoryd
```

`24A446` 的 `__TEXT` 段 `vmaddr=0x100000000`、`fileoff=0`，所以文件偏移等于
`地址 - 0x100000000`；函数边界取自 `analysis/24A446/accessoryd-functions.json`
（11599 项）。本文所有地址是该文件里的静态、未加 ASLR slide 的虚拟地址。

复核脚本：`research/connection/tools/inspect_wifisharing_start_feature.py`。它从字节重新
推导本文的三条断言（单次发送、唯一调用点 + feature 22、必填组方向），任一不成立就以非零
退出；固件子模块没检出时输出 `SKIP` 并返回 0，不当作通过。

```powershell
python -B research/connection/tools/inspect_wifisharing_start_feature.py
python -B research/connection/tools/inspect_wifisharing_start_feature.py --binary <accessoryd 路径>
```

脚本同时校验 `accessoryd` 的 sha256 与函数索引的 sha256；重新提取导致任一变化时，本文所有
地址都要重新推导，脚本会先报出来。
