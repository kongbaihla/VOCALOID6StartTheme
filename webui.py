# -*- coding: utf-8 -*-
"""
V6PAC WebView2 界面
====================
界面层用 HTML/CSS/JS, 逻辑层直接复用 v6pac_core / v6pac_image, 一行不改。

结构:
    web/index.html      界面
    web/app.js          交互 + 调后端
    web/style.css       样式
    webui.py            Python 侧的 js_api 桥 + 窗口

为什么换成 WebView2: tkinter 的观感受限于它的绘制模型(没有真圆角、没有
抗锯齿、没有阴影), 而同样的界面用 HTML/CSS 写出来接近原生应用的观感。
代价是多一个 pywebview 依赖(它调用系统自带的 WebView2 运行时)。
"""
from __future__ import annotations

import base64
import io
import json
import sys
import traceback
from pathlib import Path

# 打包成 exe 后 __file__ 在临时解压目录里。资源(web/、bin/)跟着 _MEIPASS 走,
# 可写数据和 exe 放一起 —— 与 v6pac_core 里的 RES_ROOT / APP_ROOT 保持同一套规则。
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from v6pac_core import RES_ROOT as HERE_RES, APP_ROOT as HERE_DATA  # noqa: E402

import v6pac_core as core      # noqa: E402
import v6pac_image as vimg     # noqa: E402


