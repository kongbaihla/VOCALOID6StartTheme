<img width="681" height="468" alt="image" src="https://github.com/user-attachments/assets/56aecebd-625c-4d5b-8285-27c1186fd82f" /># V6PAC

替换 VOCALOID6 编辑器的**启动封面 / 图标**。
有问题，嗯。。。。qq群？1128455018

把自制的封面图写进 `VOCALOID6.dll` 的资源节，启动时显示自己的图而不是官方 splash。

> ⚠️ **本工具会修改 `VOCALOID6.dll` 本体**。修改后 Authenticode 签名失效。
> 使用前请确认你接受这一点，并且**务必保留备份**（工具每次换封面前都会自动备份，
> 原版备份永不删除）。
> 非 Yamaha 官方工具，与 Yamaha 无关联。

|界面示例|
|-|
|<img width="450" height="269" alt="image" src="https://github.com/user-attachments/assets/ef10b435-1e5c-4ec2-b8cf-e44fb5ffb649" />
|
|<img width="450" height="280" alt="image" src="https://github.com/user-attachments/assets/1fa29068-32cf-4b48-b378-3e1f50d40f2f" />
|
---

## ⚠️ 运行前必读

**在按下启动按钮之前，按顺序确认下面每一项。** 前三条任意一条不满足，
都可能让你需要重装 VOCALOID6。

### 1. 关闭 VOCALOID6 编辑器

`VOCALOID6.dll` 被进程占用时**无法写入**。必须先完全退出编辑器
（托盘图标也检查一遍），否则会写失败或写出损坏文件。

### 2. 备份（工具自动做，但仍建议自己留一份）

工具的备份规则（2026-10 起）：

- **每次应用封面之前都备份**当前 DLL，所以换多次也能退回到上一版
- **签名有效的原版永不删除**，也不计入保留数量
- 被改过的备份最多保留**最近 10 份**，超出的自动清理

`备份\` 里的文件名带版本、时间和来源：

```
备份\VOCALOID6.dll.6.13.3.1.20261018-230854.apply.a1b2c3d4.bak
                  └版本┘ └────时间────┘ └来源┘ └摘要┘
