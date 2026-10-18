# -*- coding: utf-8 -*-
"""
V6PAC 核心逻辑
==============
VOCALOID6 启动封面替换工具 —— 核心层 (与界面无关)

职责:
  * 定位 VOCALOID6.dll
  * 调用 v6res.exe 读取信息 / 校验 / 替换
  * 备份管理 (签名有效时备份一次, 永不覆盖)
  * 状态检测 (未应用 / 已应用 / 版本变化)

设计约束 (经实测确定):
  * VOCALOID6.dll 无自校验, 改后不影响启动; 但 Authenticode 签名会失效
  * 原地替换上限 = 各条目原始大小 (splash.png = 439,738 字节)
  * 超过上限时必须走 --rebuild (dnlib 重建, 已验证可用)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 路径常量
#
# 打包成 exe 后 `__file__` 指向 PyInstaller 的临时解压目录(_MEIPASS),
# 每次运行都会变。若把运行时数据放在那里, 备份/日志/状态会在每次重启后
# 消失 —— 对一个"帮你保住原版 DLL"的工具是致命的。
#
# 所以分成两个根:
#   RES_ROOT  只读资源(bin\v6res.exe、web\、预设默认图)  -> _MEIPASS
#   APP_ROOT  可写数据(备份/日志/状态/自定义/输出)       -> exe 所在目录
# 未打包时两者相同。

def _resource_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def _data_root() -> Path:
    if getattr(sys, "frozen", False):
        # exe 旁边: 用户能看到、能备份、升级时不会被删
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


RES_ROOT = _resource_root()
APP_ROOT = _data_root()

V6RES = RES_ROOT / "bin" / "v6res.exe"

DIR_BACKUP = APP_ROOT / "备份"
DIR_CUSTOM = APP_ROOT / "自定义"
DIR_PRESET = APP_ROOT / "预设"
DIR_LOG = APP_ROOT / "日志"
DIR_OUTPUT = APP_ROOT / "输出"
DIR_STATE = APP_ROOT / "状态"

for _d in (DIR_BACKUP, DIR_CUSTOM, DIR_PRESET, DIR_LOG, DIR_OUTPUT, DIR_STATE):
    _d.mkdir(parents=True, exist_ok=True)

STATE_FILE = DIR_STATE / "state.json"

# 候选 DLL 位置 —— 只作为最后的兜底。
# 真正可靠的来源是注册表的 InstallLocation(见 discover_dlls), 因为它记录了
# 安装器实际写入了哪里; 写死盘符会在装到 D:/E: 时直接找不到。
DLL_CANDIDATES = [
    Path(r"C:\Program Files\VOCALOID6\Editor\VOCALOID6.dll"),
    Path(r"C:\Program Files (x86)\VOCALOID6\Editor\VOCALOID6.dll"),
]

# 资源条目定义
RES_KEYS = {
    "splash": "assets/splash.png",
    "splashdev": "assets/splash_dev.png",
    "icon": "assets/icon.ico",
}

# 封面目标尺寸 (由 splashwindow.baml 决定; 只换图不改布局, 故必须匹配)
SPLASH_SIZE = (1200, 714)


class V6PacError(Exception):
    """工具自身的可预期错误。"""


# ---------------------------------------------------------------- 日志

_LOGFILE: Path | None = None


def log(msg: str, *, to_file: bool = True) -> None:
    """写日志 (控制台 + 文件)。"""
    global _LOGFILE
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    if to_file:
        try:
            if _LOGFILE is None:
                _LOGFILE = DIR_LOG / f"V6PAC-{datetime.now():%Y%m%d}.log"
            with open(_LOGFILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
        except Exception:
            pass


# ---------------------------------------------------------------- 子进程

def _run_v6res(args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    """调用 v6res.exe, 返回其 JSON 输出。"""
    if not V6RES.exists():
        raise V6PacError(f"缺少核心程序: {V6RES}\n请确认 bin 目录完整。")

    cmd = [str(V6RES), *args]
    log("执行: " + " ".join(cmd))
    try:
        p = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise V6PacError("核心程序执行超时。")
    except OSError as e:
        raise V6PacError(f"无法启动核心程序: {e}")

    out = p.stdout.decode("utf-8", "replace").strip()
    err = p.stderr.decode("utf-8", "replace").strip()

    if p.returncode != 0:
        detail = err or out or f"退出码 {p.returncode}"
        # v6res 的容量错误有专门退出码
        if p.returncode == 3:
            raise V6PacError(f"资源超出原地替换容量。\n{detail}")
        raise V6PacError(detail)

    if err:
        log("核心程序提示: " + err)
    try:
        return json.loads(out) if out else {}
    except json.JSONDecodeError:
        raise V6PacError(f"核心程序输出无法解析: {out[:400]}")


# ---------------------------------------------------------------- DLL 定位

def discover_dlls() -> list[dict]:
    """
    找出机器上所有 VOCALOID6.dll, 按可信度排序。

    来源(优先级从高到低):
      1. 注册表 Uninstall 项的 InstallLocation —— 安装器真正写过的位置
      2. 各盘符的常见安装路径 —— 覆盖装在 D:/E: 的情况, 也覆盖绿色版

    返回 [{"path", "version", "signature", "source"}]。同一路径只出现一次。
    多个结果时由界面让用户挑: 本机就同时存在 C:\\Program Files 下的 6.13.3.1
    和 E:\\VOCALOID6 下的 6.13.0.1, 静默"取第一个"很容易改错那个。
    """
    found: dict[str, dict] = {}

    def add(p: Path, source: str) -> None:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key in found:
            return
        if not p.is_file():
            return
        try:
            sig, _ = signature_status(p)
        except Exception:
            sig = "Unknown"
        found[key] = {
            "path": str(p),
            "version": file_version(p) or "?",
            "signature": sig,
            "source": source,
        }

    # 1) 注册表
    try:
        import winreg

        roots = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, sub in roots:
            try:
                with winreg.OpenKey(hive, sub) as root:
                    n = winreg.QueryInfoKey(root)[0]
                    for i in range(n):
                        try:
                            name = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, name) as k:
                                try:
                                    disp = winreg.QueryValueEx(k, "DisplayName")[0]
                                except OSError:
                                    continue
                                if "VOCALOID6" not in str(disp):
                                    continue
                                try:
                                    loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                                except OSError:
                                    continue
                                if not loc:
                                    continue
                                base = Path(str(loc))
                                for rel in ("Editor\\VOCALOID6.dll",
                                            "Editor\\VOCALOID6.dll".replace("\\", "/")):
                                    add(base / rel, "注册表")
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass

    # 2) 各盘符常见路径
    try:
        import string
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            if not root.exists():
                continue
            for rel in ("Program Files\\VOCALOID6\\Editor\\VOCALOID6.dll",
                        "Program Files (x86)\\VOCALOID6\\Editor\\VOCALOID6.dll",
                        "VOCALOID6\\Editor\\VOCALOID6.dll"):
                add(root / rel, "扫描")
    except Exception:
        pass

    # 3) 写死的兜底(和上面重复的会被去重)
    for c in DLL_CANDIDATES:
        add(c, "默认位置")

    items = list(found.values())
    # 注册表来源排前面, 其余按路径排序保证结果稳定
    items.sort(key=lambda d: (0 if d["source"] == "注册表" else 1, d["path"]))
    return items


def find_dll(explicit: str | os.PathLike | None = None) -> Path:
    """定位 VOCALOID6.dll。explicit 优先, 否则取 discover_dlls 的第一个。"""
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        raise V6PacError(f"指定的文件不存在: {p}")

    items = discover_dlls()
    if items:
        return Path(items[0]["path"])

    raise V6PacError(
        "未找到 VOCALOID6.dll。\n"
        "已在注册表和各个盘符的常见路径里查找, 都没有结果。\n\n"
        "请手动指定该文件。"
    )


# ---------------------------------------------------------------- 签名检测

def signature_status(dll: Path) -> tuple[str, str]:
    """
    返回 (状态, 说明)。
    状态取 'Valid' / 'NotSigned' / 'HashMismatch' / 'Unknown'。
    签名有效 == 文件是 Yamaha 原版, 未被任何工具改过。
    """
    ps = shutil.which("pwsh") or shutil.which("powershell")
    if not ps:
        return "Unknown", "未找到 PowerShell, 无法检测签名"
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{dll}'; "
        f"Write-Output $s.Status"
    )
    try:
        p = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        st = p.stdout.decode("utf-8", "replace").strip()
        desc = {
            "Valid": "签名有效 (原版文件, 未被修改)",
            "NotSigned": "无签名",
            "HashMismatch": "签名已失效 (文件被修改过)",
            "UnknownError": "签名状态未知",
        }.get(st, st or "无法判定")
        return st or "Unknown", desc
    except Exception as e:
        return "Unknown", f"签名检测失败: {e}"


def is_pristine(dll: Path) -> bool:
    """文件是否为未被修改的原版 (签名有效)。"""
    st, _ = signature_status(dll)
    return st == "Valid"


# ---------------------------------------------------------------- 权限

def is_admin() -> bool:
    """当前进程是否具有管理员权限。"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def can_write(path: Path) -> tuple[bool, str]:
    """
    检测能否写入目标文件。返回 (是否可写, 原因)。
    'denied'  = 权限不足, 需要管理员
    'locked'  = 文件被其他进程占用
    'ok'      = 可写
    """
    if not path.exists():
        return False, "missing"
    try:
        # 以独占方式打开读写, 不修改内容
        f = open(path, "r+b")
        f.close()
        return True, "ok"
    except PermissionError:
        # 区分「权限不足」与「被占用」
        import ctypes
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        FILE_SHARE_ALL = 0x00000007
        k32 = ctypes.windll.kernel32
        h = k32.CreateFileW(str(path), GENERIC_WRITE, FILE_SHARE_ALL,
                            None, OPEN_EXISTING, 0, None)
        if h == -1:
            err = k32.GetLastError()
            # 5 = ACCESS_DENIED (权限), 32 = SHARING_VIOLATION (占用)
            if err == 32:
                return False, "locked"
            return False, "denied"
        k32.CloseHandle(h)
        return False, "denied"
    except OSError as e:
        return False, f"error:{e}"
    except Exception as e:
        return False, f"error:{e}"


