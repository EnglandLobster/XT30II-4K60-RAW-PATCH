# 开发与构建

## 结构

- `src/`：补丁 C/ARM/链接脚本、原验收版主机安装逻辑、离线模拟器和录像分析工具。
- `tools/prepare.py`：校验并解码用户提供的原厂 2.04 DAT；本地重建引用窗口，明确标记为离线参考。
- `tools/camera_checks.py`：新的固定窗口现场核验入口，只有 `--execute` 才打开 USB。
- `tools/install.py`：按原验收顺序组织的交互式向导。
- `payloads/`：9 个已验收核心载荷、2 个历史诊断载荷和源码构建 manifest。
- `metadata/`、`validation/`：来源、指纹、本地数据配方、历史模拟/录像摘要。
- `vendor/fffw/`：固定提交的 MIT USB transport，无运行时 sibling checkout 依赖。

主机源码为独立发布调整了目录路径和编译器发现方式；设备端补丁 C/汇编/链接脚本与私有研究验收源一致。已验证编译输出相同。`src/normal_route_20261012` 这个日期名保留了原工具的文件契约，里面的新安装输出仍使用当前时间戳。

## 离线检查

```sh
python -m pip install -r requirements.txt
python tools/check.py --payloads-only
python tools/prepare.py /path/to/XT30II_FW204.DAT
python tools/check.py
```

完整测试需要自己提供参考 DAT，测试不得访问 USB。CI 只执行不需要原厂文件的完整性/语法/发布入口单元测试；不把私有 DAT 上传为 CI artifact 或 secret。

## 编译

依赖 Python 3.11+、clang（ARMv7 freestanding）、ld.lld、llvm-objcopy、llvm-nm。将 LLVM 工具加入 PATH。macOS 验证命令：

```sh
CC=/usr/bin/clang PATH="$(brew --prefix llvm)/bin:$PATH" python src/build_ram_payloads.py
```

输出单独写入被忽略的 `build/`，不会覆盖 `payloads/`。构建器核对 9 个核心二进制的 SHA256，编译器版本导致字节变化时明确失败。不要以新结果替换验收版、更新哈希来消除失败。其他系统/编译器的输出若不同，应独立分析并重新验证。

## 设计约束

FPS 策略、独立缓冲 profile、400Mbps ceiling 和完整电影菜单指针是四个独立目标。FPS apply 后必须先提示用户重选 29.97P/200Mbps、退出菜单并确认，再执行独立缓冲策略。拒绝确认或 FPS apply 失败时，不得执行剩余策略。不要省略独立缓冲步骤，否则初始问题中的描述符重叠会重新出现。设备端通过原厂 API 临时调整所需权限，恢复后核验完整区域；主机不直接把目标页表改成任意可写。

存活的 12KiB arena 由原厂分配获得；本版本普通策略只接受已验收分配地址。没有动态重定位到任意地址的实现。代码/状态保持引用时不可 free；完整冷启动是本版退出路径。

超时或短响应会退役传输。不要添加自动重试、伪造完成状态、复用旧 installation，或用 2.04 的离线模型替代 2.06 现场兼容性。

[历史模拟报告](../validation/)仅复用原验收字节对应的证据。新增代码、固件兼容或启动/恢复路径应新增有区分力的测试，并明确区分离线、构建、真机及物理验收。