```

来源有三种：`apply`（换封面前）、`upgrade`（升级前）、`manual`（手动）。

即便如此，自己再复制一份最保险：

```
C:\Program Files\VOCALOID6\Editor\VOCALOID6.dll
```

复制到桌面，改名成 `VOCALOID6.dll.orig` 之类。

### 3. 确认接受「签名失效」

修改后 Authenticode 签名不再有效。VOCALOID6 **没有自校验**，不影响启动，
但杀毒软件或系统可能因此报警。你接受这个后果再继续。

### 4. 准备图片

| 要求 | 说明 |
|---|---|
| 尺寸 | **1200 × 714**（工具会自动缩放，但比例不对会变形） |
| 格式 | PNG / JPG / BMP（工具会转成 PNG） |
| 大小 | 原地替换上限 439,738 字节；超出会自动走重建模式 |

### 5. 确认 Python 环境（最常出问题的一步）

本工具需要这几样东西，**缺一样就跑不起来**：

| 依赖 | 说明 | 缺失时表现 |
|---|---|---|
| Python **3.9+** | 解释器 | `Exited with code 9009` |
| **Pillow** | 图片处理（第三方，可 pip 装） | `No module named 'PIL'` |
| **pywebview** | 界面窗口（第三方，可 pip 装） | `No module named 'webview'` |
| **WebView2 Runtime** | 渲染界面（系统组件） | 界面空白 / 启动器提示缺失 |

#### 第一步：确认 Python 是真的

```bat
python --version
```

- 输出版本号（如 `Python 3.12.4`）→ 继续
- 弹出应用商店 / 报 9009 → 是**占位符**，先看
  [报 Exited with code 9009](#报-exited-with-code-9009)，装真正的 Python

#### 第二步：确认 Pillow 在

```bat
python -c "import PIL; print('Pillow', PIL.__version__)"
```

- 输出 `Pillow x.x.x` → 继续
- 报 `No module named 'PIL'` → **启动器会自动提示并询问是否安装**，按 `Y`
  即可，不用自己敲命令

#### 第三步：确认 pywebview 在

```bat
python -c "import webview; print('pywebview OK')"
```

- 输出 `pywebview OK` → 继续
- 报 `No module named 'webview'` → 启动器同样会提示并帮你装

手动装：

```bat
python -m pip install pillow pywebview
```

> 用 `python -m pip` 而不是 `pip`：`pip` 可能不在 PATH 里，
> `python -m pip` 一定指向当前这个解释器。

**用 `py` 启动器的话**，把 `python` 换成 `py -3`：

```bat
py -3 -m pip install pillow pywebview
```

#### 第四步：确认 WebView2 运行时在

Windows 10/11 **通常自带**。启动器会检查这两个目录之一：

```
C:\Program Files (x86)\Microsoft\EdgeWebView\Application
C:\Program Files\Microsoft\EdgeWebView\Application
```

都不存在的话，从微软官网装
[WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
它是系统组件，装一次即可。

> **不再需要 tkinter。** WebView2 版界面完全不用 tcl/tk，
> 所以当年没勾选「tcl/tk and IDLE」的 Python 也能跑。

#### 一条命令全查完

懒得一条条敲，把这段存成 `check.bat` 放在 `pac\` 下双击：

```bat
@echo off
python --version
python -c "import PIL; print('Pillow', PIL.__version__)"
python -c "import webview; print('pywebview OK')"
if exist "%ProgramFiles(x86)%\Microsoft\EdgeWebView\Application" echo WebView2 OK
if exist "%ProgramFiles%\Microsoft\EdgeWebView\Application" echo WebView2 OK
pause
```

四行都有正常输出就可以启动 V6PAC 了。

### 6. 装完第一次运行后

先用**一份确认没用的图**试一次，重启编辑器确认封面变了、程序能正常启动，
再换成真正想用的图。别一上来就用最终成品。

### 想还原怎么办

**先在工具的「备份历史」页里挑一份点「还原」**，不用自己复制文件。

列表会写明每份备份的**版本**和**是否原版**：

```
v6.13.3.1  [原版]     2026-10-18 23:08  ← 升级前还原用这个
v6.13.3.1  [已修改]   2026-10-17 21:25  ← 你之前换过的封面
```

- **原版**（签名有效）的删除按钮是禁用的，删不掉
- **已修改**的可以手动删除

也可以手工还原：

```bat
copy /Y "备份\VOCALOID6.dll.6.13.3.1.*.bak" "C:\Program Files\VOCALOID6\Editor\VOCALOID6.dll"
```

写 `Program Files` 需要**管理员权限**，用管理员身份打开 CMD。
或者直接点界面顶部的「以管理员身份重启」——工具会自己弹 UAC 提权。

---

## 特性

- **界面**：WebView2（HTML/CSS/JS），逻辑层仍是 Python，与 tkinter 版共用同一套核心代码
- **原地替换**：不重排 PE 结构，只要新图不超过原始条目大小
- **超限自动重建**：超过容量时走 `--rebuild`（dnlib 重建资源节，已验证可用）
- **自动发现目标**：先查注册表 `InstallLocation`，再扫各盘符常见路径。
  找到多个时让你在界面里选，不会静默改错那个
- **每次换封面都备份**：能退回上一版；原版备份永不删除
- **状态检测**：未应用 / 已应用 / VOCALOID 版本变化
- **实时预览**：拖动取景框时即时更新，大图走缩略副本计算

## 实测约束

| 项 | 值 |
|---|---|
| 封面目标尺寸 | 1200 × 714（由 `splashwindow.baml` 决定） |
| 原地替换上限 | 各条目原始大小（splash.png = 439,738 字节） |
| 自校验 | 无。改后不影响启动，但签名失效 |

## 界面

左侧导航：

| 项 | 作用 |
|---|---|
| **替换封面** | 选图 → 拖取景框 → 应用 |
| **备份历史** | 列出全部备份（版本 / 原版或已修改 / 时间 / 缩略图），可还原或删除 |
| **还原默认封面** | 恢复成官方图 |
| **升级前还原** | 升级 VOCALOID6 前把 DLL 恢复成原版 |
| **关于** | 钉在左下角 |

顶部**目标文件**卡：

- 显示当前 DLL 的路径、版本、签名状态、封面上限
- 机器上装了多个 VOCALOID6 时，卡片区会平铺出全部候选，点一张就切换

**没有管理员权限也能看**：选图、取景、预览都不需要提权，
只有真正写入 DLL 那一下需要。界面上会提示，并提供「以管理员身份重启」按钮。

## 目录

```
pac/
├── webui.py            WebView2 界面入口（启动脚本默认跑这个）
├── web/
│   ├── index.html      界面结构
│   ├── style.css       样式（配色取自 DSH 界面实测像素）
│   ├── app.js          交互逻辑 + 调后端
│   └── vendor/
│       └── gsap.min.js 过渡动画（本地副本，离线可用）
├── v6pac_core.py       核心逻辑：找 DLL / 调 v6res / 备份 / 状态
├── v6pac_image.py      图片处理：缩放、格式转换、容量检查、圆角
├── V6PAC.py            旧版 tkinter 界面（保留，不再是默认入口）
├── 启动 V6PAC.cmd       启动器（自动找 Python、检查依赖）
├── bin/                v6res 运行时（资源读写工具）
│   ├── v6res.exe
│   ├── v6res.dll
│   └── dnlib.dll
└── (reader|loadertest|pecmp|wpftest|snprobe)/
                        开发期的 PE / WPF 实验工程
