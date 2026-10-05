# EPD106 (virgo-perf1) — 主板调试串口观察 & 无 ADB 授权时的救援思路

**设备**：小米多看电纸书一代 / 墨案电纸书青春版
**型号**：EPD106　**代号**：`virgo-perf1`　**SoC**：Allwinner B300 (`sun8iw15p1`)
**系统**：Android 8.1，`user/test-keys` 构建，无 AVB、无 dm-verity，bootloader 未锁

> **状态说明**：第 4 节（主板调试串口）是**主板实物观察结果**，照片为证。
> 由它引出 u-boot 控制台的思路**尚未在本机实测验证**，请勿当作已验证教程使用。

---

## 1. 场景：卡在开机动画，且 adb 永远 unauthorized

安装第三方桌面（`com.etang.mt_launcher`，即"莓糖桌面"）并设为默认 HOME 之后：

- 开机只有 logo + 进度条，跑满即循环，进不了系统
- `adb devices` 显示 `<serial>  unauthorized`，且**永远停在这个状态**

## 2. 为什么常规手段全部无效（逐条实测）

| 手段 | 结果 | 原因 |
|---|---|---|
| 盲点授权弹窗 | ❌ 原理上不可能 | 弹窗是 `com.android.systemui` 的 `UsbDebuggingActivity`；框架起不来 ⇒ 弹窗**从未被绘制**。且 `adb shell input tap` 本身就需要授权，逻辑自环 |
| 硬件组合键进 recovery | ❌ 不存在 | 本机只有电源键 + 重置孔，**无音量键**。社区实测结论：无音量键机型没有 recovery 组合键，**ADB 是唯一入口** |
| FEL | ❌ 不可用 | B300 的 SoC ID `0x1755` 不在 `sunxi-tools` 的 `soc_info.c` 里；且缺 `fes1.fex`，进不了 FES 模式 |
| fastboot | ❌ 无入口 | 需要 `adb reboot bootloader`，而 adb 未授权 |
| SD 卡启动 | ❌ 无卡槽 | — |
| MTP / UMS | ❌ 不暴露 | 框架没起来，USB 功能集没切换，只枚举出单个 ADB 接口 |

**结论**：框架起不来 + ADB 密钥丢失 ⇒ `unauthorized` 无法解除，而 recovery / FEL / fastboot 又全都没有入口。

## 3. 为什么"卡在开机动画"时 adb 还能被授权（对照情形）

公开教程里能修好这类机器的人，`adb devices` 显示的是 `device`（已授权）—— 因为
`/data/misc/adb/adb_keys` 里**早就存着他们主机的公钥**。所以 `adb reboot recovery`
才发得出去。**本文场景的区别就在于：主机换过系统，旧私钥没了。**

## 4. 【主板观察】调试串口焊盘

主板上有一组**印了丝印**的调试焊盘：

```
S-TX     S-RX     GND     FEL
```

（照片见 `images/board_uart.jpg`）

### 接线（若验证成功）

| USB-TTL | → | 主板 |
|---|---|---|
| GND | → | `GND` |
| TX | → | `S-RX` |
| RX | → | `S-TX` |
| VCC / 3V3 | → | **不接，悬空** |

### ⚠️ 安全警告

1. **绝对不要把 VCC / 3V3 接到主板上** —— 设备由 USB 供电，反向灌电可能损坏主板。
2. **USB-TTL 必须工作在 3.3V 电平**（CH340G 模块上的 5V/3V3 跳线要插到 3V3）。
   5V 电平打到 SoC 的 UART 引脚上可能击穿。

### 串口参数

- 首选 **115200 8N1**（全志 u-boot 调试口默认）
- 若乱码，换 **1500000 8N1**

## 5. 【待验证】拿到 u-boot 控制台之后

u-boot 运行在 Android 之前，**完全不需要 ADB 授权**，且自带读写 eMMC 的能力：

```
mmc list                 # 列出存储设备
mmc dev 0                # 选中 eMMC
part list mmc 0          # 查看分区表
ums 0 mmc 0              # 把 eMMC 挂成 U 盘 → 在 PC 上直接看到分区
fastboot usb 0           # 或者起 fastboot
```

若 `ums` 可用，就能：dump 出 `/data` 备份 → 只删掉出问题的桌面 APK → 写回，**资料保住**。

## 6. 【已验证】自制 testkey 签名刷机包

固件自带 `/system/etc/security/otacerts.zip`，其证书与 AOSP 公开 testkey **完全一致**：

```
OTA otacert     sha256 = A4384BA815B9499A5CE349B4E33C1755278873FE2EAC150A068823F526E6DBDE
AOSP testkey    sha256 = A4384BA815B9499A5CE349B4E33C1755278873FE2EAC150A068823F526E6DBDE
```

因此可自签 `update.zip`，经 stock recovery 的 **Apply update from ADB** 刷入
（recovery 只验整包签名：PKCS7 DER 放在 zip 注释里，覆盖 `[文件头, EOCD+20)`）。

签名需要 **JDK 8**（signapk 会摸 `sun.security.pkcs`，JDK 9+ 不再导出）。

```
java -jar signapk-1.0.jar -w testkey.x509.pem testkey.pk8 in.zip out_signed.zip
```

签名正确性校验（zip 注释应形如 `"signed by SignApk" + 0x00 + DER PKCS7`）：

```python
import struct
d = open("out_signed.zip","rb").read()
i = d.rfind(b"PK\x05\x06")
clen = struct.unpack("<H", d[i+20:i+22])[0]
c = d[len(d)-clen:]
assert c.startswith(b"signed by SignApk")
assert c[18:20] == b"\x30\x82"      # DER PKCS7
```

## 7. 相关链接

- 本机 root / 工具链：<https://github.com/delbertbeta/edp106>
- 同族机型 root 思路：<https://github.com/qwerty12/inkPalm-5-EPD105-root>
- EPD106 ADB 使用：<https://github.com/epodegrid/epd106-ADB>
- EPD106 官方 OTA（含 `u-boot.fex` / `boot0_sdcard.fex` / `boot.img`）：<https://github.com/lav89/MAS_EPD106A_L8AB802_V07_240424>
- EPD106 TWRP 设备树：<https://github.com/nekohashizuku2333333333/twrp_device_mireader_epd106>
