# 安装与日常使用

适用：富士 X-T30 II，**机身固件 2.06**，实验性 RAM 补丁 v0.1.1。真机流程在 macOS 验收；Linux/Windows 的 USB 驱动配置仅作准备参考，本项目尚未完成这些系统的上机验收。

## 1. 准备电脑和参考数据

需要 Python 3.11+、libusb、USB 数据线。macOS 可使用 Homebrew 安装 `libusb`；Ubuntu 可安装 `python3-venv libusb-1.0-0`。Windows 需要 Python 和 libusb 可用的 USB 后端，必要时按 [fffw 上游说明](https://github.com/tiredboffin/fffw#instructions-ff80)为 **04cb:ff80** 配置 WinUSB，勿改其他设备的驱动。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows 激活命令为 `.venv\Scripts\activate`。

从[富士官方支持](https://www.fujifilm-x.com/global/support/download/firmware/cameras/x-t30-ii/)自行取得参考文件。工具需要 **XT30II_FW204.DAT**，SHA256：

```text
723220a2c3781fa10585b1ed173a4df89aefe6208880f96fca97527bf398862c
```

若官网当前提供其他版本，应另行取得合法的 2.04 原文件；不要拿别的文件改名，不要跳过哈希检查。**这里的 2.04 用于电脑端离线解码，机身继续使用已验收的 2.06，不进行降级/升级。** 仓库不代为下载、接受厂商协议或分发原厂程序。

```sh
python tools/prepare.py /path/to/XT30II_FW204.DAT
python tools/check.py
```

准备器验证整个 DAT 和每个解码段，生成本地参考窗口、测试样本和已验收暂存页。这些文件留在被 Git 忽略的目录。部分 2.06 字体引用由已核对的 2.04→2.06 地址变换在本地重建；安装时还会读取真机并核对完整窗口哈希。

无需编译即可使用 `payloads/` 的已验收字节。准备和离线检查都不打开 USB。

## 2. 准备相机

1. 在机身确认型号 X-T30 II 和固件 2.06。
2. **自动关机设为关**；使用电量充足的电池，SD 卡留足空间。400Mbps 约 50MB/s，选择持续写入能力足够的卡。
3. 电影设置先用 **UHD 29.97P / MOV H.264 / LongGOP / 200Mbps**。停止录像并关闭所有菜单。
4. 关机，移除电池后装回，以清除旧 RAM 实例。
5. 在关机状态连接电脑 USB。按住**快门和方向上键**开机进入 Jig。上游把该模式称为 ff80，USB 标识应为 **04cb:ff80**。参见 [fffw 原始说明](https://github.com/tiredboffin/fffw#instructions-ff80)。
6. 关闭其他占用相机的程序，只连接一台目标相机。

Linux 非 root USB 权限可参考随包 `vendor/fffw/ff80/60-fujig.rules` 和上游的 `usbdev` 组说明；这是可选系统配置，不要为了运行工具关闭全局 USB 权限限制。

## 3. 交互式安装（推荐）

在仓库根目录和虚拟环境内运行：

```sh
python tools/install.py --execute
```

它会显示本次 installation 路径，并按下列顺序执行：

1. 离线校验；用户确认型号、固件、自动关机和初始设置。
2. 冷 Jig 基线和额外代码/字体指纹；不匹配则停止。
3. 私有内存执行/释放探针，保留原生页表准备结果。
4. 安装禁用状态的生命周期 hook 与电影菜单字体标签；验证禁用 hook 的 UI 消费。
5. 请求一次切换正常 REC，随即退役旧 USB 会话，不在旧会话上重试。
6. **出现正常取景后，按提示拔插一次 USB，期间不要关机、取电池或让相机自动关机。** 输入 YES 确认正常取景和未重启；工具读取新的 REC 状态与资源指纹。
7. 对 FPS 策略执行 probe/apply，解锁帧率。
8. **向导在此暂停：重新选择 UHD 29.97P／MOV H.264／LongGOP／200Mbps，退出菜单，再输入 YES。** 此时可能看到 59.94P，但独立缓冲与码率尚未安装，请勿录制 4K60，也不要关机或重插 USB。这个暂停点来自 v0.1.0 的真机中断记录；拒绝确认就停止，不执行剩余策略。
9. 在已恢复的 29.97P/200Mbps、停止录像、菜单关闭状态，依次对独立缓冲、码率、菜单三项策略执行 probe/apply。原有设置守卫、目标范围、权限恢复和驻留代码检查保持有效。
10. 全部安装完成后，按提示在完整电影菜单选 **UHD59.94P / MOV H.264 / 400Mbps**，退出菜单，输入 YES。工具确认最终设置和稳定边界。

输入 YES 是对当前机身状态的人工确认，不能从旧日志复制。安装脚本不会自动启动录像。若 USB 切换返回超时，但记录已进入 handoff，工具只在人工确认正常取景后继续**只读核验**，不会重发切换请求；核验失败即停止。

## 4. 手动分阶段安装（开发者）

每个命令前确认仍处在同一个未重启的冷启动周期。`INSTALLATION` 必须是本次命令输出的目录，不能填历史目录。

```sh
python tools/camera_checks.py cold --execute
python src/try_loader_probe.py --payload private_exec_probe --execute
python src/try_loader_probe.py --payload rec_install_label_probe --execute
```

记录输出中的 `src/normal_route_20261012/rec_install_label_probe_<本次时间>` 路径：

```sh
INSTALLATION=src/normal_route_20261012/rec_install_label_probe_<本次时间>
python src/test_resident_rec_hook.py "$INSTALLATION" --execute
python src/activate_rec_lifecycle.py "$INSTALLATION" --execute
```

确认正常取景，按上文拔插 USB；保持 29.97P/200、停止录像、菜单关闭：

```sh
python tools/camera_checks.py rec "$INSTALLATION" --live-view-confirmed --execute
python tools/camera_checks.py fingerprints --execute
FINGERPRINTS=src/normal_route_20261012/resource_fingerprints.json
python src/normal_fps_patch.py "$INSTALLATION" --action probe --execute
python src/normal_fps_patch.py "$INSTALLATION" --action apply --execute
```

**现在重新选择 UHD 29.97P／200Mbps 并退出菜单，再运行下方命令。** 即使先前已选过也要在帧率解锁后重新确认；当前不要录制 4K60。保持相机开机和 USB 连接。v0.1.0 真机试用时在此看到菜单为 59.94P/200Mbps，原守卫正确阻止了后续安装；恢复 29.97P/200Mbps 后即可继续。

```sh
python src/normal_resource_patch.py "$INSTALLATION" "$FINGERPRINTS" --action probe --execute
python src/normal_resource_patch.py "$INSTALLATION" "$FINGERPRINTS" --action apply --execute
python src/normal_bitrate_patch.py "$INSTALLATION" --action probe --execute
python src/normal_bitrate_patch.py "$INSTALLATION" --action apply --execute
python src/normal_bitrate_menu_patch.py "$INSTALLATION" --action probe --execute
python src/normal_bitrate_menu_patch.py "$INSTALLATION" --action apply --execute
```

最后选择 59.94P/400Mbps，关闭菜单再读取设置：

```sh
python src/capture_movie_buffer_state.py "$INSTALLATION" "$FINGERPRINTS" --label selected_60p400 --execute
```

成功选择对应 `selected_profile=6`、资源 type4、`route_classifier_inputs[1]=6`、`autoset.fps=5`、`autoset.bitrate=0`；参见 [完整验收设置](../metadata/selected-state.json)。此处枚举值来自原生数据结构，不是人类可读的 fps/码率单位。

默认不加 `--execute` 的工具只做离线前置检查，某些检查需要当前 installation 的文件；无文件时会报错，不会连接 USB。

## 5. 拍摄、关机与恢复

成功后先断开 USB，录一段短片，回放并检查原文件。建议用 `ffprobe` 检查分辨率、帧率、码率，再用 `ffmpeg -v error -i clip.MOV -f null -` 检查解码。400Mbps 为目标码率，实测会略有浮动。

录制时 LCD 实时画面可能卡顿。两段已检查原片的时间戳连续且无完全重复帧，不能仅依据 LCD 观感判断编码输出。

退出补丁：停止录像、等待写卡灯熄灭、断开 USB、关机、取出电池后重新安装并普通开机。按需恢复原厂支持的电影菜单设置。**关机、取电池或自动关机唤醒后，旧 installation 立即退役。** 重装先归档整个 `src/normal_route_20261012/`，重新运行准备工具和冷启动流程。不要删除仍在使用实例的日志或暂存文件。

## 6. 常见故障

| 现象 | 处理 |
| --- | --- |
| 参考 DAT 哈希不匹配 | 使用上文精确原文件；不要移除检查 |
| 找不到一台 04cb:ff80 | 确认数据线、Jig 按键开机与 USB 权限；普通相机 USB 模式不能替代 |
| 冷机指纹、页表或分配地址不匹配 | 当前状态/版本不符合验收条件；停止，保留日志并冷启动 |
| 超时、响应不完整或黑屏 | 不重试、不执行额外清理命令；先停止流程，结束写卡后断开 USB 并冷启动 |
| 帧率已解锁，但提示要求 29.97/200 | 重新选择 UHD 29.97P／MOV H.264／LongGOP／200Mbps 并退出菜单；保持开机，按本页手动流程从资源策略 probe 续接，勿重跑整个安装器 |
| 400Mbps 消失 | 检查是否发生关机或自动关机唤醒；从新冷启动重新安装 |
| 卡写入不足或录制中断 | 停止录制，换持续写入能力足够的卡并检查原片；本项目不解除温度或原厂保护 |

求助时提交版本、操作阶段和脱敏后的错误信息。完整 RAM 文件、原厂固件和个人原片请保留本地。
