# CarVeX CarPlay 接入 · 交接文档

> 面向：接手这个任务的 Agent。
> 读完之后你应该能回答三个问题：**现在做到哪了、还差什么、下一步具体敲什么命令。**
> 所有结论都带 `文件:行号` 或日志原文，可以自己 grep 复核，不要凭本文档的口气相信。

最后更新：2026-11-02 14:42（北京时间）
本仓库已 fork 到 `MingTu01` 名下，本地改动已提交并推送；上游仅作参考，**不要向 upstream 推送**（无权限）。

---

## 0. 一分钟摘要

| 项目 | 状态 |
|---|---|
| **本仓库（fork）** | https://github.com/MingTu01/carvex-carplay-research |
| **代码子模块（fork）** | https://github.com/MingTu01/carvex-android （`android/`） |
| **固件证据库（fork）** | https://github.com/MingTu01/carvex-ios-firmware （`firmware/`，**几十 GB，只用 blobless 克隆**） |
| 上游原始仓库 | https://github.com/iamr0s/carvex-carplay-research · https://github.com/iamr0s/carvex-android · https://github.com/iamr0s/carvex-ios-firmware |
| 当前工作副本 | `C:\Users\Administrator\WorkBuddy\carvex`（可换任意路径，文档不依赖它） |
| 当前 HEAD | 父仓库 `main`；`android` 子模块 `main` @ `21765d7`（4 个本地提交，已推送） |
| 构建状态 | ✅ 能出包，`:app:assembleXiaomiDebug` 成功 |
| 测试状态 | ✅ `:protocol-carplay:testDebugUnitTest`、`:host-carlife-mixing:test` 全绿 |
| 产品状态 | ⚠️ **软接收端（winplay）端到端跑通；真车（mingtu）从未验证** |

**一句话结论**：真车原先在"安全选路"这一步被代码按设计判死（`SECURITY_POLICY_UNRESOLVED`）。现在这一层改成了回落到 MFi/SAP 认证，逻辑通顺、能编译、能测试，**但一次都没有在真车上跑过**。真车能不能出画面，取决于车机是否提供 `/auth-setup` 端点——这是当前唯一的未知大关。

**下一个 Agent 的第一件事**：装包（现成产物 `android/app/build/outputs/apk/xiaomi/debug/CarVex_xiaomi_debug_20001.apk`；重新构建会变成 `…_20012.apk`，见 §1.2 版本号规则），连真车 `mingtu`，抓日志，按 §6.2 的判据看四行。**在拿到真机日志之前，不要改任何协议代码。**

---

## 1. 仓库与环境

### 1.1 仓库关系

```
carvex-carplay-research/          ← 父仓库：只有研究文档（research/）
├── android/                      ← 子模块：真正的 App 代码（Kotlin）
│   ├── app/                      ← UI、Flavor、APK 打包
│   ├── protocol-carplay/         ← CarPlay/AirPlay 协议栈（**改动主战场**）
│   ├── bridge/                   ← SessionController：会话编排、宿主（CarWith）交互
│   ├── host-api/                 ← CastHost 契约
│   ├── host-carlife-mixing/      ← CarWith / CarLife 适配实现
│   └── core/                     ← 共享状态
├── firmware/                     ← 子模块：iOS 固件逆向证据（大，按需取）
└── research/                     ← 协议研究文档（结论的依据）
```

克隆（fork 版本，已验证可用）：

```bash
git clone --depth 1 https://github.com/MingTu01/carvex-carplay-research.git carvex
cd carvex
git remote add upstream https://github.com/iamr0s/carvex-carplay-research.git
git submodule update --init --depth 1 android   # .gitmodules 已指向 MingTu01 的 fork
# firmware 不要这样拉，见 1.3
```

子模块同样是 fork 的：`https://github.com/MingTu01/carvex-android.git`。
每个仓库都保留 `upstream` 指向 `iamr0s`，用于对比上游更新：`git fetch upstream && git log --oneline HEAD..upstream/main`。
**本文档里所有 `文件:行号` 都以 fork 的 `android` main @ `21765d7` 为准**；如果上游之后有改动，行号可能偏移，用函数名或日志字符串 grep 定位更稳。

### 1.2 构建环境（换机器必读，不绑定某台电脑）

**前置只有三件套**，都在仓库外，换机要自己装：

| 依赖 | 要求 | 备注 |
|---|---|---|
| JDK | **必须 17** | Gradle toolchain 硬要求；21/25 会报 `Cannot find a Java installation … languageVersion=17`。装了多版本时用 `JAVA_HOME` 临时指定，不要改全局 |
| Android SDK | `platforms;android-37.0` + `build-tools;36.0.0`（或 37.0.0）+ `platform-tools` | 包名**必须带 `.0`**：`platforms;android-37` 不存在，`sdkmanager` 会直接说不支持 |
| Gradle | 不需要装 | 仓库自带 Wrapper，`gradlew.bat` 会自己下 |