def _b64_png(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _b64_preview(img, quality: int = 82) -> str:
    """
    预览用的 base64。用 JPEG 而不是 PNG。

    实测同样一张 520x320 的封面预览: PNG 约 150 KB, JPEG(q82) 约 18 KB。
    每次拖动/缩放都要把这段串从 Python 送到页面, 8 倍的体积差直接体现在
    跟手程度上。预览只是给人看构图, JPEG 的损失在这里不可见; 真正写进
    DLL 的仍然是 _final_image() 出来的无损 PNG, 不受这里影响。
    """
    buf = io.BytesIO()
    im = img
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _b64_file(path) -> str:
    """把已存在的图片文件转成 data URI。用于缓存好的缩略图。"""
    data = Path(path).read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


class Api:
    """暴露给 JS 的接口。webview 会把公共方法挂到 window.pywebview.api 下。

    ⚠️ 不能把 Window 对象存成公共属性。
    pywebview 会走查 js_api 对象的属性做序列化, 一旦存在 api.window -> win
    且 win 又能回到 api 的引用, 就会无限递归并让整个窗口 "未响应":
        Error while processing window.native.AccessibilityObject.Bounds...
        .Empty.Empty.Empty...: maximum recursion depth exceeded
    所以窗口引用放在 **私有属性** _win 里(下划线开头, 不会被当作公开 API 暴露),
    取文件对话框时通过它调用。
    """

    def __init__(self) -> None:
        self.dll: Path | None = None
        self.info: core.DllInfo | None = None
        self.src_path: Path | None = None
        self.src_image = None
        self.src_preview = None     # 缩小后的副本, 只用于实时预览
        self.view = None            # vimg.CropView
        self.corner = 0.0           # 圆角百分比(0 = 关闭)
        self._win = None

    # 实时预览用的工作分辨率。
    # 实测 4480x6294 的原图每次 render_crop 要 65ms, 加上缩图与编码约 80-90ms,
    # 松手后的更新有明显停顿; 先缩到长边 1600 再裁剪只要 30ms, 快 3 倍。
    # 这只影响预览 —— apply() 用的是 _final_image(), 仍然从原图渲染。
    PREVIEW_MAX_SIDE = 1600

    # ---------------------------------------------------------- 状态
    def bootstrap(self) -> dict:
        """启动时调用一次: 找 DLL、读信息、生成预设。"""
        out: dict = {"ok": False}
        try:
            # 先列全部候选: 本机同时存在 C 盘的 6.13.3.1 和 E 盘的 6.13.0.1,
            # 静默取第一个容易改错对象, 所以把候选一起交给界面。
            self.candidates = core.discover_dlls()
            if not self.candidates:
                out["error"] = "未找到 VOCALOID6.dll"
                out["candidates"] = []
                return out

            self.dll = Path(self.candidates[0]["path"])
            try:
                core.export_presets(self.dll)
            except Exception:
                pass
            out = self.state()
            out["ok"] = True
            out["candidates"] = self.candidates
            return out
        except Exception as e:
            out["error"] = str(e)
            return out

    def choose_dll(self, path: str) -> dict:
        """切换到另一个候选 DLL。"""
        try:
            p = Path(path)
            if not p.is_file():
                return {"ok": False, "error": "文件不存在"}
            self.dll = p
            try:
                core.export_presets(p)
            except Exception:
                pass
            st = self.state()
            st["candidates"] = getattr(self, "candidates", [])
            st["ok"] = True
            return st
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def state(self) -> dict:
        """当前 DLL 的全部展示信息。"""
        if not self.dll:
            return {"ok": False, "error": "未选择 DLL"}
        try:
            self.info = core.read_info(self.dll)
            st = core.detect_status(self.dll, self.info)
            try:
                sig_kind, sig_text = core.signature_status(self.dll)
            except Exception:
                sig_kind, sig_text = "unknown", "未知"

            ok, why = core.can_write(self.dll)
            backups = core.list_backups(self.dll)
            return {
                "ok": True,
                "dllPath": str(self.dll),
                "dllSize": vimg.human_size(self.dll.stat().st_size),
                "splashSize": vimg.human_size(self.info.capacity_of("splash") or 0),
                "splashCapacity": vimg.human_size(self.info.capacity_of("splash") or 0),
                "version": core.file_version(self.dll) or "?",
                "statusLabel": st.label,
                "statusKind": st.state,
                "sigText": sig_text,
                "sigKind": sig_kind,
                "writable": ok,
                "writeReason": why,
                "isAdmin": core.is_admin(),
                "backupCount": len(backups),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------------------------------------------------- 选图
    def pick_image(self) -> dict:
        """打开系统文件对话框选图。"""
        try:
            import webview
            paths = self._win.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "图片 (*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif)",
                    "全部文件 (*.*)",
                ),
            )
            if not paths:
                return {"ok": False, "cancelled": True}
            return self.load_image_file(paths[0] if isinstance(paths, (list, tuple)) else paths)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_image_file(self, path: str) -> dict:
        try:
            img = vimg.load_image(path)
            self.src_image = img
            self.src_path = Path(path)
            # 预览副本: 长边超过 PREVIEW_MAX_SIDE 才缩, 小图直接用原图。
            if max(img.width, img.height) > self.PREVIEW_MAX_SIDE:
                self.src_preview = vimg.make_preview(
                    img, self.PREVIEW_MAX_SIDE, self.PREVIEW_MAX_SIDE)
            else:
                self.src_preview = img
            self.view = vimg.auto_view(img)

            # 左栏大图直接从预览副本再缩一次, 不要从 4480x6294 的原图缩 ——
            # 那一步实测要 1 秒(选完图后界面干等着), 从 1139x1600 缩只要几十毫秒,
            # 而这张图在屏幕上最终也就显示到 1200 宽, 观感没有区别。
            big = vimg.make_preview(self.src_preview, 1200, 1200)
            return {
                "ok": True,
                "name": Path(path).name,
                "width": img.width,
                "height": img.height,
                "preview": _b64_preview(big, 88),
                "crop": self._crop(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_default(self) -> dict:
        # 用当前目标 DLL 对应版本的预设, 而不是共用一份 ——
        # 换了目标之后"默认封面"应该是这个版本自己的官方图。
        p = core.preset_dir_for(self.dll) / "splash.png"
        if not p.is_file():
            try:
                core.export_presets(self.dll)
            except Exception:
                pass
        if not p.is_file():
            return {"ok": False, "error": "预设封面不存在"}
        return self.load_image_file(str(p))

    # ---------------------------------------------------------- 取景
    def _crop(self) -> dict | None:
        """
        取景状态交给前端。注意 CropView 用的是**中心点** cx/cy(原图归一化),
        前端需要在显示时换算成左上角, 否则取景框会偏移半个框。
        """
        if not self.src_image or not self.view:
            return None
        v = self.view
        return {"cx": v.cx, "cy": v.cy, "zoom": v.zoom}

    def set_crop(self, cx: float, cy: float, zoom: float) -> dict:
        """前端拖动/缩放后回传取景参数, 这里重算最终效果预览。"""
        if not self.src_image or not self.view:
            return {"ok": False}
        try:
            from v6pac_image import CropView
            v = CropView(cx=float(cx), cy=float(cy), zoom=float(zoom))
            v.clamp()
            self.view = v
            return {"ok": True, "effect": self._effect_b64(), "crop": self._crop()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def center(self) -> dict:
        if not self.src_image:
            return {"ok": False}
        self.view = vimg.auto_view(self.src_image)
        return {"ok": True, "effect": self._effect_b64(), "crop": self._crop()}

    def _final_image(self):
        """渲染 1200x714 的最终封面(含圆角)。用原图, 保证写入质量。"""
        if not self.src_image or not self.view:
            return None
        img = vimg.render_crop(self.src_image, self.view)
        return self._round(img)

    def _preview_image(self):
        """渲染预览用的最终封面。用缩图, 快 3 倍。"""
        src = self.src_preview or self.src_image
        if not src or not self.view:
            return None
        img = vimg.render_crop(src, self.view)
        return self._round(img)

    def _round(self, img):
        """
        按当前圆角设置挖角。

        标注"实验性"是有实测依据的: VOCALOID6 启动窗口不透明, alpha=0 的
        像素会被渲染成黑色而不是透出桌面, 所以四角看起来是黑的。是否要这个
        效果由用户在预览里自己判断 —— 预览里看到的就是最终的。
        """
        pct = float(getattr(self, "corner", 0) or 0)
        if pct <= 0:
            return img
        r = vimg.corner_radius_px(img.width, img.height, pct)
        if r <= 0:
            return img
        return vimg.apply_rounded_corners(img, r)

    def set_corner(self, percent: float) -> dict:
        """圆角滑块变化: 只重算预览。"""
        try:
            self.corner = max(0.0, min(8.0, float(percent)))
            return {
                "ok": True,
                "percent": self.corner,
                "px": (vimg.corner_radius_px(1200, 714, self.corner)
                       if self.corner > 0 else 0),
                "effect": self._effect_b64(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _effect_b64(self) -> str | None:
        img = self._preview_image()
        if img is None:
            return None
        # 预览只是看构图, 用 JPEG 换体积; 写入 DLL 的仍是无损 PNG。
        return _b64_preview(vimg.make_preview(img, 640, 380))

    def effect(self) -> dict:
        try:
            return {"ok": True, "effect": self._effect_b64()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------------------------------------------------- 备份
    def backups(self) -> dict:
        if not self.dll:
            return {"ok": False, "items": []}
        try:
            items = core.list_backups(self.dll)
            out = []
            for b in items:
                # 签名状态: 版本号相同的两条备份, 只有签名能分出哪个是真原版。
                # 不带这个, 界面上一行 v6.13.3.1 NotSigned、一行 v6.13.3.1 Valid
                # 长得一模一样, 用户没法选对。
                try:
                    sig_kind, _ = core.signature_status(b.path)
                except Exception:
                    sig_kind = "Unknown"
                out.append({
                    "path": str(b.path),
                    "name": b.path.name,
                    "version": b.version,
                    "reason": b.reason_label,
                    "size": b.size_label,
                    "created": b.created.strftime("%Y-%m-%d %H:%M:%S") if b.created else "?",
                    "isCurrent": b.is_current_version,
                    "sigKind": sig_kind,
                    "isOriginal": sig_kind == "Valid",
                    # 缩略图按需另取(见 backup_thumb), 列表一次拿全部会卡
                })
            return {
                "ok": True,
                "currentVersion": core.file_version(self.dll) or "?",
                "items": out,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "items": []}

    def delete_backup(self, path: str) -> dict:
        """删除一份备份。原版会被 core 拒绝。"""
        try:
            ok, msg = core.delete_backup(Path(path))
            return {"ok": ok, "message": msg, "items": self.backups()}
        except Exception as e:
            return {"ok": False, "message": str(e), "items": self.backups()}

    def backup_thumb(self, path: str) -> dict:
        """
        取某份备份里的启动封面小图。

        慢的原因: v6res 只能整目录导出, 一次约 535ms。所以结果**落盘缓存** ——
        备份文件不会变, 用它的 (大小 + 修改时间) 做键就够了。第二次起直接读缓存。
        """
        try:
            bk = Path(path)
            if not bk.is_file():
                return {"ok": False, "error": "备份不存在"}
            st = bk.stat()
            key = f"{bk.stem}.{st.st_size}.{int(st.st_mtime)}"
            safe = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in key)
            cache = core.DIR_OUTPUT / "_thumbs" / (safe + ".jpg")
            if cache.is_file():
                return {"ok": True, "thumb": _b64_file(cache), "cached": True}

            import subprocess
            import tempfile
            res = core.V6RES
            with tempfile.TemporaryDirectory() as td:
                subprocess.run([str(res), "extract", str(bk), td],
                               capture_output=True, timeout=60)
                src = Path(td) / "splash.png"
                if not src.is_file():
                    return {"ok": False, "error": "备份里没有封面"}
                img = vimg.load_image(str(src))
            small = vimg.make_preview(img, 240, 160)
            cache.parent.mkdir(parents=True, exist_ok=True)
            if small.mode not in ("RGB", "L"):
                small = small.convert("RGB")
            small.save(cache, format="JPEG", quality=80, optimize=True)
            return {"ok": True, "thumb": _b64_file(cache), "cached": False}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def restore(self, path: str) -> dict:
        try:
            msg = core.restore_backup(self.dll, Path(path))
            core.clear_applied()
            return {"ok": True, "message": msg, "state": self.state()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------------------------------------------------- 应用
    def apply(self) -> dict:
        if not self.src_image or not self.view:
            return {"ok": False, "error": "尚未选择图片"}
        try:
            ok, why = core.can_write(self.dll)
            if not ok:
                return {
                    "ok": False,
                    "needAdmin": (why == "denied" and not core.is_admin()),
                    "error": core.describe_write_problem(self.dll),
                }
            cover = self._final_image()
            tmp = core.DIR_OUTPUT / "web_cover.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            cover.save(tmp, format="PNG")
            core.ensure_backup(self.dll, reason="apply")
            res = core.apply_cover(self.dll, splash=tmp)
            core.remember_cover(tmp, {"mode": getattr(res, "mode", "")})
            return {"ok": True, "result": str(res), "state": self.state()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def elevate(self) -> dict:
        """
        以管理员身份重新启动本程序(UAC 提示), 成功后退出当前实例。

        为什么需要这个: VOCALOID6.dll 在 C:\\Program Files 下, 普通账户
        无权写入。旧版 tkinter 一启动就弹框问要不要提权, 每次打开都被挡一次;
        改成 WebView2 后是"点应用才需要权限", 所以提权入口必须摆在
        用户真的需要它的那一刻 —— 界面上就是应用失败时出现的那个按钮。

        返回 ok=False 且用户取消了 UAC 时, 调用方应保持界面不变。
        """
        import ctypes
        try:
            py = sys.executable
            # 打包成 exe 后 sys.executable 就是 exe 本身, 不能再传脚本路径;
            # 未打包时用解释器 + 脚本。
            if getattr(sys, "frozen", False):
                exe, params = py, ""
            else:
                exe, params = py, f'"{HERE / "webui.py"}"'
            # 工作目录固定在数据根, 让新实例读写同一套 备份/状态/日志
            cwd = str(HERE_DATA)

            # ShellExecuteW(runas) 会弹 UAC; 用户点"否"时返回 <= 32
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params, cwd, 1)
            if r <= 32:
                return {"ok": False, "cancelled": True,
                        "error": f"UAC 被取消或失败 (ShellExecuteW={r})"}
            # 新实例已经起来了, 老实例退出(稍等, 让新窗口先拿到前台)
            import threading

            def bye():
                import time
                time.sleep(0.6)
                try:
                    self._win.destroy()
                except Exception:
                    pass

            threading.Thread(target=bye, daemon=True).start()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def restore_default(self) -> dict:
        try:
            res = core.restore_default(self.dll)
            return {"ok": True, "result": str(res), "state": self.state()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def upgrade_prepare(self) -> dict:
        try:
            ok, msg = core.prepare_for_upgrade(self.dll)
            return {"ok": ok, "message": msg, "state": self.state()}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def main() -> int:
    import webview

    api = Api()
    index = HERE_RES / "web" / "index.html"
    # 尺寸按屏宽算, 不写死: 这台机器工作区 1707x1067, 原来固定 1000x700
    # 占掉近 60% 宽、66% 高, 界面本身内容不多, 显得空荡。取屏宽 56%
    # 并夹在 [820, 1180] 之间; 高度略矮一些, 让人一眼看出是个工具窗口。
    try:
        import ctypes

        class _R(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]

        _r = _R()
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(_r), 0)
        sw, sh = _r.r - _r.l, _r.b - _r.t
    except Exception:
        sw, sh = 1920, 1040

    # 上次关闭时的窗口位置尺寸(存在 状态/state.json), 命中就沿用
    saved = None
    try:
        saved = core.load_state().get("webwindow")
    except Exception:
        saved = None

    w = h = x = y = None
    if isinstance(saved, dict):
        try:
            sw0, sh0 = int(saved.get("w") or 0), int(saved.get("h") or 0)
            if 800 <= sw0 <= sw and 520 <= sh0 <= sh:
                w, h = sw0, sh0
                x0, y0 = saved.get("x"), saved.get("y")
                if isinstance(x0, int) and isinstance(y0, int) \
                        and -8 <= x0 < sw - 120 and -8 <= y0 < sh - 120:
                    x, y = x0, y0
        except Exception:
            w = h = None

    if w is None:
        w = int(min(max(sw * 0.54, 800), 1150))
        h = int(min(max(sh * 0.62, 520), 720))

    # 没有记录过位置(首次运行, 或上次的位置已不在屏内)就居中。
    # 用**工作区**而不是整屏: 整屏包含任务栏, 垂直居中会偏下一截,
    # 看着像"没居中"。工作区才是用户真正看到的可用区域。
    if x is None:
        try:
            wa_x, wa_y, wa_w, wa_h = 0, 0, sw, sh
            import ctypes

            class _WR(ctypes.Structure):
                _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                            ("r", ctypes.c_long), ("b", ctypes.c_long)]

            _wr = _WR()
            # SPI_GETWORKAREA = 48
            ctypes.windll.user32.SystemParametersInfoW(
                48, 0, ctypes.byref(_wr), 0)
            wa_x, wa_y = _wr.l, _wr.t
            wa_w, wa_h = _wr.r - _wr.l, _wr.b - _wr.t
            x = wa_x + max((wa_w - w) // 2, 0)
            y = wa_y + max((wa_h - h) // 2, 0)
        except Exception:
            x = max((sw - w) // 2, 0)
            y = max((sh - h) // 2, 0)

    kw = dict(
        title="VOCALOID6 启动封面替换工具",
        url=str(index),
        js_api=api,
        width=w, height=h,
        x=x, y=y,
        min_size=(740, 500),
        background_color="#16161a",
    )

    win = webview.create_window(**kw)
    api._win = win

    _install_geometry_save(win)
    webview.start(debug=False)
    return 0


def _install_geometry_save(win) -> None:
    """
    关闭前把窗口大小/位置写进 state.json。

    pywebview 没有"关闭前"回调, 这里挂到 closing 事件上; 拿不到事件就
    退化成定时采样 —— 每 2 秒记一次当前几何, 进程被直接结束也不会丢太多。
    两种方式都只是记录, 失败不影响程序。
    """
    def save():
        try:
            from webview.window import Window  # noqa: F401
        except Exception:
            pass
        try:
            ww, hh = win.width, win.height
            xx, yy = win.x, win.y
            st = core.load_state()
            st["webwindow"] = {"w": int(ww), "h": int(hh),
                               "x": int(xx), "y": int(yy)}
            core.save_state(st)
        except Exception:
            pass

    try:
        win.events.closed += lambda: save()
    except Exception:
        pass

    # 兜底: 定时记录。窗口没变就不重复写盘。
    import threading

    def loop():
        last = None
        while True:
            try:
                import time
                time.sleep(2.0)
                cur = (win.width, win.height, win.x, win.y)
                if cur != last:
                    last = cur
                    st = core.load_state()
                    st["webwindow"] = {"w": int(cur[0]), "h": int(cur[1]),
                                       "x": int(cur[2]), "y": int(cur[3])}
                    core.save_state(st)
            except Exception:
                return

    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
