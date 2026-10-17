# V6PAC

替换 VOCALOID6 编辑器的**启动封面 / 图标**。

把自制的封面图写进 `VOCALOID6.dll` 的资源节，启动时显示自己的图而不是官方 splash。

> ⚠️ **本工具会修改 `VOCALOID6.dll` 本体**。修改后 Authenticode 签名失效。
> 使用前请确认你接受这一点，并且**务必保留备份**（工具会自动备份一次）。
> 非 Yamaha 官方工具，与 Yamaha 无关联。

---

## ⚠️ 运行前必读

**在按下启动按钮之前，按顺序确认下面每一项。** 前三条任意一条不满足，
都可能让你需要重装 VOCALOID6。

### 1. 关闭 VOCALOID6 编辑器

`VOCALOID6.dll` 被进程占用时**无法写入**。必须先完全退出编辑器
（托盘图标也检查一遍），否则会写失败或写出损坏文件。

### 2. 手动备份一次 `VOCALOID6.dll`

工具会**自动备份**，规则是：

- 仅当 DLL **仍是原版（签名有效）** 且**还没有备份**时才创建
- **永不覆盖**已有备份

也就是说：如果你之前用别的工具改过 DLL，或者已经有一份备份，
工具会**跳过**备份，直接在当前 DLL 上改。所以自己先复制一份最保险：

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

本工具需要三样东西，**缺一样就跑不起来**：

| 依赖 | 说明 | 缺失时表现 |
|---|---|---|
| Python **3.9+** | 解释器 | `Exited with code 9009` |
| **tkinter** | 图形界面（标准库，但部分安装不带） | `No module named 'tkinter'` |
| **Pillow** | 图片处理（第三方） | `No module named 'PIL'` |

#### 第一步：确认 Python 是真的

```bat
python --version
```

- 输出版本号（如 `Python 3.12.4`）→ 继续
- 弹出应用商店 / 报 9009 → 是**占位符**，先看
  [报 Exited with code 9009](#报-exited-with-code-9009)，装真正的 Python

#### 第二步：确认 tkinter 在

```bat
python -c "import tkinter; print('tkinter OK')"
```

- 输出 `tkinter OK` → 继续
- 报 `No module named 'tkinter'` → 见下方「tkinter 缺失怎么办」

#### 第三步：确认 Pillow 在

```bat
python -c "import PIL; print('Pillow', PIL.__version__)"
```

- 输出 `Pillow x.x.x` → 环境齐了
- 报 `No module named 'PIL'` → **启动器会自动提示并询问是否安装**，按 `Y`
  即可，不用自己敲命令

手动装也可以：

```bat
python -m pip install pillow
```

> 用 `python -m pip` 而不是 `pip`：`pip` 可能不在 PATH 里，
> `python -m pip` 一定指向当前这个解释器。

**用 `py` 启动器的话**，把 `python` 换成 `py -3`：

```bat
py -3 -m pip install pillow
```

#### tkinter 缺失怎么办

Windows 上 tkinter **不能**用 pip 装，它是 Python 安装器的组件：

1. 重新运行 Python 安装程序 → **Modify**
2. 勾选 **tcl/tk and IDLE**
3. 完成

用 Microsoft Store 版 Python 通常自带 tkinter；用官网安装器时
**默认就是勾选的**，除非当年手动取消过。

#### 一条命令全查完

懒得一条条敲，把这段存成 `check.bat` 放在 `pac\` 下双击：

```bat
@echo off
python --version
python -c "import tkinter; print('tkinter OK')"
python -c "import PIL; print('Pillow', PIL.__version__)"
pause
```

三行都有正常输出就可以启动 V6PAC 了。

### 6. 装完第一次运行后

先用**一份确认没用的图**试一次，重启编辑器确认封面变了、程序能正常启动，
再换成真正想用的图。别一上来就用最终成品。

### 想还原怎么办

**先关闭编辑器**，然后把 `备份\` 里的 `.bak` 复制回去。备份文件长这样：

```
备份\VOCALOID6.dll.6.13.0.1.20261005-172450.a1b2c3d4.bak
                  └版本┘ └──时间──┘ └摘要┘
```

```bat
copy /Y "备份\VOCALOID6.dll.*.bak" "C:\Program Files\VOCALOID6\Editor\VOCALOID6.dll"
```

如果 `备份\` 里有多份，挑**最早的那个**——工具只备份一次且永不覆盖，
最早的一般是原始文件。

写 `Program Files` 需要**管理员权限**，用管理员身份打开 CMD。

---

## 特性

- **原地替换**：不重排 PE 结构，只要新图不超过原始条目大小
- **超限自动重建**：超过容量时走 `--rebuild`（dnlib 重建资源节，已验证可用）
- **自动备份**：签名有效时备份一次，**永不覆盖**已有备份
- **状态检测**：未应用 / 已应用 / VOCALOID 版本变化
- **图形界面**：tkinter，带实时预览

## 实测约束

| 项 | 值 |
|---|---|
| 封面目标尺寸 | 1200 × 714（由 `splashwindow.baml` 决定） |
| 原地替换上限 | 各条目原始大小（splash.png = 439,738 字节） |
| 自校验 | 无。改后不影响启动，但签名失效 |

## 目录

```
pac/
├── V6PAC.py            图形界面（入口）
├── v6pac_core.py       核心逻辑：定位 DLL / 调 v6res / 备份 / 状态
├── v6pac_image.py      图片处理：缩放、格式转换、容量检查
├── 启动 V6PAC.cmd       启动器（自动找 Python）
├── Start-V6PAC.cmd     启动器（英文名，同上）
├── bin/                v6res 运行时（资源读写工具）
│   ├── v6res.exe
│   ├── v6res.dll
│   └── dnlib.dll
├── 预设/                内置封面与图标素材
└── (reader|loadertest|pecmp|wpftest|snprobe)/
                        开发期的 PE / WPF 实验工程
```

运行时自动生成（**不含在仓库中**）：
`备份/`、`自定义/`、`日志/`、`输出/`、`状态/`

## 依赖

| 依赖 | 必需 | 说明 |
|---|---|---|
| Python 3.9+ | ✅ | 解释器 |
| tkinter | ✅ | 图形界面；标准库但需安装器勾选，**无法 pip 装** |
| Pillow | ✅ | 图片缩放 / 格式转换 |

```bat
pip install pillow
```

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