**签名不用配**：`.signing/keystore.properties` 和 `.signing/release.jks` 都已被仓库跟踪（上游 `40a3b0d` 起 CI 也用它）。所以 debug / release 都能直接签名，新机器**不需要**准备 keystore，也不要覆盖这两个文件。

**一次性安装（Windows + cmdline-tools）**：

```bash
# 1) 下载 commandlinetools-win-*_latest.zip，解压成 <SDK>/cmdline-tools/latest
# 2) 接受许可并装包
<SDK>/cmdline-tools/latest/bin/sdkmanager.bat --sdk_root=<SDK> --licenses
<SDK>/cmdline-tools/latest/bin/sdkmanager.bat --sdk_root=<SDK> \
  "platform-tools" "platforms;android-37.0" "build-tools;36.0.0"
# 3) 在 android/ 下写 local.properties（不要提交）
#    sdk.dir=<SDK 绝对路径>，Windows 盘符冒号要转义：sdk.dir=C\:\\path\\to\\Sdk
```

**构建**（bash / Git Bash）：

```bash
cd android
export JAVA_HOME="<JDK17 绝对路径>"          # 例：C:/Java/jdk-17
./gradlew.bat :protocol-carplay:testDebugUnitTest :host-carlife-mixing:test --no-daemon --console=plain
./gradlew.bat :app:assembleXiaomiDebug --no-daemon --console=plain
```

**构建**（PowerShell）：

```powershell
$env:JAVA_HOME="C:\path\to\jdk-17"
.\gradlew.bat :app:assembleXiaomiDebug --no-daemon
```

**自检**：`./gradlew.bat -version` 的 JVM 必须是 `17.x`；再跑一次上面的两个任务，都绿才算环境就绪。

**正确的任务名**（上游已修正，别再用旧写法）：

| 用途 | 任务 | 说明 |
|---|---|---|
| 协议/宿主单测 | `:protocol-carplay:testDebugUnitTest`、`:host-carlife-mixing:test` | 与品牌无关，最快 |
| 全量单测 | `:app:testXiaomiDebugUnitTest` 等 | **每个 flavor 一个**，没有聚合任务 |
| lint | `:app:lintXiaomiRelease` 等 | **没有聚合的 `lintRelease`**，写了会在任务选择阶段报 ambiguous、什么都没跑 |
| 打包 | `:app:assembleXiaomiDebug` / `:app:assembleRelease` | 产物在 `app/build/outputs/apk/<brand>/<type>/` |

**产物命名与版本号**：`CarVex_<brand>_<buildType>_<versionName>.apk`，
`versionCode = 20000 + git rev-list --count HEAD`。
android 仓库当前 **12 个提交** → `20012`。
**浅克隆会让这个号变小**（`--depth 1` 时是 `20001`），看到版本号奇怪先查克隆深度，不要以为是构建坏了。

Flavor 与包名：`xiaomi` / `oppo` / `vivo` / `samsung` / `honor`，小米包名 `com.baidu.carlife.xiaomi`。**APK 必须与手机上已装的同 Flavor 一致**，否则签名/覆盖会出问题。

**CI**：`.github/workflows/android.yml` 会在 push main / PR / 手动触发时并行跑各 flavor 并出包。但 **fork 仓库的 Actions 默认是关闭的**（`total_count=0`），要用得去 fork 的 Actions 页手动 Enable，或本地 `workflow_dispatch`。当前没有任何一次 CI 运行记录。


### 1.3 firmware 子模块（只有目录树，没有文件内容）

当前是 blobless 克隆，**2935 个文件树节点，实际只下载过按需的几个 JSON**：

```bash
cd carvex && git clone --filter=blob:none --no-checkout https://github.com/MingTu01/carvex-ios-firmware.git firmware
cd firmware && git ls-tree -r --name-only HEAD | head
git show HEAD:analysis/vertical-feasibility/linux-first/dependencies.json   # 按需取单个文件
```

> 注意：父仓库记录的 firmware 指针是 `5630458`，而 blobless 克隆默认落在 `main` 的 `b786786`。
> **不要把 firmware 指针提交进去**（`git add firmware`），那会改掉研究结论所依据的固件版本。

⚠️ 因为不是正规 submodule init，父仓库 `git status` 可能把 `firmware` 显示成 modified，**属正常，别去"修"它**。

### 1.4 上游那 6 个提交改了什么，有没有用

本地代码曾停在 `eb9f997`（2026-10-31），上游之后又推了 6 个提交，fork 对齐后已包含它们。全部**不涉及协议、认证、音频**，对"真机能不能连上"零影响；其中有两条对换电脑开发有用。

