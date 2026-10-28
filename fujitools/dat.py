"""DAT 容器格式解析

格式 (os=4/6, X Processor 世代):
    0x000  u32   格式版本 "os" (1,2,3,4,5,6,8 -> 机型代码区大小 64/128/512B)
    0x004  NB    机型代码区: ASCII, 每隔一字节为 '3'(0x33), 取奇数索引字节得数字串
                 结构: 基础码(6位)+区域变体(2位) 的重复列表
    +N     u32   版本 major (十进制)
    +N+4   u32   版本 minor (按十六进制显示)
    +N+8   u32   校验和 (算法未逆向)
    +N+12  u32   end/类型标志 (==2 为镜头固件)
    +N+16  ...   payload; 代码区混淆 = XOR 0xFF, 资源区明文, 部分段 fflz 压缩
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

CODE_SIZES = {1: 64, 2: 128, 3: 512, 4: 512, 5: 512, 6: 512, 8: 512}


@dataclass
class DatFile:
    path: Path
    os_ver: int = 0
    model_code: str = ""
    model_variants: dict = field(default_factory=dict)
    version: str = ""
    checksum: int = 0
    end_flag: int = 0
    payload_offset: int = 0
    sha256: str = ""

    @classmethod
    def open(cls, path: str | Path) -> "DatFile":
        p = Path(path)
        d = p.read_bytes()
        os_ver, = struct.unpack_from("<I", d, 0)
        if os_ver not in CODE_SIZES:
            raise ValueError(f"未知格式版本 {os_ver}: {p}")
        n = CODE_SIZES[os_ver]

        code_raw = d[4:4 + n]
        digits = "".join(chr(code_raw[i]) for i in range(1, len(code_raw), 2))
        model_code = digits.rstrip("0\x00")

        major, minor, checksum, end = struct.unpack_from("<4I", d, 4 + n)
        version = f"{major}.{minor:02X}"

        variants: dict[str, list[str]] = {}
        for i in range(0, len(model_code) - 7, 8):
            g = model_code[i:i + 8]
            variants.setdefault(g[:6], []).append(g[6:])

        return cls(
            path=p, os_ver=os_ver, model_code=model_code, model_variants=variants,
            version=version, checksum=checksum, end_flag=end,
            payload_offset=4 + n + 16,
            sha256=hashlib.sha256(d).hexdigest(),
        )

    @property
    def raw(self) -> bytes:
        return self.path.read_bytes()

    def xor_view(self) -> bytes:
        """payload 整体 XOR 0xFF 视图 (代码区正确解码; 明文资源区会被反转, 分析时注意)"""
        d = self.raw
        return bytes(b ^ 0xFF for b in d[self.payload_offset:])

    def summary(self) -> str:
        lines = [
            f"文件      : {self.path.name}  ({self.path.stat().st_size:,} bytes)",
            f"SHA256    : {self.sha256}",
            f"格式版本  : os={self.os_ver} (代码区 {CODE_SIZES[self.os_ver]}B)",
            f"固件版本  : {self.version}",
            f"校验和    : 0x{self.checksum:08x}",
            f"end标志   : {self.end_flag}" + (" (镜头固件)" if self.end_flag == 2 else ""),
            f"机型代码  : {self.model_code}",
        ]
        for base, vs in self.model_variants.items():
            lines.append(f"           基础码 {base}: 区域变体 {vs}")
        lines.append(f"payload   : 0x{self.payload_offset:x} 起")
        return "\n".join(lines)