```

运行时自动生成（**不含在仓库中**）：
`备份/`、`自定义/`、`日志/`、`输出/`、`状态/`、`预设/<版本>/`

`预设/` 按 DLL 版本分子目录，因为不同版本的官方封面不一样。

## 依赖

| 依赖 | 必需 | 说明 |
|---|---|---|
| Python 3.9+ | ✅ | 解释器 |
| Pillow | ✅ | 图片缩放 / 格式转换 |
| pywebview | ✅ | 界面窗口；`pip install pywebview` |
| WebView2 Runtime | ✅ | 渲染界面，Win10/11 自带 |

```bat
pip install pillow pywebview
```

> 旧版 tkinter 界面仍需 `tkinter`，但 WebView2 版**不需要**它，也不需要
> 安装器勾选 tcl/tk。

逐项检查方法见上面的 **⚠️ 运行前必读 → 5. 确认 Python 环境**。

启动器会**逐个实测**候选 Python（`python.exe -c "import sys"`），只有真正能
运行的那一个才算数。顺序：`.\python\` → 常见安装目录 → `py` 启动器 →
`PATH` 里的 `python.exe`。

### 报 `Exited with code 9009`

Windows 10/11 自带一个**应用商店占位符**：

```
C:\Users\<你>\AppData\Local\Microsoft\WindowsApps\python.exe
```

它是 0 字节的假文件，位于 PATH 中，运行只会返回 9009。启动器已经会靠实跑
探测**跳过**它；如果仍然报 9009，说明这台机器上确实没有可用的 Python：

1. 装 [Python 3.9+](https://www.python.org/downloads/)，安装向导第一步就
   **勾选 “Add python.exe to PATH”**（不勾的话命令行找不到）
2. 同一次安装里确认 **tcl/tk and IDLE** 是勾上的（默认已勾）
3. 装完**重开**一个 CMD 窗口（旧窗口不会刷新 PATH）
4. `pip install pillow`
5. 用 `where python` 确认指向 `Python3xx\`，不是 `WindowsApps`

也可以直接把真实的 `python.exe` 放到 `pac\python\` 下（启动器最优先用它）。

## 使用

双击 `启动 V6PAC.cmd`（或 `Start-V6PAC.cmd`）。

1. 工具自动定位 `C:\Program Files\VOCALOID6\Editor\VOCALOID6.dll`
2. 选一张图 → 自动缩放到 1200×714 并预览
3. 点「应用」→ 自动备份原 DLL → 写入资源
4. 重启 VOCALOID6 看效果

想还原：把 `备份\` 里的 `.bak` 复制回 `VOCALOID6.dll`
（**先关闭编辑器**，否则文件被占用）。

## 关于 bin/

`v6res.exe` 是读写 PE 资源的工具，由仓库作者编译提供。
它的源码不在本仓库中——如果你要从源码重建，需要自己实现等价的资源
读写功能。`v6pac_core.py` 用到的子命令只有四个，接口很窄：

| 子命令 | 用途 |
|---|---|
| `v6res info <dll>` | 读出各条目的大小 / 哈希 / 容量（JSON） |
| `v6res verify <dll>` | 校验资源完整性 |
| `v6res extract <dll> <dir>` | 把资源导出到目录 |
| `v6res replace <src> <dst> [--rebuild] splash=… splashdev=… icon=…` | 写入替换后的 DLL |

`bin/` 里只保留 `v6res` 运行时；`reader` / `pecmp` / `wpftest` / `snprobe` /
`loadertest` 是开发期的实验工程，只保留源码。

## 与主题工具的关系

本工具**修改 DLL 文件**；[V6 Theme Hook](../ram-theme/) **只改内存**。
两者可以同时用，但：

- 主题工具的 bat 启动看到的是**已被替换的封面**
- 如果 VOCALOID6 升级导致 `VOCALOID6.dll` 版本变化，状态检测会提示

## 许可

仅供学习研究。VOCALOID 及相关商标归 Yamaha 所有，本项目与之无关联。
请自行确认当地法律与软件许可条款。