| 提交 | 改了什么 | 对我们 |
|---|---|---|
| `40a3b0d` Use tracked signing material in CI | CI 改用仓库里已跟踪的 `.signing/`，删掉 60 行"从 secrets 还原 keystore"的逻辑；README 同步 | **有用**：签名材料本来就在仓库里，换机不用额外配，这也是为什么 `assembleXiaomiDebug` 开箱能出可安装包 |
| `34bf85c` Fix CI: artifacts dir + step summary | 先建 artifacts 目录再 `tee`；Gradle 失败写进 job summary | 仅 CI 相关 |
| `e3a3480` Fix CI task selection | lint 是 per-flavor（`lintXiaomiRelease`），没有聚合 `lintRelease`；`bash -e` 下保留失败处理。同步更正了 `AGENT.md` 的任务清单 | **有用**：照旧写法跑 lint 会在任务选择阶段直接报 ambiguous，见 §1.2 任务表 |
| `90fae45` CI matrix | 各品牌改成并行 job，产出各品牌 APK + `CarVex_all_flavors.zip` | 仅 CI 相关（耗时从串行压到并行） |
| `9434dcb` Fix matrix | GitHub matrix 的 key 大小写不敏感，品牌首字母大写改为 shell 推导 | 修上一条的 bug |
| `69802bf` README | 加开发者 QQ 群 | 无技术影响 |

> 上游 `AGENT.md` 是项目自己的开发约定（构建、任务名、协议限制），**改代码前值得先读一遍**，它比本文档更贴近上游的编码规范。


---

## 2. 当前状态总览

### 2.1 已验证（有日志/测试支撑）

| # | 事项 | 证据 |
|---|---|---|
| V-1 | 软接收端 winplay 端到端会话成立：iAP2 → Wi-Fi handoff → AirPlay → SETUP → 视频帧在流 → `/feedback` 200 | `device-log(1)`(winplay 侧) 与 `carvex-log-20261102-140732.txt` |
| V-2 | 该会话走的是 **PAIRED（HAP）**路线：`pi=36 pk=32 gate=start_ready` | 同上，诊断行 |
| V-3 | 音频在 HAP 路线**完全可用**：AAC-LC/48000/2，RTP 包正常累积，用户实测有声音 | 日志 `Audio category=1 selected type=102/media codec=AAC_LC/48000/2` |
| V-4 | 由 CarWith 发起的会话，显示权交给 CarWith 正常（拿到 `host-display 96`） | 同上 |
| V-5 | 编译 + 单测全绿 | 见 §1.2 命令 |

### 2.2 已改但**未验证**

| # | 事项 | 风险 |
|---|---|---|
| W-1 | 真车选路从"抛死"改为"SAP 回落"（见 §4.1） | 只做过静态核对，真机一次没跑 |
| W-2 | SAP 分支真的去 POST `/auth-setup`（原为空实现） | 该函数全仓零调用历史，是死代码复活 |
| W-3 | CarWith 自唤醒死锁修复（见 §4.4） | 用户后来表示"这个不重要"，优先级已降 |

### 2.3 已知缺陷 / 未知

见 §5，编号 U-1 起。

---

## 3. 真车（mingtu）失败的确切原因

这份日志：`C:\Users\Administrator\Desktop\device-log(1).txt`（23003 字节，2026-11-01 17:39，目标 `1C:50:1E:B7:68:87`，`experiment=true`）

**五步连锁，缺一不可：**

| 步 | 现象 | 证据位置 |
|---|---|---|
| ① | 车机 `_airplay._tcp` 的 TXT **只给 `features`，不给 `pk`** | 行 170 `keyPresent=false features=source=LEGACY_FLAGS bytes=8` |
| ② | `featuresLow64=0x6104040280`，置位 `7/9/18/26/32/37/38` | 行 181 |
| ③ | bit38 置位 → `directCoreUtilsPairing=true` → 代码判"该走 CU/HAP";`gate` 第 44 行要求 `publicKey.size==32`，`pk` 缺失 → 返回 null | `BootstrapSecurity.kt:44` 附近 |
| ④ | `route()` 拿到 `gate==null` → 抛 `SECURITY_POLICY_UNRESOLVED` | 行 231、235（`SecurityRouting.kt:81`） |
| ⑤ | `SecurityFailure extends IllegalArgumentException` → `SessionController` 判 terminal → **不重试，直接结束** | 日志 `outcome=failed` |

**还有第二条会拦的（即使 ③ 通过）**：`gate` 里 `sameAddress` 要求 Bonjour 地址与 iAP2 地址严格相等，而

```
行 179: control candidates=BOOTSTRAP@192.168.0.1:7000, BONJOUR@fe80::cafe:fff:fe29:36de%wlan0:7000
```