def verify_wpf(dll: Path) -> tuple[bool, str]:
    """
    验证资源条目类型符合 WPF 要求 —— 这是 VOCALOID6 启动的硬性前提。

    ⚠ 历史教训 (真实事故):
      .NET 资源容器为每个条目记录**运行时类型码**。WPF 通过 pack URI 加载
      资源时走 ResourceManager.GetStream(), 它**要求条目是 Stream 类型**。
      早期版本的 dnlib 重写路径把所有条目 materialize 成 byte[] 再写回,
      类型码随之变为 Byte[], 导致启动时:
          System.InvalidOperationException:
          Resource 'app.baml' was not a Stream - call GetObject instead.
            at ...ResourceManager.GetStream(...)
            at System.Windows.Application.LoadComponent(...)
            at Yamaha.VOCALOID.App.InitializeComponent()
      即 VOCALOID6 一启动就崩溃 (用户看到 "An unexpected error has occurred")。

    ⚠ 为什么必须用类型判据而不是"能否读出内容":
      用 ResourceReader 枚举或 GetManifestResourceStream 读字节, 两种类型
      都能正常读出、SHA256 也一致 —— 这类测试**发现不了**该缺陷。
      唯一可靠判据是条目的**运行时类型**必须是 Stream。

    返回 (是否合格, 说明)。
    """
    exe = APP_ROOT / "bin" / "types.exe"
    if not exe.exists():
        return True, "（未找到 types.exe, 跳过类型检查）"

    # 抽取 .g.resources 容器本体 (extract 导出的是图片, 不是容器)
    tmpdir = DIR_OUTPUT / "_typecheck"
    tmpdir.mkdir(parents=True, exist_ok=True)
    cont = _extract_container(dll, tmpdir)
    if cont is None:
        return True, "（无法定位资源容器, 跳过类型检查）"

    try:
        p = subprocess.run(
            [str(exe), str(cont)], capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return True, f"（类型检查无法执行: {e}）"

    out = p.stdout.decode("utf-8", "replace")
    # 解析形如 "   System.Byte[] = 223" 的统计行
    bad_types = []
    for ln in out.splitlines():
        s = ln.strip()
        if "=" not in s or not s.startswith("System."):
            continue
        name, _, cnt = s.partition("=")
        name = name.strip()
        cnt = cnt.strip()
        # Stream 系列是合法的
        if name.endswith("Stream") or name.endswith("MemoryStream"):
            continue
        bad_types.append(f"{name} × {cnt}")

    if bad_types:
        return False, ("资源条目类型不符合 WPF 要求 (会导致启动崩溃):\n  "
                       + "\n  ".join(bad_types) +
                       "\n\n条目必须是 Stream 类型。")
    return True, "资源条目类型正确 (Stream)"


def _extract_container(dll: Path, outdir: Path) -> Path | None:
    """从 DLL 抽取 .g.resources 容器本体, 返回文件路径。"""
    exe = APP_ROOT / "bin" / "v6res.exe"
    dst = outdir / "container.bin"
    try:
        p = subprocess.run(
            [str(exe), "container", str(dll), str(dst)],
            capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode == 0 and dst.exists():
            return dst
    except Exception:
        pass
    return None



def describe_write_problem(path: Path) -> str:
    """给出针对性的、可执行的错误说明。"""
    ok, why = can_write(path)
    if ok:
        return ""
    if why == "missing":
        return f"目标文件不存在:\n{path}"
    if why == "locked":
        return ("VOCALOID6.dll 正被其他程序占用。\n\n"
                "请完全退出以下程序后重试:\n"
                "  · VOCALOID6 编辑器\n"
                "  · 任何加载了 VOCALOID6 插件的 DAW\n"
                "    (Cubase / Studio One / FL Studio 等)\n\n"
                "可在任务管理器中确认没有 VOCALOID6.exe 残留进程。")
    # denied
    if is_admin():
        return ("无法写入 VOCALOID6.dll。\n\n"
                "当前已是管理员权限, 但仍被拒绝。\n"
                "可能原因: 文件被安全软件锁定, 或 ACL 异常。")
    return ("需要管理员权限。\n\n"
            "VOCALOID6.dll 位于 C:\\Program Files\\ 下,\n"
            "该目录受 Windows 保护, 普通账户无法写入。\n\n"
            "解决办法: 关闭本工具, 然后右键点击\n"
            "V6PAC 的启动方式 -> 「以管理员身份运行」。")


# ---------------------------------------------------------------- 信息读取

@dataclass
class DllInfo:
    path: Path
    file_size: int
    has_cert: bool
    resource_count: int
    sizes: dict[str, int] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)
    capacities: dict[str, int] = field(default_factory=dict)

    def size_of(self, key: str) -> int | None:
        return self.sizes.get(key)

    def hash_of(self, key: str) -> str | None:
        return self.hashes.get(key)

    def capacity_of(self, key: str) -> int | None:
        return self.capacities.get(key)


def read_info(dll: Path) -> DllInfo:
    """读取 DLL 资源信息。"""
    raw = _run_v6res(["info", str(dll)])
    info = DllInfo(
        path=dll,
        file_size=int(raw.get("fileSize", 0)),
        has_cert=bool(raw.get("hasCertTable", False)),
        resource_count=int(raw.get("resourceCount", 0)),
    )
    for key in ("splash", "splashdev", "icon"):
        if f"{key}Size" in raw:
            info.sizes[key] = int(raw[f"{key}Size"])
        if f"{key}Sha256" in raw:
            info.hashes[key] = str(raw[f"{key}Sha256"])
        if f"{key}Capacity" in raw:
            info.capacities[key] = int(raw[f"{key}Capacity"])
    return info


def verify_dll(dll: Path) -> tuple[bool, list[str]]:
    """校验 DLL 资源容器是否完整。返回 (是否OK, 缺失项)。"""
    try:
        raw = _run_v6res(["verify", str(dll)])
        return bool(raw.get("ok")), list(raw.get("missing", []))
    except V6PacError:
        return False, ["<校验失败>"]


# ---------------------------------------------------------------- 备份

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_path_for(dll: Path) -> Path | None:
    """
    查找与**当前 DLL 版本匹配**的备份，找不到时退回最新的一份。

    曾经这里只做 sorted(...)[0]，也就是按字母序取第一个。备份命名同时包含
    版本号和时间戳，于是结果取决于字符串比较：'6.13.0.1...' 排在中文名的
    '圆角测试前...' 前面, 还原就把一个更老的版本拷了回去 —— 启动画面右下角
    的版本号随之从 6.13.3 变成 6.13.0(实测踩过)。

    现在的规则:
      1. 优先选版本号与当前 DLL 一致的备份(FileVersion 从 PE 资源读, 不靠文件名)
      2. 同版本多份时选最新时间戳的
      3. 一个都匹配不上时选最新时间戳的, 并让调用方知道
    """
    cands = list(DIR_BACKUP.glob(f"{dll.name}.*.bak"))
    if not cands:
        return None

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    # 按写入时间从新到旧
    cands.sort(key=mtime, reverse=True)

    cur = file_version(dll)
    if cur:
        for c in cands:
            if file_version(c) == cur:
                return c

    return cands[0]

def file_version(dll: Path) -> str | None:
    """
    读 PE 的 VS_FIXEDFILEINFO, 返回像 '6.13.3.1' 的版本号, 失败返回 None。

    为什么不用 v6res: 它的 info 输出里**没有**版本字段(只有尺寸/哈希/资源数),
    所以读它永远拿不到版本 —— 这正是第一版 backup_path_for 静默退化成
    "随便挑一个"的原因。

    也不用文件名: 用户会手工改名(本机就有一份叫 '圆角测试前' 的备份),
    名字里的版本号不可信。

    实现是纯 struct 解析, 不依赖 pefile / pywin32 —— 这两个在目标机上都没有。
    """
    try:
        with open(dll, "rb") as f:
            data = f.read(1024)
            if data[:2] != b"MZ":
                return None
            pe_off = struct.unpack_from("<I", data, 0x3C)[0]
            f.seek(pe_off)
            if f.read(4) != b"PE\0\0":
                return None
            f.read(2)
            num_sec = struct.unpack("<H", f.read(2))[0]
            f.read(12)
            opt_size = struct.unpack("<H", f.read(2))[0]
            f.read(2)
            opt_off = f.tell()
            magic = struct.unpack("<H", f.read(2))[0]
            if magic not in (0x10B, 0x20B):
                return None
            dd_off = opt_off + (112 if magic == 0x20B else 96)
            f.seek(dd_off + 2 * 8)              # 数据目录[2] = 资源表
            rva, _size = struct.unpack("<II", f.read(8))
            if rva == 0:
                return None

            f.seek(opt_off + opt_size)          # 节表紧跟可选头
            sections = []
            for _ in range(num_sec):
                raw = f.read(40)
                if len(raw) < 40:
                    break
                vsz, vrva, rsz, roff = struct.unpack_from("<IIII", raw, 8)
                sections.append((vrva, max(vsz, rsz), roff))

            def rva2off(va):
                for vrva, span, roff in sections:
                    if vrva <= va < vrva + span:
                        return roff + (va - vrva)
                return None

            base = rva2off(rva)
            if base is None:
                return None

            def entries(off):
                f.seek(off)
                hdr = f.read(16)
                if len(hdr) < 16:
                    return []
                nnamed, nid = struct.unpack_from("<HH", hdr, 12)
                out = []
                for i in range(nnamed + nid):
                    f.seek(off + 16 + i * 8)
                    nm, target = struct.unpack("<II", f.read(8))
                    out.append((nm, target))
                return out

            # 资源树固定三层: 类型 -> 名字 -> 语言, 第 3 层才是数据项。
            #
            # 注意不要把"高位是 1"当成"跳过": 前两层的条目按定义都是子目录,
            # 那个标志位正是它们存在的意思。第一版在这里 `continue`, 结果
            # 一个条目都没进去, file_version 永远返回 None —— 而调用方把
            # None 当成"版本未知", 于是备份选择静默退化成随便挑一个。
            for nm, t1 in entries(base):                 # 层 1: 类型
                if nm != 16 or not (t1 & 0x80000000):    # RT_VERSION = 16
                    continue
                lvl1 = base + (t1 & 0x7FFFFFFF)
                for _n2, t2 in entries(lvl1):            # 层 2: 名字
                    if not (t2 & 0x80000000):
                        continue
                    lvl2 = base + (t2 & 0x7FFFFFFF)
                    for _n3, t3 in entries(lvl2):        # 层 3: 语言
                        if t3 & 0x80000000:
                            continue                     # 这一层若是目录则无数据
                        leaf = base + (t3 & 0x7FFFFFFF)
                        f.seek(leaf)
                        d_rva, d_size, _, _ = struct.unpack("<IIII", f.read(16))
                        doff = rva2off(d_rva)
                        if doff is None:
                            continue
                        f.seek(doff)
                        blob = f.read(d_size)
                        i = blob.find(b"\xbd\x04\xef\xfe")   # VS_FIXEDFILEINFO
                        if i >= 0:
                            _, _, ms, ls = struct.unpack_from("<IIII", blob, i)
                            return (f"{ms >> 16}.{ms & 0xFFFF}."
                                    f"{ls >> 16}.{ls & 0xFFFF}")
            return None
    except Exception:
        return None


def ensure_backup(dll: Path, *, force: bool = False,
                  reason: str = "manual") -> tuple[Path | None, str]:
    """
    备份当前 DLL。

    规则(2026-10 改版):
      * **每次调用都真的写一份**, 不再"已有备份就跳过"。这样每换一次封面
        都留下上一版的状态, 可以回退。
      * 首次遇到原版(签名有效)时, 它自然就是一份原版备份 —— 原版备份永不删除。
      * 改过的版本也照备份, 由 trim_backups() 负责只保留最近若干份。

    reason 写进文件名, 供备份列表显示来源:
      apply    应用封面之前
      upgrade  VOCALOID 升级之前
      manual   用户手动

    返回值第二个元素是给界面看的说明。
    """
    if not dll.is_file():
        raise V6PacError(f"目标文件不存在: {dll}")

    try:
        # 版本号从 PE 资源读, 文件名里带上真实版本, 列表才能按版本分组。
        ver = file_version(dll) or "unknown"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        digest = _sha256_file(dll)[:8]
        dst = DIR_BACKUP / f"{dll.name}.{ver}.{ts}.{reason}.{digest}.bak"

        # 同一秒内重复调用会撞名, 加后缀防止互相覆盖
        n = 1
        while dst.is_file():
            dst = DIR_BACKUP / f"{dll.name}.{ver}.{ts}.{reason}.{digest}.{n}.bak"
            n += 1

        shutil.copy2(dll, dst)
        pristine = is_pristine(dll)
        log(f"已备份{'原版' if pristine else '当前状态'} -> {dst}")

        # 备份完顺手清理超额的"改过的"备份(原版不计入、不删除)
        removed = trim_backups()
        extra = f"; 清理了 {removed} 份旧备份" if removed else ""
        return dst, f"已备份{'原版' if pristine else '当前状态'}: {dst.name}{extra}"
    except Exception as e:
        raise V6PacError(f"创建备份失败: {e}")


# 改过的备份最多留几份。原版备份不计入这个数, 也永不删除。
KEEP_MODIFIED = 10


def is_original_backup(path: Path) -> bool:
    """签名有效 = 官方原版, 不可删除。"""
    try:
        kind, _ = signature_status(path)
        return kind == "Valid"
    except Exception:
        return False


def trim_backups(keep: int = KEEP_MODIFIED) -> int:
    """
    删除超额的非原版备份, 返回删除数量。

    只删"改过的"备份(签名无效)。原版备份无论多少都保留 —— 它是升级前
    还原唯一的可靠来源, 删掉就再也拿不回来了。
    """
    removed = 0
    try:
        modified = []
        for p in DIR_BACKUP.glob("*.bak"):
            if is_original_backup(p):
                continue
            try:
                modified.append((p.stat().st_mtime, p))
            except OSError:
                continue
        modified.sort(reverse=True)          # 新的在前
        for _, p in modified[keep:]:
            try:
                p.unlink()
                removed += 1
                log(f"清理旧备份: {p.name}")
            except OSError:
                pass
    except Exception as e:
        log(f"trim_backups 失败: {e}")
    return removed


def delete_backup(path: Path) -> tuple[bool, str]:
    """
    删除一份备份。原版(签名有效)拒绝删除。

    返回 (是否成功, 说明)。
    """
    p = Path(path)
    if not p.is_file():
        return False, "备份文件不存在"
    if is_original_backup(p):
        return False, ("这是官方原版备份，不能删除。\n"
                       "它是升级前还原唯一可靠的来源。")
    try:
        p.unlink()
        log(f"已删除备份: {p.name}")
        return True, f"已删除: {p.name}"
    except Exception as e:
        return False, f"删除失败: {e}"


@dataclass
class BackupInfo:
    """备份列表里的一行。"""
    path: Path
    version: str            # PE 版本号, 读不到时为 "unknown"
    created: datetime | None
    size: int
    reason: str             # apply / upgrade / manual / unknown
    is_current_version: bool = False   # 与当前 DLL 版本是否一致

    @property
    def reason_label(self) -> str:
        return {"apply": "应用前", "upgrade": "升级前",
                "manual": "手动"}.get(self.reason, "未知")

    @property
    def size_label(self) -> str:
        mb = self.size / (1024 * 1024)
        return f"{mb:.2f} MB"


def list_backups(dll: Path | None = None) -> list[BackupInfo]:
    """
    列出全部备份, 按时间从新到旧。

    解析文件名 `<dll>.<版本>.<时间戳>.<来源>.<摘要>.bak`。早期版本没有
    来源段(文件名是 `<dll>.<版本>.<时间戳>.<摘要>.bak`), 那时按 unknown
    处理 —— 不能因为改了命名规则就让旧备份从列表里消失。

    版本号优先读 PE 资源(可信); 读不出来才退回文件名里的那一段。
    """
    out: list[BackupInfo] = []
    try:
        files = sorted(DIR_BACKUP.glob("*.bak"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return out

    cur_ver = file_version(dll) if dll else None

    for p in files:
        try:
            st = p.stat()
            parts = p.name.split(".")
            # 文件名以 .bak 结尾; 倒数第二段是摘要, 往常才是来源/时间戳
            stem = p.name[:-4] if p.name.endswith(".bak") else p.name
            stem = stem[len(p.stem.split(".")[0]) + 1:] if "." in stem else stem
            seg = stem.split(".")
            version = "unknown"
            reason = "unknown"
            created = None
            # 时间戳格式 YYYYMMDD-HHMMSS, 找它来确定各段含义
            ts_idx = None
            for i, s in enumerate(seg):
                if len(s) == 15 and s[8] == "-" and s[:8].isdigit():
                    ts_idx = i
                    break
            if ts_idx is not None:
                try:
                    created = datetime.strptime(seg[ts_idx], "%Y%m%d-%H%M%S")
                except ValueError:
                    created = None
                if ts_idx >= 1:
                    version = seg[ts_idx - 1]
                if ts_idx + 1 < len(seg) and seg[ts_idx + 1] in (
                        "apply", "upgrade", "manual"):
                    reason = seg[ts_idx + 1]
            else:
                created = datetime.fromtimestamp(st.st_mtime)

            real = file_version(p)
            if real:
                version = real

            out.append(BackupInfo(
                path=p,
                version=version,
                created=created or datetime.fromtimestamp(st.st_mtime),
                size=st.st_size,
                reason=reason,
                is_current_version=bool(cur_ver) and version == cur_ver,
            ))
        except Exception:
            continue
    return out


def restore_backup(dll: Path, backup: Path | None = None) -> str:
    """从备份还原 DLL。"""
    bk = backup or backup_path_for(dll)
    if not bk or not bk.is_file():
        raise V6PacError("没有可用的备份文件。")
    if not dll.is_file():
        raise V6PacError(f"目标文件不存在: {dll}")
    try:
        shutil.copy2(bk, dll)
    except PermissionError:
        raise V6PacError(describe_write_problem(dll) or "写入被拒绝。")
    except Exception as e:
        raise V6PacError(f"还原失败: {e}")
    log(f"已从备份还原: {bk.name}")
    return f"已还原为备份: {bk.name}"


# ------------------------------------------------------------ 升级前还原

UPGRADE_FLAG = DIR_STATE / "upgrade_pending.flag"


def prepare_for_upgrade(dll: Path) -> tuple[bool, str]:
    """
    升级 VOCALOID6 前把 DLL 还原成原版。

    为什么需要这一步:
      MSI 在升级时会先卸载旧版本, 期间会校验/处理已安装的文件。
      若 VOCALOID6.dll 被本工具替换过 (大小改变、签名失效),
      虽然通常不影响, 但为消除变量, 升级前还原成原版最稳妥。

      同时记录一个标记, 升级完成后可提示用户重新应用封面。

    返回 (是否需要还原, 说明)。
    """
    if not dll.is_file():
        raise V6PacError(f"目标文件不存在: {dll}")

    # 已经是原版 -> 无需还原
    st, _ = signature_status(dll)
    if st == "Valid":
        return False, "当前 DLL 已是原版, 无需还原。"

    # 这里要的是"能还给安装包一个原版 DLL", 所以必须挑**签名有效**的备份。
    #
    # 不能用 backup_path_for(): 它按"与当前 DLL 同版本"来选, 而当前 DLL
    # 恰好是被改过的 —— 于是它会把另一份同样被改过、签名同样失效的备份
    # 拷回去(本机实测: 6.13.3.1 那份"圆角测试前"也是 NotSigned)。
    # 还原前后都是非原版, 这一步就白做了。
    #
    # 顺序: 先按版本匹配找有效签名的, 再退到任何版本的有效签名备份。
    cur_ver = file_version(dll)
    cands = [b for b in list_backups(dll) if b.path.is_file()]
    verified = []
    for b in cands:
        try:
            s, _ = signature_status(b.path)
        except Exception:
            s = None
        if s == "Valid":
            verified.append(b)

    bk = None
    for b in verified:
        if cur_ver and b.version == cur_ver:
            bk = b.path
            break
    if bk is None and verified:
        # 同版本没有原版时, 用任意一个原版也比还原成改过的版本强;
        # 版本不同会在返回消息里说明, 由用户决定是否继续升级。
        bk = verified[0].path

    if bk is None:
        raise V6PacError(
            "需要还原, 但备份里没有**原版**(签名有效)的 DLL。\n\n"
            "现有的备份都是被修改过的, 拷回去仍然是改过的文件, "
            "对升级没有帮助。\n"
            "建议先手动从 VOCALOID6 安装包修复安装。")

    msg = restore_backup(dll, bk)
    clear_applied()

    # 说明还原的是哪一份, 以及版本是否和原来一致 —— 用户需要知道升级
    # 面对的 DLL 是不是同一个版本。
    bk_ver = file_version(bk)
    note = f"\n还原自: {bk.name}"
    if bk_ver and cur_ver and bk_ver != cur_ver:
        note += (f"\n注意: 这份备份是 {bk_ver}, 而还原前的 DLL 是 {cur_ver}。"
                 f"\n同版本没有原版备份, 只能退回更早的原版。")

    # 记录"曾经应用过封面", 升级后好提示重新应用
    state = load_state()
    last = state.get("last_cover") or {}
    cover_file = last.get("file") if isinstance(last, dict) else None
    # 兜底: 直接看自定义目录里有没有保存过的封面
    if not cover_file:
        fallback = DIR_CUSTOM / "last_cover.png"
        if fallback.is_file():
            cover_file = str(fallback)

    if cover_file and Path(cover_file).is_file():
        try:
            UPGRADE_FLAG.write_text(
                json.dumps({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "cover": str(cover_file)}, ensure_ascii=False),
                encoding="utf-8")
        except Exception as e:
            log(f"写入升级标记失败: {e}")

    return True, f"{msg}{note}\n可以开始安装 VOCALOID6 新版了。"


def pending_upgrade_restore() -> dict[str, Any] | None:
    """检查是否有"升级前还原过、待重新应用封面"的情况。"""
    if not UPGRADE_FLAG.is_file():
        return None
    try:
        data = json.loads(UPGRADE_FLAG.read_text(encoding="utf-8"))
    except Exception:
        clear_upgrade_flag()
        return None
    if not isinstance(data, dict):
        clear_upgrade_flag()
        return None

    cover = data.get("cover")
    # 容错: cover 必须是字符串路径且文件存在
    if isinstance(cover, dict):
        cover = cover.get("file")
    if not isinstance(cover, str) or not cover or not Path(cover).is_file():
        # 兜底: 自定义目录里是否有保存过的封面
        fallback = DIR_CUSTOM / "last_cover.png"
        if fallback.is_file():
            data["cover"] = str(fallback)
            return data
        clear_upgrade_flag()
        return None
    data["cover"] = cover
    return data


def clear_upgrade_flag() -> None:
    try:
        UPGRADE_FLAG.unlink()
    except Exception:
        pass


# ------------------------------------------------------ 记住上次的封面

def remember_cover(cover_png: Path, meta: dict[str, Any] | None = None) -> None:
    """保存本次使用的封面, 供升级后一键重应用。"""
    state = load_state()
    dst = DIR_CUSTOM / "last_cover.png"
    try:
        shutil.copy2(cover_png, dst)
    except Exception as e:
        log(f"保存上次封面失败: {e}")
        return
    state["last_cover"] = {
        "file": str(dst),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "meta": meta or {},
    }
    save_state(state)


def last_cover() -> Path | None:
    """取回上次使用的封面图。"""
    state = load_state()
    lc = state.get("last_cover", {})
    p = Path(lc.get("file", "")) if lc.get("file") else None
    if p and p.is_file():
        return p
    return None


# ---------------------------------------------------------------- 状态

@dataclass
class Status:
    state: str            # pristine / applied / other / unknown
    label: str            # 给用户看的中文描述
    detail: str = ""


def load_state() -> dict[str, Any]:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(data: dict[str, Any]) -> None:
    try:
        STATE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"写入状态失败: {e}")


def detect_status(dll: Path, info: DllInfo | None = None) -> Status:
    """
    判定当前封面状态:
      pristine —— 签名有效, 原版未改
      applied  —— 封面哈希与本工具记录的上次应用值一致
      other    —— 文件被改过, 但不是本工具改的 (例如厂商更新 / 其他工具)
    """
    try:
        info = info or read_info(dll)
    except V6PacError as e:
        return Status("unknown", "无法读取 DLL 信息", str(e))

    st, desc = signature_status(dll)
    cur = info.hash_of("splash")

    if st == "Valid":
        # 原版。但如果之前升级前还原过、且用户曾用过封面, 提示可重新应用。
        pend = pending_upgrade_restore()
        if pend:
            return Status("pristine", "原版 (升级已完成)",
                          "检测到你在升级前还原了 DLL。\n"
                          "升级已完成, 可以重新应用上次的封面。")
        return Status("pristine", "原版 (未应用替换)", desc)

    state = load_state()
    rec = state.get("applied", {})
    rec_hash = rec.get("splash_sha256")
    rec_ver = rec.get("dll_size")

    if rec_hash and cur == rec_hash:
        return Status("applied", "已应用替换", f"封面哈希与本工具记录一致")

    if rec_ver and int(rec_ver) != info.file_size:
        return Status("other", "检测到版本变化",
                      "DLL 大小与上次应用时不同, 可能被 VOCALOID6 更新覆盖。\n"
                      "建议重新应用封面。")

    return Status("other", "文件已被修改 (非本工具)",
                  "签名已失效, 但封面哈希与本工具记录不符。\n"
                  "可能是其他工具修改, 或之前应用过不同的图。")


def record_applied(dll: Path, info: DllInfo, note: str = "") -> None:
    """记录本次应用, 供后续状态检测。"""
    state = load_state()
    state["applied"] = {
        "dll": str(dll),
        "dll_size": info.file_size,
        "splash_sha256": info.hash_of("splash"),
        "splashdev_sha256": info.hash_of("splashdev"),
        "icon_sha256": info.hash_of("icon"),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": note,
    }
    save_state(state)


def clear_applied() -> None:
    state = load_state()
    state.pop("applied", None)
    save_state(state)


# ---------------------------------------------------------------- 应用

@dataclass
class ApplyResult:
    ok: bool
    mode: str = ""                 # inplace / rebuild
    output: Path | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def apply_cover(
    dll: Path,
    *,
    splash: Path | None = None,
    splashdev: Path | None = None,
    icon: Path | None = None,
    force_rebuild: bool = False,
) -> ApplyResult:
    """
    应用封面替换。直接写入目标 DLL (会先自动备份)。

    优先尝试原地替换 (零 PE 改动, 最安全); 若超出容量则自动改用重建模式。
    """
    targets: list[str] = []
    if splash:
        targets.append(f"splash={splash}")
    if splashdev:
        targets.append(f"splashdev={splashdev}")
    if icon:
        targets.append(f"icon={icon}")
    if not targets:
        raise V6PacError("没有指定任何要替换的内容。")

    # 1) 备份 —— 每次应用前都把当前状态存一份, 这样能回退到上一个封面。
    # (旧版是"已有备份就跳过", 结果换第二次封面时没有上一版可退。)
    bk, bk_msg = ensure_backup(dll, reason="apply")
    log(bk_msg)

    info_before = read_info(dll)

    # 2) 决定模式
    mode = "rebuild" if force_rebuild else "inplace"
    if not force_rebuild:
        # 检查是否超出各条目容量
        need_rebuild = False
        for key, path in (("splash", splash), ("splashdev", splashdev),
                          ("icon", icon)):
            if not path:
                continue
            cap = info_before.capacity_of(key) or 0
            size = path.stat().st_size
            if size > cap:
                log(f"{key}: {size:,} 字节 > 容量 {cap:,}, 需要重建模式")
                need_rebuild = True
        if need_rebuild:
            mode = "rebuild"

    # 3) 写到临时文件, 成功后再替换 (避免中途失败损坏目标)
    tmp = DIR_OUTPUT / f"_tmp_{dll.name}"
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass

    args = ["replace", str(dll), str(tmp)]
    if mode == "rebuild":
        args.append("--rebuild")
    args.extend(targets)

    try:
        raw = _run_v6res(args)
    except V6PacError as e:
        return ApplyResult(False, mode, None, str(e))

    # 4) 校验产物: 资源完整性 + WPF 资源路径
    ok, missing = verify_dll(tmp)
    if not ok:
        return ApplyResult(False, mode, tmp,
                           f"生成的文件校验未通过, 缺失: {missing}")

    wpf_ok, wpf_msg = verify_wpf(tmp)
    if not wpf_ok:
        # 这一步失败意味着 VOCALOID6 会启动崩溃 —— 绝不写入目标
        return ApplyResult(
            False, mode, tmp,
            "生成的文件未通过 WPF 资源加载检查, 已中止写入。\n\n"
            "这是为了防止 VOCALOID6 启动失败。\n\n"
            f"详情:\n{wpf_msg}")

    # 5) 覆盖目标
    try:
        shutil.copy2(tmp, dll)
    except PermissionError:
        return ApplyResult(False, mode, tmp,
                           describe_write_problem(dll) or "写入被拒绝。")
    except Exception as e:
        return ApplyResult(False, mode, tmp, f"写入失败: {e}")

    # 6) 记录状态
    info_after = read_info(dll)
    record_applied(dll, info_after, note=f"mode={mode}")

    # 记住这次用的封面, 供升级后一键重应用
    if splash and Path(splash).is_file():
        remember_cover(Path(splash), {"mode": mode})
    # 成功应用即清除"升级待重应用"标记
    clear_upgrade_flag()

    return ApplyResult(
        True, mode, dll,
        f"应用成功 ({'重建模式' if mode == 'rebuild' else '原地替换'})",
        dict(raw),
    )


def restore_default(dll: Path) -> ApplyResult:
    """
    恢复为预设的零售版封面。
    若存在原版备份且当前 DLL 除封面外无其他改动需求, 直接还原备份最干净。
    """
    preset = preset_dir_for(dll) / "splash.png"
    if not preset.is_file():
        # 该版本还没导出过, 现导一次
        export_presets(dll)
    if not preset.is_file():
        raise V6PacError(
            f"缺少预设封面: {preset}\n"
            "请先运行一次「导出默认封面」。")

    return apply_cover(dll, splash=preset)


def preset_dir_for(dll: Path) -> Path:
    """
    某个 DLL 的默认封面目录: 预设\\<版本>\\

    为什么按版本分开: 切换目标 DLL 时不能把另一份的封面当成"默认"覆盖过来。
    本机 C 盘是 6.13.3.1、E 盘是 6.13.0.1, 两份的官方封面不同, 混在一个
    目录里会让"载入默认封面"给出错误的那一张。
    """
    ver = file_version(dll) or "unknown"
    safe = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in ver)
    return DIR_PRESET / safe


def export_presets(dll: Path) -> list[dict[str, Any]]:
    """从 DLL 导出默认封面到该版本自己的预设目录。"""
    target = preset_dir_for(dll)
    target.mkdir(parents=True, exist_ok=True)
    raw = _run_v6res(["extract", str(dll), str(target)])
    return raw if isinstance(raw, list) else []
