# -*- coding: utf-8 -*-
"""
V6PAC —— VOCALOID6 启动封面替换工具 (GUI)
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v6pac_core as core
import v6pac_image as vimg
from PIL import Image

APP_TITLE = "VOCALOID6 启动封面替换工具"
APP_VER = "1.0"

BG = "#1e1e22"
BG2 = "#26262c"
FG = "#e8e8ea"
FG_DIM = "#9a9aa2"
ACCENT = "#4a9eff"
OK = "#4caf50"
WARN = "#ffb300"
ERR = "#ef5350"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE}  v{APP_VER}")
        self.configure(bg=BG)
        self.geometry("1000x860")
        self.minsize(900, 760)

        # --- 状态 ---
        self.dll: Path | None = None
        self.info: core.DllInfo | None = None
        self.src_image: Image.Image | None = None   # 用户选中的原图
        self.view: vimg.CropView | None = None      # 裁剪取景
        self.preview_photo = None
        self.result_png: bytes | None = None        # 最终封面 PNG
        self.result_lossless: bool = True
        self.warned_today = False                   # 签名警告每天一次

        # --- 性能相关 ---
        self.base = None            # 缩小后的底图 (用于快速预览)
        self.base_icon = None       # 保留引用, 防止 GC
        self._base_disp = None      # 底图对应的画布显示尺寸
        self._prev_key = None       # 预览缓存键 (fw, fh, box)
        self._heavy_job = None      # 延迟执行的重活 (PNG 编码)
        self._preview_job = None    # 延迟执行的预览重绘
        self._busy = False

        self._build_ui()
        self.after(60, self._startup)

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, fieldbackground=BG2)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Dim.TLabel", background=BG, foreground=FG_DIM)
        style.configure("Head.TLabel", background=BG, foreground=FG,
                        font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("TButton", background=BG2, foreground=FG, padding=6)
        style.map("TButton", background=[("active", "#34343c")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#357abd")])
        style.configure("TLabelframe", background=BG, foreground=FG)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT)
        style.configure("TEntry", fieldbackground=BG2, foreground=FG)

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # 布局原则: 先用 side="bottom" 占住底部 (状态栏 / 按钮栏 / 成效预览),
        # 中间剩余空间再交给可伸缩的画布区。这样窗口再小也不会挤掉按钮。

        # ---------- 状态栏 (最底) ----------
        self.var_msg = tk.StringVar(value="就绪")
        bar = tk.Label(root, textvariable=self.var_msg, bg=BG2, fg=FG_DIM,
                       anchor="w", padx=10, pady=4)
        bar.pack(fill="x", side="bottom")

        # ---------- 底部按钮栏 ----------
        bottom = ttk.Frame(root)
        bottom.pack(fill="x", side="bottom", pady=(8, 0))
        ttk.Button(bottom, text="还原默认封面",
                   command=self.on_restore_default).pack(side="left")
        ttk.Button(bottom, text="从备份还原",
                   command=self.on_restore_backup).pack(side="left", padx=(8, 0))
        self.btn_upgrade = ttk.Button(
            bottom, text="升级前还原", command=self.on_prepare_upgrade)
        self.btn_upgrade.pack(side="left", padx=(8, 0))
        ttk.Button(bottom, text="刷新状态",
                   command=self.refresh).pack(side="left", padx=(8, 0))
        self.btn_apply = ttk.Button(bottom, text="应用封面", style="Accent.TButton",
                                    command=self.on_apply, state="disabled")
        self.btn_apply.pack(side="right")

        # ---------- 顶部: DLL 信息 ----------
        box = ttk.LabelFrame(root, text=" 目标文件 ", padding=8)
        box.pack(fill="x", side="top")

        row = ttk.Frame(box); row.pack(fill="x")
        ttk.Label(row, text="VOCALOID6.dll:").pack(side="left")
        self.var_dll = tk.StringVar(value="检测中…")
        ttk.Label(row, textvariable=self.var_dll, style="Dim.TLabel").pack(
            side="left", padx=(6, 8), fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self.on_browse_dll).pack(side="right")

        row2 = ttk.Frame(box); row2.pack(fill="x", pady=(8, 0))
        self.lbl_status = ttk.Label(row2, text="状态: —", style="Head.TLabel")
        self.lbl_status.pack(side="left")
        self.lbl_sig = ttk.Label(row2, text="", style="Dim.TLabel")
        self.lbl_sig.pack(side="left", padx=(12, 0))

        row3 = ttk.Frame(box); row3.pack(fill="x", pady=(6, 0))
        self.lbl_sizes = ttk.Label(row3, text="", style="Dim.TLabel")
        self.lbl_sizes.pack(side="left")

        # ---------- 中部: 选择图片 (左) + 封面效果预览 (右) ----------
        mid = ttk.Frame(root)
        mid.pack(fill="both", expand=True, pady=(10, 0))

        left = ttk.LabelFrame(mid, text=" 选择图片 ", padding=8)
        left.pack(side="left", fill="both", expand=True)

        r = ttk.Frame(left); r.pack(fill="x")
        ttk.Button(r, text="选择图片…", command=self.on_pick_image,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(r, text="载入默认封面", command=self.on_load_default).pack(
            side="left", padx=(8, 0))
        ttk.Button(r, text="居中", command=self.on_center).pack(side="right")

        self.lbl_img = ttk.Label(left, text="尚未选择图片", style="Dim.TLabel")
        self.lbl_img.pack(anchor="w", pady=(6, 0))

        # 裁剪画布 (图片固定, 拖动取景框)
        self.canvas = tk.Canvas(left, bg="#101014", highlightthickness=1,
                                highlightbackground="#3a3a42")
        self.canvas.pack(fill="both", expand=True, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda e: self._on_canvas_resize())
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Button-1>", self._on_drag_start)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        # 缩放控制
        zr = ttk.Frame(left); zr.pack(fill="x", pady=(6, 0))
        ttk.Label(zr, text="缩放:").pack(side="left")
        self.var_zoom = tk.DoubleVar(value=1.0)
        sc = ttk.Scale(zr, from_=1.0, to=4.0, variable=self.var_zoom,
                       command=lambda *_: self._on_zoom_change())
        sc.pack(side="left", fill="x", expand=True, padx=(6, 6))
        ttk.Label(left, text="拖动取景框 · 滚轮缩放",
                  style="Dim.TLabel").pack(anchor="w")

        # ---------- 右侧: 封面效果预览 (放大) ----------
        eff = ttk.LabelFrame(mid, text=" 封面效果预览 ", padding=8)
        eff.pack(side="left", fill="both", expand=True, padx=(10, 0))

        ttk.Label(eff, text=f"{vimg.TARGET_W} × {vimg.TARGET_H}  (最终封面)",
                  style="Dim.TLabel").pack(anchor="w")

        self.canvas_eff = tk.Canvas(eff, bg="#101014", highlightthickness=1,
                                    highlightbackground="#3a3a42",
                                    width=460, height=280)
        self.canvas_eff.pack(fill="both", expand=True, pady=(6, 0))
        self.canvas_eff.bind("<Configure>", lambda e: self._schedule_effect(30))
        self.eff_photo = None
        self._eff_job = None

        # ---------- 底部: 输出信息 (全宽) ----------
        out = ttk.LabelFrame(root, text=" 输出 ", padding=8)
        out.pack(fill="x", side="bottom", pady=(10, 0))

        line1 = ttk.Frame(out); line1.pack(fill="x")
        ttk.Label(line1, text="写入方式:", style="Dim.TLabel").pack(side="left")
        self.lbl_mode = ttk.Label(line1, text="—")
        self.lbl_mode.pack(side="left", padx=(6, 0))

        ttk.Label(line1, text="　预计体积:", style="Dim.TLabel").pack(side="left")
        self.lbl_size = ttk.Label(line1, text="—",
                                  font=("Consolas", 11, "bold"))
        self.lbl_size.pack(side="left", padx=(6, 0))

        self.lbl_quality = ttk.Label(line1, text="")
        self.lbl_quality.pack(side="left", padx=(14, 0))

        ttk.Label(out, style="Dim.TLabel", justify="left",
                  text=("· 放得下时走「原地替换」(不重建 PE, 最安全); 放不下自动走"
                        "「重建模式」, 画质均无损\n"
                        "· 修改会使 Yamaha 签名失效, 但不影响 VOCALOID6 启动"
                        "(已实测确认)　· 首次应用前自动备份原文件")
                  ).pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------ 启动
    def _startup(self) -> None:
        try:
            self.dll = core.find_dll()
        except core.V6PacError as e:
            self.var_dll.set("未找到")
            self.var_msg.set("未找到 VOCALOID6.dll")
            messagebox.showerror(APP_TITLE, str(e))
            return
        self.var_dll.set(str(self.dll))

        # 权限检查: C:\Program Files 需要管理员权限才能写入
        self._check_permission()

        self.refresh()
        # 首次运行时导出默认封面
        try:
            if not (core.DIR_PRESET / "splash.png").is_file():
                core.export_presets(self.dll)
        except Exception:
            pass

        # 升级前还原过 -> 若升级已完成, 提示重新应用封面
        self.after(500, self._check_pending_upgrade)

    def _check_permission(self) -> None:
        """启动时检测写入权限, 权限不足则提示并可一键提权重启。"""
        if not self.dll:
            return
        ok, why = core.can_write(self.dll)
        self.can_write = ok
        self.write_problem = why

        if ok:
            return

        if why == "locked":
            self._set_msg("VOCALOID6.dll 被占用, 请退出 VOCALOID6", WARN)
            return

        if why == "denied" and not core.is_admin():
            self._set_msg("权限不足: 需要以管理员身份运行", WARN)
            self.after(400, self._ask_elevate)

    def _ask_elevate(self) -> None:
        msg = ("需要管理员权限\n\n"
               "VOCALOID6.dll 位于 C:\\Program Files\\ 下,\n"
               "该目录受 Windows 保护, 普通账户无法写入。\n\n"
               "是否以管理员身份重新启动本工具?\n"
               "(会弹出 UAC 授权窗口)")
        if messagebox.askyesno(APP_TITLE, msg):
            self._restart_elevated()
        else:
            self._set_msg("未提权 —— 「应用封面」将无法写入", WARN)

    def _restart_elevated(self) -> None:
        """用管理员权限重启自身。"""
        try:
            import ctypes
            script = str(Path(__file__).resolve())
            py = sys.executable
            # 用 ShellExecuteW 的 runas 触发 UAC
            params = f'"{script}"'
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", py, params,
                str(Path(script).parent), 1)
            if r <= 32:
                raise OSError(f"ShellExecuteW 返回 {r}")
            self.destroy()
        except Exception as e:
            messagebox.showerror(
                APP_TITLE,
                f"提权启动失败: {e}\n\n"
                "请手动操作: 关闭本窗口, 然后右键点击\n"
                "启动脚本或快捷方式 -> 「以管理员身份运行」。")
            self._set_msg("提权失败", ERR)

    # ------------------------------------------------------------ 刷新
    def refresh(self) -> None:
        if not self.dll:
            return
        try:
            self.info = core.read_info(self.dll)
        except core.V6PacError as e:
            self._set_msg(f"读取失败: {e}", ERR)
            return

        st = core.detect_status(self.dll, self.info)
        color = {"pristine": FG_DIM, "applied": OK,
                 "other": WARN}.get(st.state, FG)
        self.lbl_status.configure(text=f"状态: {st.label}", foreground=color)

        sig_state, sig_desc = core.signature_status(self.dll)
        self.lbl_sig.configure(
            text=f"签名: {'有效' if sig_state == 'Valid' else '已失效'}",
            foreground=OK if sig_state == "Valid" else WARN)

        sp = self.info.size_of("splash") or 0
        self.lbl_sizes.configure(
            text=f"当前封面 {vimg.human_size(sp)}   "
                 f"原地替换上限 {vimg.human_size(self.info.capacity_of('splash') or 0)}   "
                 f"文件 {vimg.human_size(self.info.file_size)}")

        self._update_output_panel()
        self._set_msg(st.detail or st.label)

    def _set_msg(self, text: str, color: str = FG_DIM) -> None:
        self.var_msg.set(text.replace("\n", " "))

    # ------------------------------------------------------------ 选图
    def on_browse_dll(self) -> None:
        p = filedialog.askopenfilename(
            title="选择 VOCALOID6.dll",
            filetypes=[("VOCALOID6.dll", "VOCALOID6.dll"), ("DLL", "*.dll")])
        if p:
            self.dll = Path(p)
            self.var_dll.set(str(self.dll))
            self.refresh()

    def on_pick_image(self) -> None:
        types = [("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
                 ("所有文件", "*.*")]
        p = filedialog.askopenfilename(title="选择封面图片", filetypes=types)
        if not p:
            return
        try:
            im = vimg.load_image(p)
        except vimg.ImageError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        self._set_source(im, Path(p).name)

    def on_load_default(self) -> None:
        p = core.DIR_PRESET / "splash.png"
        if not p.is_file():
            if not self.dll:
                messagebox.showerror(APP_TITLE, "尚未定位 VOCALOID6.dll。")
                return
            try:
                core.export_presets(self.dll)
            except core.V6PacError as e:
                messagebox.showerror(APP_TITLE, str(e))
                return
        if not p.is_file():
            messagebox.showerror(APP_TITLE, f"缺少默认封面: {p}")
            return
        self._set_source(vimg.load_image(p), "零售版默认封面")

    def _set_source(self, im: Image.Image, name: str) -> None:
        self.src_image = im
        self.view = vimg.auto_view(im)
        self.var_zoom.set(1.0)
        # 底图延后到首次绘制时按画布尺寸生成
        self.base = None
        self.base_icon = None
        self._base_disp = None
        self._prev_key = None
        self.lbl_img.configure(
            text=f"{name}   ({im.width} × {im.height})")
        self._set_msg("正在计算…")
        # 先让布局生效, 再按真实画布尺寸生成底图 (避免首帧用错尺寸)
        self.update_idletasks()
        self._draw_preview()
        self._schedule_effect(delay=10)
        self._schedule_heavy(delay=10)

    # ------------------------------------------------------------ 裁剪交互
    def _canvas_geom(self):
        """
        返回 (ox, oy, dw, dh, s):
          ox, oy —— 静态底图左上角在画布中的位置
          dw, dh —— 底图在画布上的显示尺寸
          s      —— 原图像素 -> 画布像素 的缩放
        """
        if not self.src_image:
            return None
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        iw, ih = self.src_image.size
        s = min(cw / iw, ch / ih)
        dw, dh = max(int(iw * s), 1), max(int(ih * s), 1)
        return (cw - dw) // 2, (ch - dh) // 2, dw, dh, s

    def _draw_preview(self, *, quick: bool = False) -> None:
        """
        绘制预览。

        交互模型: **图片固定不动, 移动的是取景框**。
        整张图片按"填满画布"缩放显示 (静态), 上面叠加一个 1200:714 比例的
        取景框; 拖动/滚轮改变取景框在原图上的位置与大小, 框内即最终封面。

        性能: 图片本身从不重采样, 只有取景框矩形在移动 -> 拖动时零开销。
        """
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)

        if not self.src_image or not self.view:
            self.canvas.create_text(cw // 2, ch // 2,
                                    text="选择图片后在此预览", fill="#55555c",
                                    font=("Microsoft YaHei UI", 11))
            return

        iw, ih = self.src_image.size

        # --- 1) 静态底图: 按"填满画布"缩放 (只在尺寸变化时重建) ---
        s = min(cw / iw, ch / ih)
        dw = max(int(iw * s), 1)
        dh = max(int(ih * s), 1)
        ox = (cw - dw) // 2
        oy = (ch - dh) // 2

        if self._base_disp != (dw, dh) or self.base_icon is None:
            self.base = self.src_image.resize((dw, dh), Image.LANCZOS)
            self.base_icon = vimg.to_tk(self.base)
            self._base_disp = (dw, dh)

        self.canvas.create_image(ox, oy, anchor="nw", image=self.base_icon)

        # --- 2) 取景框: 原图坐标 -> 画布坐标 ---
        box = vimg.crop_box(iw, ih, self.view)
        k = s                                    # 原图像素 -> 画布像素
        bx0 = ox + box[0] * k
        by0 = oy + box[1] * k
        bx1 = ox + box[2] * k
        by1 = oy + box[3] * k

        # --- 3) 框外变暗 (纯色, 无 stipple) ---
        dim = "#0d0d10"
        for (x0, y0, x1, y1) in (
            (ox, oy, ox + dw, by0),          # 上
            (ox, by1, ox + dw, oy + dh),     # 下
            (ox, by0, bx0, by1),             # 左
            (bx1, by0, ox + dw, by1),        # 右
        ):
            if x1 > x0 and y1 > y0:
                self.canvas.create_rectangle(x0, y0, x1, y1,
                                             fill=dim, outline="")

        # --- 4) 取景框边框 + 三分线 ---
        self.canvas.create_rectangle(bx0, by0, bx1, by1,
                                     outline=ACCENT, width=2)
        for i in (1, 2):
            x = bx0 + (bx1 - bx0) * i / 3
            y = by0 + (by1 - by0) * i / 3
            self.canvas.create_line(x, by0, x, by1, fill="#5aa8ff")
            self.canvas.create_line(bx0, y, bx1, y, fill="#5aa8ff")

        # --- 5) 角标 (视觉上强调是可拖动的框) ---
        L = 14
        for (cx_, cy_, sx, sy) in ((bx0, by0, 1, 1), (bx1, by0, -1, 1),
                                   (bx0, by1, 1, -1), (bx1, by1, -1, -1)):
            self.canvas.create_line(cx_, cy_, cx_ + L * sx, cy_,
                                    fill="#ffffff", width=3)
            self.canvas.create_line(cx_, cy_, cx_, cy_ + L * sy,
                                    fill="#ffffff", width=3)

        # --- 6) 提示 ---
        bw = box[2] - box[0]
        bh = box[3] - box[1]
        self.canvas.create_text(
            ox + 6, oy + dh - 6, anchor="sw",
            text=f"取景 {bw}×{bh}px  ·  缩放 {self.view.zoom:.2f}x",
            fill="#c8c8d0", font=("Microsoft YaHei UI", 8))

    # ---- 画布尺寸变化 ----
    def _on_canvas_resize(self) -> None:
        self._schedule_preview(0)
        self._schedule_effect(30)

    # ---- 延迟任务调度 ----
    def _schedule_preview(self, delay: int = 0) -> None:
        """安排一次完整预览重绘 (廉价绘图, 可立即执行)。"""
        if self._preview_job:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.after(delay, self._do_preview)

    def _do_preview(self) -> None:
        self._preview_job = None
        self._draw_preview(quick=False)

    # ---- 成效预览 (小图, 廉价) ----
    def _schedule_effect(self, delay: int = 60) -> None:
        if self._eff_job:
            try:
                self.after_cancel(self._eff_job)
            except Exception:
                pass
        self._eff_job = self.after(delay, self._do_effect)

    def _do_effect(self) -> None:
        """渲染"最终封面"预览 (右侧大图)。"""
        self._eff_job = None
        c = self.canvas_eff
        c.delete("all")
        if not self.src_image or not self.view:
            return
        cw = max(c.winfo_width(), 1)
        ch = max(c.winfo_height(), 1)

        # 按画布可用空间等比摆放 (保持 1200:714), 尽量占满
        pad = 4
        avail_w = max(cw - pad * 2, 20)
        avail_h = max(ch - pad * 2, 20)
        s = min(avail_w / vimg.TARGET_W, avail_h / vimg.TARGET_H)
        tw = max(int(vimg.TARGET_W * s), 8)
        th = max(int(vimg.TARGET_H * s), 6)

        # 直接从原图裁剪 -> 结果与最终封面完全一致。
        # 用 BILINEAR: 这是预览缩略图, 不是最终产物, 速度优先且质量足够。
        box = vimg.crop_box(self.src_image.width, self.src_image.height, self.view)
        try:
            thumb = self.src_image.crop(box).resize((tw, th), Image.BILINEAR)
        except Exception:
            return
        self.eff_photo = vimg.to_tk(thumb)
        c.create_image(cw // 2, ch // 2, anchor="center", image=self.eff_photo)

    def _schedule_heavy(self, delay: int = 220) -> None:
        """安排重活 (渲染 1200x714 + PNG 编码)。拖动停止后才跑。"""
        if self._heavy_job:
            try:
                self.after_cancel(self._heavy_job)
            except Exception:
                pass
        self._heavy_job = self.after(delay, self._do_heavy)

    def _do_heavy(self) -> None:
        self._heavy_job = None
        self._recompute()
        self._update_output_panel()
        self._do_effect()
        self._set_msg("就绪")

    def _on_drag_start(self, ev) -> None:
        self._drag_last = (ev.x, ev.y)

    def _on_drag(self, ev) -> None:
        """图片固定, 拖动移动取景框。"""
        if not self.src_image or not self.view:
            return
        last = getattr(self, "_drag_last", None)
        if not last:
            self._drag_last = (ev.x, ev.y)
            return
        dx = ev.x - last[0]
        dy = ev.y - last[1]
        self._drag_last = (ev.x, ev.y)

        g = self._canvas_geom()
        if not g:
            return
        _, _, dw, dh, s = g
        if s <= 0:
            return
        iw, ih = self.src_image.size

        # 画布位移 -> 原图像素位移 -> 归一化增量。
        # 取景框右移 = 取景窗口在原图上右移 = cx 增大。
        self.view.cx += dx / s / iw
        self.view.cy += dy / s / ih
        self.view.clamp()

        # 图片本身不重采样, 只有框在动 -> 极快
        self._draw_preview(quick=True)
        self._schedule_effect()
        self._schedule_heavy()
        self._set_msg("调整取景框…")

    def _on_wheel(self, ev) -> None:
        if not self.view:
            return
        step = 0.08 if ev.delta > 0 else -0.08
        self.var_zoom.set(max(1.0, min(4.0, self.var_zoom.get() + step)))
        self._on_zoom_change()

    def _on_zoom_change(self) -> None:
        if not self.view:
            return
        self.view.zoom = float(self.var_zoom.get())
        self.view.clamp()
        # 只移动取景框, 重活延后
        self._draw_preview(quick=True)
        self._schedule_effect()
        self._schedule_heavy()
        self._set_msg("缩放中…")

    def on_center(self) -> None:
        if not self.view:
            return
        self.view.cx = self.view.cy = 0.5
        self._draw_preview(quick=True)
        self._schedule_effect()
        self._schedule_heavy()

    # ------------------------------------------------------------ 计算输出
    def _recompute(self) -> None:
        """渲染最终封面并决定写入方式 (只在重活阶段调用)。"""
        import io
        self.result_png = None
        self.result_lossless = True
        if not self.src_image or not self.view or not self.info:
            return

        cover = vimg.render_crop(self.src_image, self.view)

        buf = io.BytesIO()
        cover.convert("RGBA").save(buf, format="PNG", optimize=True)
        lossless = buf.getvalue()

        cap = self.info.capacity_of("splash") or 0
        self.result_png = lossless
        self.result_lossless = True
        self.result_mode = "inplace" if len(lossless) <= cap else "rebuild"

    def _update_output_panel(self, size: int | None = None) -> None:
        if size is None and self.result_png:
            size = len(self.result_png)

        if not self.result_png:
            self.lbl_size.configure(text="—", foreground=FG_DIM)
            self.lbl_quality.configure(text="")
            self.lbl_mode.configure(text="—")
            self.btn_apply.configure(state="disabled")
            return

        mode = getattr(self, "result_mode", "inplace")
        if mode == "inplace":
            self.lbl_mode.configure(
                text="原地替换 (不重建 PE, 最安全)", foreground=OK)
        else:
            self.lbl_mode.configure(
                text="重建模式 (重新生成资源, 画质无损)", foreground=ACCENT)

        self.lbl_size.configure(text=vimg.human_size(size), foreground=FG)
        self.lbl_quality.configure(
            text="无损 —— 画质与原图完全一致", foreground=OK)
        self.btn_apply.configure(state="normal")

    # ------------------------------------------------------------ 应用
    def on_apply(self) -> None:
        if not self.dll or not self.result_png:
            return

        # 写入前再次检测权限 (比启动时更准确: 文件可能刚被占用)
        ok, why = core.can_write(self.dll)
        if not ok:
            detail = core.describe_write_problem(self.dll)
            if why == "denied" and not core.is_admin():
                if messagebox.askyesno(
                        APP_TITLE,
                        detail + "\n\n是否现在以管理员身份重新启动?"):
                    self._restart_elevated()
                    return
            messagebox.showerror(APP_TITLE, detail)
            self._set_msg("无法写入", ERR)
            return

        # 确认
        st = core.detect_status(self.dll, self.info) if self.info else None
        mode = getattr(self, "result_mode", "inplace")
        msg = (f"即将替换 VOCALOID6 启动封面。\n\n"
               f"目标: {self.dll}\n"
               f"方式: {'原地替换' if mode == 'inplace' else '重建模式'}\n"
               f"体积: {vimg.human_size(len(self.result_png))}\n\n")
        if st and st.state == "pristine":
            msg += "将自动备份原文件 (仅一次, 之后不会覆盖)。\n\n"
        msg += ("修改会使 Yamaha 的数字签名失效。\n"
                "已实测确认: VOCALOID6 不校验签名, 不影响启动。\n\n"
                "请确保 VOCALOID6 已完全退出。\n\n确定继续吗?")
        if not messagebox.askyesno(APP_TITLE, msg):
            return

        # 写临时文件
        tmp = core.DIR_OUTPUT / "_cover.png"
        try:
            tmp.write_bytes(self.result_png)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"写入临时文件失败: {e}")
            return

        self.btn_apply.configure(state="disabled")
        self._set_msg("正在应用…")
        self.update_idletasks()

        try:
            res = core.apply_cover(self.dll, splash=tmp)
        except core.V6PacError as e:
            self.btn_apply.configure(state="normal")
            self._set_msg("应用失败", ERR)
            messagebox.showerror(APP_TITLE, str(e))
            return
        except Exception as e:
            self.btn_apply.configure(state="normal")
            self._set_msg("应用失败", ERR)
            messagebox.showerror(APP_TITLE,
                                 f"发生未预期错误:\n{e}\n\n{traceback.format_exc()}")
            return

        if not res.ok:
            self.btn_apply.configure(state="normal")
            self._set_msg("应用失败", ERR)
            messagebox.showerror(APP_TITLE, res.message)
            return

        self._set_msg(res.message, OK)
        self.refresh()

        info = (f"封面已成功替换 ({'重建模式' if res.mode == 'rebuild' else '原地替换'})。\n\n"
                "现在启动 VOCALOID6 即可看到新封面。\n\n"
                "注意: Yamaha 的数字签名已失效 (属正常现象,\n"
                "不影响 VOCALOID6 运行)。\n\n"
                "如需还原, 点击「从备份还原」。")
        messagebox.showinfo(APP_TITLE, info)

    # ------------------------------------------------------------ 还原
    def on_restore_backup(self) -> None:
        if not self.dll:
            return
        bk = core.backup_path_for(self.dll)
        if not bk:
            messagebox.showwarning(APP_TITLE, "没有找到备份文件。")
            return
        if not messagebox.askyesno(
                APP_TITLE,
                f"将用备份还原 VOCALOID6.dll:\n\n{bk.name}\n\n"
                "请确保 VOCALOID6 已完全退出。确定继续吗?"):
            return
        try:
            msg = core.restore_backup(self.dll, bk)
        except core.V6PacError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        core.clear_applied()
        self._set_msg(msg, OK)
        self.refresh()
        messagebox.showinfo(APP_TITLE, msg)

    def on_restore_default(self) -> None:
        if not self.dll:
            return
        p = core.DIR_PRESET / "splash.png"
        if not p.is_file():
            messagebox.showwarning(APP_TITLE, "缺少预设封面, 请先导出默认封面。")
            return
        # 直接以预设封面走正常流程
        self._set_source(vimg.load_image(p), "零售版默认封面")
        self._set_msg("已载入默认封面, 点击「应用封面」写入。")

    # ------------------------------------------------------- 升级前还原
    def on_prepare_upgrade(self) -> None:
        if not self.dll:
            return

        ok, why = core.can_write(self.dll)
        if not ok:
            detail = core.describe_write_problem(self.dll)
            if why == "denied" and not core.is_admin():
                if messagebox.askyesno(
                        APP_TITLE, detail + "\n\n是否现在以管理员身份重新启动?"):
                    self._restart_elevated()
                    return
            messagebox.showerror(APP_TITLE, detail)
            return

        st = core.detect_status(self.dll, self.info) if self.info else None
        if st and st.state == "pristine":
            messagebox.showinfo(
                APP_TITLE,
                "当前 DLL 已是原版, 无需还原。\n\n"
                "可以直接安装 VOCALOID6 新版。")
            return

        if not messagebox.askyesno(
                APP_TITLE,
                "升级前还原\n\n"
                "将把 VOCALOID6.dll 还原成 Yamaha 原版, 以便安全升级。\n\n"
                "· 当前的自定义封面会被移除\n"
                "· 工具已记住你上次用的封面\n"
                "· 升级完成后可一键重新应用\n\n"
                "请先完全退出 VOCALOID6。确定继续吗?"):
            return

        try:
            changed, msg = core.prepare_for_upgrade(self.dll)
        except core.V6PacError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return

        self.refresh()
        self._set_msg("已还原为原版, 可以升级了", OK)
        messagebox.showinfo(
            APP_TITLE,
            msg + "\n\n"
            "现在可以运行 VOCALOID6 新版安装包。\n"
            "升级完成后重新打开本工具, 会提示你重新应用封面。")

    def _check_pending_upgrade(self) -> None:
        """启动时检查: 升级前还原过、且升级可能已完成 -> 提示重新应用封面。"""
        pend = core.pending_upgrade_restore()
        if not pend:
            return
        cover = core.last_cover()
        if not cover:
            core.clear_upgrade_flag()
            return

        # 只有当前是原版 (说明升级已完成或未应用) 才提示
        st = core.detect_status(self.dll) if self.dll else None
        if st and st.state != "pristine":
            return

        ans = messagebox.askyesno(
            APP_TITLE,
            "检测到升级已完成\n\n"
            f"你在 {pend.get('time', '')} 为升级还原了 DLL。\n"
            "工具已保存你上次使用的封面:\n"
            f"  {cover.name}\n\n"
            "是否现在重新应用这个封面?")
        if not ans:
            core.clear_upgrade_flag()
            return

        try:
            im = vimg.load_image(cover)
        except vimg.ImageError as e:
            messagebox.showerror(APP_TITLE, f"无法读取上次的封面: {e}")
            core.clear_upgrade_flag()
            return
        self._set_source(im, f"{cover.name} (上次使用)")
        core.clear_upgrade_flag()
        self._set_msg("已载入上次的封面, 点击「应用封面」写入。")
        self.on_apply()


def _try_elevate() -> bool:
    """
    若当前不是管理员且需要写入权限, 尝试以管理员身份重启自身。
    返回 True 表示已成功拉起提权实例 (本进程应退出)。
    """
    if core.is_admin():
        return False
    try:
        import ctypes
        script = str(Path(__file__).resolve())
        exe = sys.executable
        # ShellExecuteW 的 runas 会触发 UAC
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, f'"{script}"',
            str(Path(script).parent), 1)
        return r > 32
    except Exception:
        return False


def main() -> int:
    # 自动提权: VOCALOID6.dll 在 Program Files 下, 需要管理员权限才能写入
    if not core.is_admin():
        # 先问用户 (避免静默弹 UAC 造成困惑)
        try:
            _r = tk.Tk()
            _r.withdraw()
            ans = messagebox.askyesno(
                APP_TITLE,
                "需要管理员权限\n\n"
                "VOCALOID6.dll 位于 C:\\Program Files\\ 下,\n"
                "该目录受 Windows 保护, 普通账户无法写入。\n\n"
                "是否以管理员身份启动?\n"
                "(将弹出 UAC 授权窗口, 请点「是」)\n\n"
                "选择「否」仍可打开程序, 但无法应用封面。")
            _r.destroy()
        except Exception:
            ans = True

        if ans and _try_elevate():
            return 0

    try:
        app = App()
        app.mainloop()
        return 0
    except Exception:
        traceback.print_exc()
        try:
            messagebox.showerror(APP_TITLE, traceback.format_exc())
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