一个 IPv4、一个 IPv6 链路本地，`contentEquals` 必然 false。**所以这台车走 HAP 是结构性走不通，SAP 是唯一选择。**

**关键协议判断**：bit26 = AES-128 MFi SAP v1，说明车机就是准备走 `/auth-setup`；bit38 让代码误判成 CU 配对。这是项目自身的一处真实缺口。

---

## 4. 已经做了的改动（4 个提交，已推送到 fork）

分支 `main`，地址 https://github.com/MingTu01/carvex-android 。提交序列（在 `69802bf` 之上）：

| 提交 | 内容 | 涉及文件 |
|---|---|---|
| `c652dae` | protocol：安全选路回落 SAP + gate 具名原因 | `SecurityRouting.kt`、`BootstrapSecurity.kt`、`AirSession.kt` |
| `c13ae09` | protocol：蓝牙 SPP UUID 诊断日志 | `Bootstrap.kt` |
| `d5b7a4f` | bridge：CarWith 自唤醒 + `requestForeground()` | `SessionController.kt`、`CastHost.kt`、`CarWithHost.kt`、`VendorCastHost.kt` |
| `21765d7` | app：日志分享按钮 + 时间戳文件名 | `AndroidManifest.xml`、`LogPage.kt`、`file_paths.xml`、3 个 `strings.xml` |

复核：`git -C android log --oneline -4`，逐行看用 `git -C android show <sha>`。下面按主题拆解，行号基于该分支。

### 4.1 安全选路：拒绝 → 回落 SAP

| 文件 | 改动 |
|---|---|
| `protocol-carplay/.../core/SecurityRouting.kt:48` | `SecurityInputs` 新增 `sapFallbackAfterGate: Boolean = false`（默认关闭，安全语义不变） |
| 同文件 `:91` | `if (gate == null && i.sapFallbackAfterGate) return SecurityRoute.SAP` |
| `protocol-carplay/.../BootstrapSecurity.kt:16,33` | `securityInputs()` 透传该开关 |
| `protocol-carplay/.../AirSession.kt:479` | `val sapFallback = options.experiment && metadata.effectiveFeatureEvidence.has(26) == true` |

**为什么这样设计**：默认 `false` 保证所有既有测试和 HAP 路线的行为一字不变；只有"实验认证模式打开 + 对端置了 bit26"才启用。真车正好满足这两个条件。

### 4.2 gate 从黑盒变具名原因（纯诊断）

`protocol-carplay/.../BootstrapSecurity.kt:40-68`

```kotlin
@Volatile var lastDecision:String="not_evaluated"
fun no(reason:String):Boolean?{lastDecision=reason;return null}
```

原来 10 个前置条件全返回 `null`，上层只看到 `SECURITY_POLICY_UNRESOLVED`。现在分别记为 `pk_missing` / `pi_missing` / `address_mismatch bonjour=… iap2=…` / `peer_mismatch` / `accepted` 等。

`AirSession.kt:489` 在选路前多打一行：

```
Experimental HAP gate=<原因> pi=<长度> pk=<字节数> bonjour=<ip:port> iap2=<ip:port>
```

### 4.3 SAP 分支从空实现接通

| 位置 | 改动 |
|---|---|
| `AirSession.kt:537-543` | `SecurityRoute.SAP` 原来是 `-> Unit`；现在在 `experiment` 下真正调用 `AccessoryAuth.mfi(c, EXPERIMENTAL_RSA_PKCS1_SHA1_PUBLIC_KEYS_V1, log)` |
| `AirSession.kt:563` | `encryption=mfi?.let{CarPlaySetupRequests.Encryption(16,it.wrapped,it.iv)}` → SETUP 带 `et=16` + `ekey`/`eiv`（**这行原本就有，只是 `mfi` 一直是 null**） |
| `AirSession.kt:552` | 正式门槛从 `if(!experiment||shared==null)` 改为 `if(mfi==null&&(!experiment||shared==null))`——SAP 成功拿到材料时不再要求 Apple 根信任包 |

**SAP 的理论依据**（重要，别被"需要 Apple MFi 私钥"误导）：

`AccessoryAuth.mfi()` 里，手机只做三件事：
1. 生成临时 X25519 密钥对，`POST /auth-setup` 送出公钥；
2. 收 `server_pub | certLen | 车机证书 | sigLen | 签名`，用 `SHA1("AES-KEY"‖shared)` 前 16 字节做 AES-CTR 解签名；
3. **用车机证书自己的公钥**验 `server‖client` 的 RSA 签名，然后自选 16B key/IV 包好发回。

**全程不需要任何 Apple 签发的私钥。** 作者自己在 `firmware` 的 `analysis/vertical-feasibility/linux-first/dependencies.json` 里也写了：
`MFI-SAP-CONDITIONAL: Peer verification may need public trust materials rather than local vendor private key`。

