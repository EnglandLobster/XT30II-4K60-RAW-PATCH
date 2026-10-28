# XT30II-4K60-RAW-PATCH

**富士 X-T30 II 的实验性内录补丁：3840×2160、59.94fps、MOV / H.264、400Mbps。**

[English](README.en.md) · [下载发布包](https://github.com/EnglandLobster/XT30II-4K60-RAW-PATCH/releases) · [完整安装说明](docs/INSTALL.md) · [验证与限制](docs/VALIDATION.md) · [源码与构建](docs/DEVELOPMENT.md)

这个项目公开我们已经完成真机录像验收的 **RAM 临时补丁**、ARM 源码和安装工具。完整电影菜单增加 400Mbps 项；帧率策略、独立录像缓冲配置和码率规则一起安装。它需要电脑通过 USB/Jig 注入，关机或自动关机唤醒后重新安装。

**当前版本：v0.1.1-experimental。仅在 X-T30 II、机身固件 2.06 上完成过真机验收。** X-T30、其他富士机型及其他固件版本不在本次兼容范围。用于离线参考的官方 **2.04 DAT 不是机身安装目标**，请勿为使用本项目降级或刷写它。固件版本和逐窗口指纹都必须符合要求。

## 已完成的效果

- UHD 3840×2160，实际帧率 `60000/1001`（59.94P）。
- MOV / H.264、400Mbps 选项和完整 `400Mbps` 菜单标签，选择可保留。
- 一段连续 **128.128 秒 / 7680 帧**的原片，视频码率约 **406.9Mbps**，文件约 **6.56GB**，音视频解码通过。
- 修正原配置中多个录像缓冲描述符重叠导致的块状撕裂；使用本机独立缓冲配置。

录像验收来自 2026-10-12 和 2026-10-15；2026-10-29 又从公开下载的 v0.1.0 包完成真机安装与最终 59.94P/400Mbps 读回，中途重选 29.97P/200Mbps 后按随包步骤续装成功。v0.1.1 将这个操作补为向导内的明确暂停点，并完成离线回归；9 个核心 ARM 文件保持原验收字节。原片和整机转储不随仓库发布。

## 开始使用

推荐先读[安装说明](docs/INSTALL.md)。需要 Python 3.11+、libusb、支持 USB 数据传输的线、已确认的 X-T30 II / 2.06，以及自行取得的精确版本参考 DAT。400Mbps 约等于每秒 50MB，SD 卡需要持续写入能力和足够空间。

```sh
git clone https://github.com/EnglandLobster/XT30II-4K60-RAW-PATCH.git
cd XT30II-4K60-RAW-PATCH
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python tools/prepare.py /path/to/XT30II_FW204.DAT
python tools/check.py
```

以上命令均不连接相机。准备完成、关闭机身自动关机、按说明进入冷启动 Jig 后，使用交互式入口：

```sh
python tools/install.py --execute
```

安装器会在物理操作处暂停确认，并依次完成冷机指纹、私有内存执行、菜单标签/生命周期、正常取景验证、四项策略的 probe/apply 和最终设置读回。**帧率解锁后会暂停，必须重新选择 29.97P／200Mbps 并退出菜单，确认后才安装其余三项；全部完成后再选择 59.94P／400Mbps。** 任一步不匹配就停止。完整手动命令也在[安装说明](docs/INSTALL.md)中。

## 使用与退出

在完整电影菜单选择 **UHD / 59.94P / MOV H.264 / 400Mbps**。保持自动关机关闭。先录制短片检查画面、声音和播放器信息，再进行正式拍摄。

回到原厂运行代码：停止录像，等写卡灯熄灭，断开 USB，关机并移除电池，再装回普通开机。录像菜单偏好可能仍保留，按需重新选择原厂支持的设置。再次使用补丁必须从新的冷启动安装开始。

## 已知限制

- 当前没有开机自加载、跨休眠保持或永久 ROM 刷机包。
- 录制时 LCD 预览曾有卡顿；已检查的两段原片没有解码错误、时间戳断点或完全重复帧，显示调度原因待查。
- 录像验证以已记录的短片和 128 秒连续片段为范围；长时间热稳定性、所有格式/镜头/卡组合尚未完成验收。
- 超时、黑屏或断电后停止当前流程；保留日志，冷启动后重新开始。不要反复重发执行命令或复用旧 installation 目录。

## 仓库内容与许可

`src/` 是自研 Python、C、ARM 汇编及链接脚本；`payloads/` 是已验收补丁；`tools/` 是独立准备/检查/安装入口；`validation/` 是去除个人路径的历史验收摘要；`metadata/` 保存散列和本地重建配方。

原厂 DAT、解码的原厂程序、RAM 转储、照片视频、个人凭据和历史机身安装凭证均不入库。`prepare.py` 仅在本地重建被忽略的参考文件；这些离线样本不会替代新的现场检查。

自研代码采用 [MIT License](LICENSE)。USB 传输使用 [tiredboffin/fffw](https://github.com/tiredboffin/fffw) 的固定版本，保留其 [MIT 许可](vendor/fffw/LICENSE.md)；来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。这是独立社区研究项目。
