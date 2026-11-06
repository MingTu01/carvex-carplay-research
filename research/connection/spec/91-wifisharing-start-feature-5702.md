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
            │     └─ 不同过 ⇒ 直接 return 0，一个字节都不发
            ├─ _iAP2MsgInit(&session->buf, 0x5702, session->link, 0xffff, 0, 0)
            └─ _iap2_sessionControl_sendOutgoingMessage(session, &session->buf)   ← 全文唯一一次
```

因此**任何形式的 5702 重发都不来自固件**。20068 之前在 `Bootstrap` 外层做的「每 5 秒再来
一轮、共 25 秒」不是固件行为的近似，是自造的节流；20069 改成单发是回到固件合同，而不是
妥协。这一点由本文的原始指令闭合（`CLOSED-STATIC`），不依赖实车。

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
`b`/`cbz` 回到 `0x100170bf4` 之后的位置——**不存在重发路径**。

### 2.2 调用点唯一

对 `__TEXT`（`0x100000000`–`0x100218000`）逐条扫描 `BL`，目标是 `0x100170bb0` 的只有一处：

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
这与本地 `requiredMessages.networkHandoff.wifiAnnouncement`
（[82](82-network-handoff-three-way-audit.md) §4 `Bootstrap.kt:399–405` 的 `routes.wifiAnnouncement`）
是同一个门，本地实现与该门一致。

## 3. 与本地实现的对照

| 项 | 固件 24A446 | 20068 及以前 | 20069（当前） |
|---|---|---|---|
| 发送次数 | 1 | 每 5 秒一轮，25 秒预算内最多 6 帧 | 1 |
| 重发来源 | 无（只在链路层做 ACK 级重传） | `Bootstrap` 外层 while 循环 | 无；链路层重传保留 |
| 沉默后的动作 | 不重发；由上层的识别/会话预算决定放弃 | 一直重试到 25 秒，然后报 `HANDOFF_FAILED` | 立即抛 `CarHoldsPreviousSessionException`，交给上层退避 |
| 前置门 | `checkRequiredMsgIDs({5702,5703})` | `routes.wifiAnnouncement` | 同左，未改 |

2026-11-06 22:12 那一轮 5702 连发 6 帧、车机随后断电重启；20069 单发之后同一辆车
78 秒自己放行、没有重启。两轮的车机侧行为差异和本文的固件结论方向一致：**重发不是
无害的重复，它是在一辆已经卡住的车机上持续加压。**

需要写清楚的是：20069 改的是「不要重发」，本文只是确认这个改动方向正确；它**没有**改变
"车机为什么不回答"。后者仍 `OPEN`。

## 4. 仍然 OPEN

| 编号 | 问题 | 关闭所需 |
|---|---|---|
| WS-OPEN-01 | 车机侧会话占用与释放（为什么对 5702 沉默、45.7 秒后才放行） | 车机固件或车机侧日志；两次实测的 45.7 秒只能作为运行观察 |
| WS-OPEN-02 | 5702 的 `_iAP2MsgInit` 第四参数 `0xffff` 与第五/第六个 0 的字段语义 | 读 `_iAP2MsgInit` 本体的参数写入，或一条带参数的实车样本 |
| WS-OPEN-03 | 必填消息组第三字段（恒为 1）的语义 | 读 `_iap2_identification_checkRequiredMsgIDs` 对该字段的使用 |
| WS-OPEN-04 | 静默之后整段会话的放弃预算，以及会不会触发 1D03 拒绝 | 识别/控制会话状态机的定时器路径；[80](80-identification-three-way-audit.md) 只到分支，没有时间预算 |
| WS-OPEN-05 | 链路层重传（`IapLink`）与固件 `_sendOutgoingMessage` 的重传语义是否等价 | 读 `_sendOutgoingMessage` 的 ACK/重传状态机 |

## 5. 复现方式

原始二进制的入库位置是固件子模块 `iamr0s/carvex-ios-firmware`：

```text
extracted/24A446/components/24A446__iPhone18,1/root/System/Library/PrivateFrameworks/
  CoreAccessories.framework/Support/accessoryd
```

`24A446` 的 `__TEXT` 段 `vmaddr=0x100000000`、`fileoff=0`，所以文件偏移等于
`地址 - 0x100000000`；函数边界取自 `analysis/24A446/accessoryd-functions.json`
（11599 项）。本文所有地址是该文件里的静态、未加 ASLR slide 的虚拟地址。

复核脚本：`research/connection/tools/inspect_wifisharing_start_feature.py`。