### 4.4 CarWith 自唤醒死锁修复

| 文件 | 改动 |
|---|---|
| `bridge/.../SessionController.kt:207` | 新增 `var hostOwnsDisplay=fromHost`，视频段所有 `fromHost` 判定改用 `hostOwnsDisplay` |
| 同文件 `:519-539` | `fromHost=false` 时主动 `h.bind()`；**只判定绑定成功**，不等 `host-display` |
| 同文件 `:822-853` | 走与 CarWith 发起完全相同的路径：splash → `h.surface()` → 等 `hostDisplayReady` 3 秒；失败则 `h.requestForeground()` 拉前台 → 1.5 秒后重试 → 仍失败回退本地页 |
| `host-api/.../CastHost.kt:56` | 新增 `suspend fun requestForeground(): Boolean = false`（默认实现，不破坏其他宿主） |
| `host-carlife-mixing/.../VendorCastHost.kt:249` | 用宿主包名 launch intent 实现 |
| `host-carlife-mixing/.../CarWithHost.kt:39` | 转发 |

**已埋的判据日志**：
`Host bound=… source=…` / `Host prepared a cast display; the app-owned page is released` / `…after being brought to the foreground` / `Host never called onCastPrepared (handed=… foreground=…)`

⚠️ 用户已明确表示"app 发起也能进 CarWith 这个不重要"，**这块不要再投入**，除非 §6 的 P0/P1 全部关闭。

### 4.5 日志导出体验

| 文件 | 改动 |
|---|---|
| `app/.../ui/page/LogPage.kt` | 标题栏新增**分享**按钮：写 `cache/logs/` → `FileProvider` → 系统分享面板 |
| `app/src/main/AndroidManifest.xml` | 注册 `${applicationId}.fileprovider` |
| `app/src/main/res/xml/file_paths.xml` | 新增，指向 cache |
| `app/src/main/res/values*/strings.xml` | `action_share`（导出/分享） |

文件名从固定 `device-log.txt` 改为 `carvex-log-yyyyMMdd-HHmmss.txt`，不再互相覆盖。

### 4.6 蓝牙 RFCOMM 诊断

`protocol-carplay/.../Bootstrap.kt`（+3 行）：打出 `Bluetooth cached uuids=0x…,0x…`，用于判断对端到底发布了哪些 SPP UUID（对应日志里的 `NO_WIAP_HINT`）。

---

## 5. 没解决的问题（按阻塞程度排序）

### U-1 ★★★ 车机是否提供 `/auth-setup`（唯一的"生死未知"）

- **现象**：不知道。真机从未走到这一步。
- **代码**：`AccessoryAuth.kt:173` `check(r.status in 200..299){"MFiSAP rejected "+r.status}`
- **如果 404**：抛异常 → 会话失败 → **这台车在 CarVeX 上彻底无解**（下一条路是 FairPlay `/fp-setup`，本仓库完全没有实现）。
- **如果 200**：继续看 U-3。

### U-2 ★★★ SAP 路线下**音频必定没有声音**（确定，非推测）

- **代码**：`AirSession.kt:1043`
  ```kotlin
  val secret = shared ?: throw UnsupportedOperationException("Audio RTP profile requires HomeKit; MFiSAP audio is not established")
  ```
- `shared` 由 HAP pair-verify 产生，SAP 路线恒为 null → 每个分类的音频 SETUP 都抛。
- **不会弄死会话**：`SessionController.kt:945-948` 按分类 catch，日志 `CarPlay audio category=N unavailable; other streams retained`，视频继续。
- **结论**：真机若走 SAP，表现是"有画面、无声音"。
- **要修的方向**（未做，等 U-1 结论）：
  1. 输出密钥：`Crypto.hkdf(secret,"DataStream-Salt$id",…)` → `mfi.streamCipher(id)`（`AccessoryAuth.kt:149` 已有，AES-CTR，公式 `SHA512("AirPlayStreamKey"‖dec(i)‖K)[0:16]`）
  2. 帧格式：`MediaAudioPackets.accessUnit()` 现在只有 HomeKit 的 ChaCha20-Poly1305；SAP 是 AES-CTR，头/tag 结构不同，需另写分支
  3. 麦克风：`CarPlayMicReceiver` 的 `key`/`alternateKey` 同理
- **风险**：无抓包可验证（见 U-7），改完可能只是"从没声音变成有噪声"。

### U-3 ★★★ SAP 路线视频加密路径从未在真机验证

- **代码**：`AirSession.kt:1303`
  ```kotlin
  val cipher=aes ?: mfi?.streamCipher(streamId)?.also{aes=it} ?: error("Missing media crypto")
  ```
  配合 `AirSession.kt:1304-1306` 的 128 字节兼容头（offset 0=长度, 8=NTP, 16=单调时间戳）。
- 这条分支以前因 `mfi==null` 永不执行，属于"写好了但从来没跑过"。
- **最坏表现**：SETUP 回 200，但车机黑屏或花屏。
- **可调参数**：头布局、CTR 计数器是否跨帧连续、`streamCipher` 的 streamId 取值。

### U-4 ★★ SAP 签名校验只支持一种算法

- `AccessoryAuth.kt:156,160` 只认 `SHA1withRSA`；`verifyMfiSignature` 还要求 `RSAPublicKey` 且模长 1024..4096。
- 车机证书若是 ECDSA 或别的填充 → 直接 `SecurityException("MFiSAP signature verification failed …")`。
- 有单测覆盖（`core/MfiSignatureTest.kt`），但只覆盖合成证书，没有真实车机样本。

### U-5 ★★ `sameAddress` 过严，可能把能走 HAP 的车误推去 SAP

- `gate` 要求 Bonjour 地址与 iAP2 地址 `contentEquals`。mingtu 就是 IPv6 vs IPv4 不相等。
- 现在后果从"直接失败"变成"静默转 SAP"。如果某台车 HAP 本可用，就会被推到更不成熟的 SAP 路上。
- **未改**。若决定放宽，建议改成"端口一致 + 同一网段/可路由"，并保留原判定为日志字段，不要删证据。
- `ReceiverMetadata` 自己的注释写的是"地址只作连接候选，不参与身份判定"，**代码与注释矛盾**，这是项目自身的一处内部不一致。

### U-6 ★★★ 真机一次都没验证过

- winplay 走 **PAIRED(HAP)**，真车必然走 **SAP**。两条路径的实现成熟度差一个数量级。
- **不要把 winplay 的成功当作真车可用的证据。** 这是本文档最重要的一条纪律。

### U-7 ★★★ 没有媒体抓包 → 帧格式改动无客观判据

- `research/protocol/airplay_fairplay_crypto/STATUS.md` 明确写了：缺 AirPlay 媒体抓包，`OPEN-3`/`OPEN-10` 未闭合，`verify.py` 对 C10 显式 SKIP。
- 意味着 U-2/U-3 的改动只能"改了试、试了看画面"，无法用测试证明正确。
- **若要做严肃验证，需要一台能抓包的接收端**（或让 winplay 支持 SAP 模式并抓包），这是比改代码更值钱的前置投入。

### U-8 ★ winplay 蓝牙侧不完整（已判定不可用作端到端测试台）

- 早期日志：`uuidSource=platform_cache observation=NO_WIAP_HINT uuidCount=7`，两个 RFCOMM UUID 都被对端立即关闭（`read ret: -1`）。
- winplay 只模拟 AirPlay 接收端，不实现 Wireless iAP 的 SDP 与 iAP2 识别。**它只能测"AirPlay 之后"的链路。**
- 若要它支持端到端，需要它补齐：SDP 发布 `…caff`/`…0a78` → iAP2 探测/同步/识别/认证 → `5702/5703` 交 Wi-Fi 参数。

### U-9 ☆ 已知但可接受

- 音频格式固定选 AAC-LC（type 102），PCM 仅作兜底：这是设计取舍（PCM 1536 kbps vs AAC 约 256 kbps）。**不要为了"更原始"把 PCM 调成首选**，会带来 6 倍码率和延迟恶化。

---

## 6. 接下来怎么走

### 6.1 阶段划分

| 阶段 | 目标 | 前置 | 产出 |
|---|---|---|---|
| **P0** | 真机定生死：`/auth-setup` 存不存在 | 无 | 一份真机日志 |
| **P1** | 若 P0 通过：确认画面能否出来 | P0 | 黑屏/花屏/正常三选一 |
| **P2** | 音频（仅 SAP 路线） | P1 = 有画面 | 出声 |
| **P3** | CarWith 自唤醒 | 用户已降级 | 不做也行 |

**不要跳级。** P0 没结论之前改 P2，等于给一个可能根本不存在的路径写代码。

### 6.2 P0：真机验证（唯一该现在做的事）

**步骤**

1. 装包：
   ```
   adb install -r android/app/build/outputs/apk/xiaomi/debug/CarVex_xiaomi_debug_*.apk
   ```
   （包名 `com.baidu.carlife.xiaomi`，Flavor 必须与手机已装的一致）
2. **App 内设置 → 打开"实验认证模式"**。不打开的话 `SessionController.kt:70` 会直接拒绝：
   `首次使用请在设置中了解并启用实验认证模式`
3. 从 **CarWith 的 CarLife** 发起连接（不要从 CarVeX 自己点连接，那条路是 P3）。
4. 连上后，日志页右上角点**分享**，把 `carvex-log-*.txt` 拿出来。

**判据（按顺序看）**

| 日志 | 含义 | 下一步 |
|---|---|---|
| `MFi/SAP route selected; POST /auth-setup` | 选路成功，回落生效 | 继续看下一行 |
| `MFiSAP rejected 404`（或其它非 2xx） | **车机不给 SAP 端点** | → 6.4 结论 A，停手 |
| `MFiSAP certificateBytes=… signatureBytes=…` | 车机回了证书，进入验签 | 继续 |
| `MFiSAP signature verification failed` | 算法/填充假设不对 | → U-4，把证书字节数和算法给出来 |
| `MFiSAP signature verified; Apple root trust NOT verified` | 认证通了 | 继续 |
| `MFi/SAP material ready; SETUP will carry et=16 with ekey/eiv` | 密钥就绪 | 看 SETUP 返回 |
| SETUP 200 + 帧在流，但**黑屏** | 视频加密/帧头不对 | → 6.3，U-3 |
| SETUP 200 + **有画面** | 成功 | → P2 音频 |

**同时应该看到的一行**（用于验证我的诊断改动是否有效）：

```
Experimental HAP gate=pk_missing pi=absent pk=absent bonjour=fe80::…:7000 iap2=192.168.0.1:7000
```

如果这里显示 `address_mismatch` 或 `pk_missing`，说明 §3 的分析成立；如果显示 `accepted`（即车机这次给了 `pk`），那 HAP 可能可用，**先走 HAP，不要用 SAP**。

### 6.3 P1：有 SETUP 200 但黑屏时怎么查

按可能性排序，逐个排除，**一次只改一个变量**：

1. **确认 `et=16` 真的进了 SETUP**：`CarPlaySetupRequests.kt:41` 只有 `encryption != null` 才写 `et/ekey/eiv`。若日志显示 `mfi` 有值但 SETUP 里没有，是装配问题。
2. **确认帧头布局**：`AirSession.kt:1304-1306` 的 128 字节头。对照 `research/` 里第 07 章 §2.6 的描述核对 offset。
3. **确认 CTR 计数器连续性**：`private var aes` 是复用同一个 `Cipher`，靠 `cipher.update()` 自然推进 keystream。若车机要求每帧重置 IV+帧序号，这里就不对。
4. **确认 `streamCipher` 的 streamId**：用 `streamId` 拼 `"AirPlayStreamKey"+id`，id 取值必须与 SETUP 里 `streams[].streamID` 一致。

改之前先把日志里这三样抄下来：`streamId`、SETUP 实际发的 `et/ekey/eiv`（十六进制）、首帧前 32 字节。

### 6.4 P2 之前必须先做的判断

- **结论 A（`/auth-setup` 404）**：这台 mingtu 无解。**建议停手，不要投入 FairPlay**——那需要 Apple MFi 认证材料，本仓库零实现，不是几行代码的事。可选替代：换一台支持 HAP（会发 `pk`）的车机做验证。
- **结论 B（验签失败）**：把 `certificateBytes`、`publicKey.algorithm`、`signatureBytes` 记下来，按实际算法扩 `SapSignatureSchema` 枚举。这是可控的。
- **结论 C（认证通过、有画面）**：进 P2，按 U-2 的三处改动做，**只动 SAP 分支，不动 HAP**（HAP 已验证可用，见 V-3）。

### 6.5 每次改完的固定动作

```bash
cd android
export JAVA_HOME="<JDK17 绝对路径>"
./gradlew.bat :protocol-carplay:testDebugUnitTest :host-carlife-mixing:test --no-daemon --console=plain
./gradlew.bat :app:assembleXiaomiDebug --no-daemon --console=plain
```

两个都必须绿。协议栈有 1000+ 用例，`SecurityRouting` 相关改动很容易踩到既有断言。

---

## 7. 禁止事项 / 踩坑记录

| # | 禁令 | 原因 |
|---|---|---|
| 1 | **不要把 winplay 的成功当作真车可用** | 两条认证路径，成熟度差一个数量级（U-6） |
| 2 | **不要改 HAP 路线的音频代码** | 已在 winplay 实测出声（V-3），动了就是把能用的弄坏 |
| 3 | **不要把 PCM 设为音频首选** | 码率 6 倍（1536 vs 256 kbps），延迟与 RED 都会恶化（U-9） |
| 4 | **不要对 `package-lock.json` / 版本号文件做全局 sed** | 会改坏依赖的真实版本；只改根 version 两处 |
| 5 | **不要全量 clone `firmware/`** | 几十 GB；用 `--filter=blob:none` + `git show` 按需取 |
| 6 | **不要动 `AndroidManifest.xml` 里 `ShizukuProvider` 的 `exported`** | 必须 `true`，否则 Shizuku 权限永远拿不到（我在加 FileProvider 时误改成 false 过，已改回） |
| 7 | **不要删 `.workbuddy/`** | 是项目记忆，不是缓存 |
| 8 | **构建必须用 JDK 17**（`JAVA_HOME` 指过去） | toolchain 硬要求 17；装了 21/25 又不指定会直接失败 |
| 9 | **SDK 包名是 `platforms;android-37.0`** | `platforms;android-37` 不存在，会装不上 |
| 10 | **不要用 javadoc 式的"大概"下结论** | 这个项目里的结论全部要落到 `文件:行号` 或日志原文，否则下一个 Agent 会重复踩 |
| 11 | **不要 `git push upstream`** | `upstream`（`iamr0s`）只读，没有写权限；所有改动推到 `origin`（`MingTu01`） |
| 12 | **不要 `git add firmware`** | 会把固件指针从 `5630458` 挪到 `main` 的 `b786786`，与研究结论所依据的版本不一致 |

---

## 8. 关键文件索引

| 关注点 | 文件 |
|---|---|
| 安全选路（本次改动核心） | `android/protocol-carplay/src/main/java/io/github/iamr0s/carvex/carplay/core/SecurityRouting.kt` |
| HAP gate / 诊断原因 | `.../carplay/BootstrapSecurity.kt` |
| 会话主循环、SETUP、视频加密 | `.../carplay/AirSession.kt`（`mfi` 在 93、SAP 分支 537-563、视频加密 1290-1310） |
| MFi/SAP 握手 | `.../carplay/core/AccessoryAuth.kt`（`mfi()` 169、`streamCipher` 149、`verifyMfiSignature` 156） |
| 音频格式选择 | `.../carplay/core/CarPlayAudioPlan.kt` |
| SETUP 字段装配 | `.../carplay/core/CarPlaySetupRequests.kt` |
| 会话编排 / 宿主交互 | `android/bridge/src/main/java/io/github/iamr0s/carvex/session/SessionController.kt` |
| 宿主契约 | `android/host-api/src/main/java/io/github/iamr0s/carvex/sessioncore/CastHost.kt` |
| CarWith 适配 | `android/host-carlife-mixing/src/main/java/io/github/iamr0s/carvex/host/` |
| 协议研究结论 | `research/connection/spec/26-airplay-security-branches.md`、`research/protocol/airplay_fairplay_crypto/STATUS.md` |
| 可行性台账（作者自述） | `firmware/analysis/vertical-feasibility/linux-first/dependencies.json`（需 `git show` 取） |

---

## 9. 协议速查

**features 位（`AirPlayFeatures.kt`）**：7 / 9 / 18(PCM) / 19(ALAC) / 20(AAC-LC) / 26(AES-128 MFi SAP v1) / 32 / 37 / 38(CU 配对)

**mingtu `0x6104040280`** = 7,9,18,26,32,37,38 → 有 SAP，无 `pk`
**winplay `0x615653aee2`** = 含 HAP 配对位 → 走 PAIRED

**三条安全路线**：

| 路线 | 触发 | 本仓库状态 |
|---|---|---|
| `PAIRED`（HAP pair-setup + pair-verify） | 对端发 `pk` 且 gate 全通过 | ✅ 成熟，winplay 已验证 |
| `SAP`（MFi `/auth-setup`） | bit26 + gate 失败 + 实验模式 | ⚠️ 本次接通，未上真机 |
| FairPlay（`/fp-setup`） | 对端只认 FairPlay | ❌ 零实现 |

**音频 type**：`100` = 低延迟/PCM 与语音；`101` = 备用；`102` = 压缩媒体（AAC）
**常用掩码**：`0x8000` = PCM16/48000/2ch；`0x800000` = AAC-LC/48000/2ch

---

## 10. 交接检查单

接手后按顺序确认，全部打勾才算接稳：

- [ ] JDK 是 **17**（`./gradlew.bat -version` 确认），SDK 有 `platforms;android-37.0`，`local.properties` 已写
- [ ] `cd android && git log --oneline -4` 能看到 4 个提交，且 `git status` 干净
- [ ] `git remote -v` 里 `origin` 指向 `MingTu01`、`upstream` 指向 `iamr0s`
- [ ] 构建能出包（§1.2），产物 75 MB 左右，版本号 = 20000 + 提交数
- [ ] 两个测试任务全绿
- [ ] 读过 §3（真机失败五步链）与 §5 的 U-1/U-2/U-3
- [ ] 理解"真车必然走 SAP、音频必定哑"这两个结论
- [ ] 拿到一份**真车**日志，且能看到 `Experimental HAP gate=` 那一行
- [ ] 按 §6.2 的判据给出 P0 结论（A/B/C 之一）
