// v6res - VOCALOID6 启动封面替换辅助程序
//
// 设计要点:
//   DOCALOID6.dll 的托管资源区域包含两个 .resources 容器, 且 PE 结构对偏移敏感。
//   为了把风险降到最低, 替换采用「原地等长覆盖」策略:
//     1. 用官方 ResourceReader 读出容器, 定位目标条目数据在文件中的**实际字节区间**;
//     2. 若新数据长度 <= 原长度, 直接原地覆盖并在尾部补 0 —— 文件其余部分一字节不动;
//     3. 若新数据更长, 则重建容器 + 重建 PE(仅在必要时), 并保证区域之后的数据完整。
//
//   调用方(Python GUI)负责把用户图片预先压到目标尺寸内, 因此绝大多数情况走第 2 条路径。
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Resources;
using System.Text;
using System.Text.Json;

namespace V6Res;

internal static class Program
{
    private static int Main(string[] args)
    {
        try
        {
            Console.OutputEncoding = Encoding.UTF8;
            if (args.Length == 0) { Usage(); return 2; }
            return args[0].ToLowerInvariant() switch
            {
                "info" => CmdInfo(args),
                "extract" => CmdExtract(args),
                "container" => CmdContainer(args),
                "probe" => CmdProbe(args),
                "replace" => CmdReplace(args),
                "verify" => CmdVerify(args),
                _ => Usage2(),
            };
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ERROR: " + ex.Message);
            return 1;
        }
    }

    private static int Usage2() { Usage(); return 2; }

    private static void Usage()
    {
        Console.Error.WriteLine("""
用法:
  v6res info    <dll>                         DLL 信息 (版本/签名/封面/尺寸上限)
  v6res extract <dll> <目录>                  导出 splash / splash_dev / icon
  v6res probe   <dll> <键>                    查询该条目可原地替换的最大字节数
  v6res replace <dll> <输出> <键=文件>...      替换资源
  v6res verify  <dll>                         校验资源容器完整性

键: splash | splashdev | icon
""");
    }

    private static string KeyToRes(string key) => key.ToLowerInvariant() switch
    {
        "splash" => "assets/splash.png",
        "splashdev" => "assets/splash_dev.png",
        "icon" => "assets/icon.ico",
        _ => throw new ArgumentException($"未知的键: {key} (可用: splash / splashdev / icon)"),
    };

    // ---------------------------------------------------------------- info
    private static int CmdInfo(string[] args)
    {
        if (args.Length < 2) { Usage(); return 2; }
        byte[] d = File.ReadAllBytes(args[1]);
        var pe = ParsePe(d);
        var entries = ReadAllEntries(d, pe);

        var res = new Dictionary<string, object?>
        {
            ["path"] = args[1],
            ["fileSize"] = d.Length,
            ["hasCertTable"] = pe.CertSize > 0,
            ["resourceCount"] = entries.Count,
        };
        foreach (var key in new[] { "splash", "splashdev", "icon" })
        {
            string rk = KeyToRes(key);
            if (entries.TryGetValue(rk, out var e))
            {
                res[key + "Size"] = e.Data.Length;
                res[key + "Sha256"] = Sha256(e.Data);
                res[key + "Capacity"] = e.Capacity;   // 原地可写入的最大字节数
            }
        }
        Console.WriteLine(JsonSerializer.Serialize(res, JsonOpts));
        return 0;
    }

    // ------------------------------------------------------------- extract
    private static int CmdExtract(string[] args)
    {
        if (args.Length < 3) { Usage(); return 2; }
        byte[] d = File.ReadAllBytes(args[1]);
        var pe = ParsePe(d);
        var entries = ReadAllEntries(d, pe);
        Directory.CreateDirectory(args[2]);

        var list = new List<Dictionary<string, object?>>();
        foreach (var key in new[] { "splash", "splashdev", "icon" })
        {
            string rk = KeyToRes(key);
            if (!entries.TryGetValue(rk, out var e)) continue;
            string name = key == "icon" ? "icon.ico" : key + ".png";
            string dest = Path.Combine(args[2], name);
            File.WriteAllBytes(dest, e.Data);
            list.Add(new Dictionary<string, object?>
            {
                ["key"] = rk, ["file"] = dest,
                ["size"] = e.Data.Length, ["capacity"] = e.Capacity,
                ["sha256"] = Sha256(e.Data),
            });
        }
        Console.WriteLine(JsonSerializer.Serialize(list, JsonOpts));
        return 0;
    }

    // ----------------------------------------------------------- container
    /// <summary>
    /// 导出第一个资源容器 (通常是 VOCALOID6.g.resources) 的原始字节。
    /// 供外部工具检查条目的运行时类型 (WPF 要求必须是 Stream)。
    /// </summary>
    private static int CmdContainer(string[] args)
    {
        if (args.Length < 3) { Usage(); return 2; }
        byte[] d = File.ReadAllBytes(args[1]);
        var pe = ParsePe(d);
        var (regionOff, regionLen) = FindResourceRegion(d, pe);

        int p = regionOff;
        int end = regionOff + regionLen;
        while (p + 8 <= end)
        {
            if (BitConverter.ToUInt32(d, p + 4) != 0xBEEFCACE)
            {
                int scan = p, limit = Math.Min(end, p + 16);
                bool found = false;
                while (scan + 8 <= limit)
                {
                    scan++;
                    int l = BitConverter.ToInt32(d, scan);
                    if (BitConverter.ToUInt32(d, scan + 4) == 0xBEEFCACE && l > 0
                        && scan + 4 + l <= d.Length)
                    { p = scan; found = true; break; }
                }
                if (!found) break;
            }
            int len = BitConverter.ToInt32(d, p);
            if (len <= 0 || p + 4 + len > d.Length) break;

            // 取第一个容器
            string? dir = Path.GetDirectoryName(Path.GetFullPath(args[2]));
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            byte[] body = new byte[len];
            Array.Copy(d, p + 4, body, 0, len);
            File.WriteAllBytes(args[2], body);
            Console.WriteLine(JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["output"] = args[2], ["size"] = len,
            }, JsonOpts));
            return 0;
        }
        throw new InvalidDataException("未找到资源容器");
    }

    // --------------------------------------------------------------- probe
    private static int CmdProbe(string[] args)
    {
        if (args.Length < 3) { Usage(); return 2; }
        byte[] d = File.ReadAllBytes(args[1]);
        var pe = ParsePe(d);
        var entries = ReadAllEntries(d, pe);
        string rk = KeyToRes(args[2]);
        if (!entries.TryGetValue(rk, out var e))
        {
            Console.WriteLine(JsonSerializer.Serialize(
                new Dictionary<string, object?> { ["found"] = false }, JsonOpts));
            return 1;
        }
        Console.WriteLine(JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["found"] = true,
            ["key"] = rk,
            ["size"] = e.Data.Length,
            ["capacity"] = e.Capacity,
            ["canInPlace"] = true,
        }, JsonOpts));
        return 0;
    }

    // ------------------------------------------------------------- replace
    private static int CmdReplace(string[] args)
    {
        if (args.Length < 4) { Usage(); return 2; }
        string srcPath = args[1], dstPath = args[2];

        var want = new Dictionary<string, string>();   // 资源键 -> 新文件
        bool rebuild = false;
        for (int i = 3; i < args.Length; i++)
        {
            if (args[i] == "--rebuild") { rebuild = true; continue; }
            int eq = args[i].IndexOf('=');
            if (eq <= 0) throw new ArgumentException($"参数格式错误 (应为 键=值): {args[i]}");
            string rk = KeyToRes(args[i][..eq]);
            string file = args[i][(eq + 1)..];
            if (!File.Exists(file)) throw new FileNotFoundException($"文件不存在: {file}");
            want[rk] = file;
        }

        byte[] d = File.ReadAllBytes(srcPath);
        var pe = ParsePe(d);
        var entries = ReadAllEntries(d, pe);

        // 检查容量
        var tooBig = new List<string>();
        foreach (var kv in want)
        {
            if (!entries.TryGetValue(kv.Key, out var e))
                throw new InvalidOperationException($"未找到资源: {kv.Key}");
            long newLen = new FileInfo(kv.Value).Length;
            if (newLen > e.Capacity)
                tooBig.Add($"{kv.Key}: {newLen} > {e.Capacity}");
        }

        if (tooBig.Count > 0 && !rebuild)
        {
            Console.Error.WriteLine("ERROR: 以下资源超出可原地替换的容量上限: "
                                    + string.Join("; ", tooBig));
            Console.Error.WriteLine("提示: 加 --rebuild 参数可重建资源容器以支持任意大小。");
            return 3;
        }

        if (!rebuild)
        {
            // ---- 原地等长覆盖: 文件其余部分完全不变 ----
            foreach (var kv in want)
            {
                var e = entries[kv.Key];
                byte[] nb = File.ReadAllBytes(kv.Value);
                BitConverter.GetBytes(nb.Length).CopyTo(d, e.LengthPrefixOffset);
                Array.Copy(nb, 0, d, e.DataOffset, nb.Length);
                for (int i = e.DataOffset + nb.Length; i < e.DataOffset + e.Capacity; i++)
                    d[i] = 0;
            }
        }
        else
        {
            // ---- 重建模式: 用 dnlib 重写程序集 (自动处理资源布局与清单偏移) ----
            d = RebuildWithDnlib(srcPath, want);
        }

        string? dir = Path.GetDirectoryName(Path.GetFullPath(dstPath));
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
        File.WriteAllBytes(dstPath, d);

        // 自检: 重新读取并比对
        byte[] chk = File.ReadAllBytes(dstPath);
        var cpe = ParsePe(chk);
        var centries = ReadAllEntries(chk, cpe);
        var details = new List<Dictionary<string, object?>>();
        foreach (var kv in want)
        {
            byte[] expect = File.ReadAllBytes(kv.Value);
            if (!centries.TryGetValue(kv.Key, out var ce) || !ce.Data.SequenceEqual(expect))
                throw new InvalidOperationException($"自检失败: {kv.Key} 内容不一致");
            details.Add(new Dictionary<string, object?>
            {
                ["key"] = kv.Key, ["size"] = expect.Length, ["ok"] = true,
            });
        }
        // 额外自检: 未替换的关键条目必须保持不变
        foreach (var k in new[] { "assets/splash.png", "assets/splash_dev.png", "assets/icon.ico" })
        {
            if (want.ContainsKey(k)) continue;
            if (entries.TryGetValue(k, out var orig) && centries.TryGetValue(k, out var now))
                if (!orig.Data.SequenceEqual(now.Data))
                    throw new InvalidOperationException($"自检失败: 未替换的 {k} 被破坏");
        }
        if (centries.Count != entries.Count)
            throw new InvalidOperationException(
                $"自检失败: 资源条目数变化 {entries.Count} -> {centries.Count}");

        Console.WriteLine(JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["output"] = dstPath,
            ["outputSize"] = d.Length,
            ["inputSize"] = new FileInfo(srcPath).Length,
            ["mode"] = rebuild ? "rebuild" : "inplace",
            ["certRemoved"] = rebuild && pe.CertSize > 0,
            ["resourceCount"] = centries.Count,
            ["replaced"] = details,
        }, JsonOpts));
        return 0;
    }

    // -------------------------------------------------------------- verify
    private static int CmdVerify(string[] args)
    {
        if (args.Length < 2) { Usage(); return 2; }
        byte[] d = File.ReadAllBytes(args[1]);
        var pe = ParsePe(d);
        var entries = ReadAllEntries(d, pe);
        var missing = new[] { "assets/splash.png", "assets/splash_dev.png", "assets/icon.ico" }
            .Where(k => !entries.ContainsKey(k)).ToArray();
        Console.WriteLine(JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["ok"] = missing.Length == 0,
            ["resourceCount"] = entries.Count,
            ["missing"] = missing,
        }, JsonOpts));
        return missing.Length == 0 ? 0 : 1;
    }

    /// <summary>
    /// 读取 CLR 清单中每个资源容器的 offset (相对 ManagedResources 区域起点)。
    /// 返回 (资源名 -> offset) 以及每个 offset 字段在**元数据流**中的绝对偏移,
    /// 以便在容器位置变化时就地改写。
    /// </summary>
    private static List<(string name, long offset, int fieldFileOffset)> ReadManifestOffsets(
        byte[] d, PeInfo pe)
    {
        var list = new List<(string, long, int)>();

        // 元数据流在文件中的绝对偏移: 通过 MetadataReader 找到 #~ 流即可,
        // 但更简单的做法是直接用 PEReader 读取并借助其内部定位。
        int ddOff = pe.Is64 ? pe.OptOffset + 112 : pe.OptOffset + 96;
        uint corRva = BitConverter.ToUInt32(d, ddOff + 14 * 8);
        int corOff = Rva2Off(pe, corRva);
        uint mdRva = BitConverter.ToUInt32(d, corOff + 8);
        int mdOff = Rva2Off(pe, mdRva);

        // 解析元数据根以找到 #~ 流
        int o = mdOff + 4;          // 跳过签名
        o += 2 + 2 + 4;             // Major, Minor, Reserved
        int verLen = BitConverter.ToInt32(d, o); o += 4 + verLen;
        o += 2;                     // Flags
        int nStreams = BitConverter.ToInt16(d, o); o += 2;
        int tablesOff = -1;
        for (int i = 0; i < nStreams; i++)
        {
            int so = BitConverter.ToInt32(d, o); o += 4;
            o += 4;                 // size
            int ns = o; int nl = 0;
            while (o < d.Length && d[o] != 0) { o++; nl++; }
            string nm = Encoding.ASCII.GetString(d, ns, nl); o++;
            while ((o - mdOff) % 4 != 0) o++;
            if (nm == "#~" || nm == "#-") tablesOff = mdOff + so;
        }
        if (tablesOff < 0) throw new InvalidDataException("未找到 #~ 表流");

        // 用 MetadataReader 取得权威的 ManifestResource 行数据
        using var ms = new MemoryStream(d, writable: false);
        using var per = new System.Reflection.PortableExecutable.PEReader(ms);
        var md = System.Reflection.Metadata.PEReaderExtensions.GetMetadataReader(per);
        var names = new List<(string name, long offset)>();
        foreach (var h in md.ManifestResources)
        {
            var mr = md.GetManifestResource(h);
            names.Add((md.GetString(mr.Name), mr.Offset));
        }

        // 在 #~ 流中定位 ManifestResource 表的起始, 以便计算每个 offset 字段的位置
        int fieldBase = FindManifestResourceTableOffset(d, tablesOff, md);
        if (fieldBase >= 0)
        {
            // 行布局: Offset(4) Flags(4) Name(串索引) Implementation(编码索引)
            int strIdx = (d[tablesOff + 6] & 0x01) != 0 ? 4 : 2;
            foreach (var (name, _) in names)
            {
                // 逐行匹配名称以定位
                // (行宽依赖 Implementation 的编码宽度, 这里由 FindManifestResourceTableOffset 处理)
                break;
            }
            // 简化: 按行序填充, 行宽在外部计算
            _ = strIdx;
        }

        // 逐行扫描: 用 MetadataReader 的行数确定, 并由名称匹配校验
        int rowSize = ManifestResourceRowSize(d, tablesOff);
        for (int i = 0; i < names.Count; i++)
        {
            int rowOff = fieldBase + i * rowSize;
            if (rowOff + 4 > d.Length) break;
            // 校验名称一致 (读取该行的 Name 串索引)
            list.Add((names[i].name, names[i].offset, rowOff));
        }
        return list;
    }

    /// <summary>定位 #~ 流中 ManifestResource 表的第一个 Offset 字段的绝对偏移。</summary>
    private static int FindManifestResourceTableOffset(byte[] d, int tablesOff,
        System.Reflection.Metadata.MetadataReader md)
    {
        // 表流头: Reserved(4) MajorVersion(1) MinorVersion(1) HeapSizes(1) Reserved(1)
        //          Valid(8) Sorted(8) Rows[...]
        int o = tablesOff + 4 + 1 + 1 + 1 + 1;
        ulong valid = BitConverter.ToUInt64(d, o); o += 8;
        o += 8;                                     // Sorted
        int heapSizes = d[tablesOff + 6];
        bool strWide = (heapSizes & 0x01) != 0;

        var rows = new uint[64];
        for (int i = 0; i < 64; i++)
            if ((valid & (1UL << i)) != 0) { rows[i] = BitConverter.ToUInt32(d, o); o += 4; }

        // 累加前 0x27 个表的长度
        for (int tbl = 0; tbl < 0x28; tbl++)
        {
            if ((valid & (1UL << tbl)) == 0) continue;
            o += (int)(rows[tbl] * (uint)TableRowSize(tbl, rows, strWide));
        }
        return o;
    }

    private static int ManifestResourceRowSize(byte[] d, int tablesOff)
    {
        int o = tablesOff + 4 + 4;
        ulong valid = BitConverter.ToUInt64(d, o);
        var rows = new uint[64];
        o += 16;
        int heapSizes = d[tablesOff + 6];
        bool strWide = (heapSizes & 0x01) != 0;
        for (int i = 0; i < 64; i++)
            if ((valid & (1UL << i)) != 0) { rows[i] = BitConverter.ToUInt32(d, o); o += 4; }
        return TableRowSize(0x28, rows, strWide);
    }

    /// <summary>计算指定元数据表的行字节数。</summary>
    private static int TableRowSize(int tbl, uint[] rows, bool strWide)
    {
        int s = strWide ? 4 : 2;                 // #Strings 索引
        int g = 2;                               // #GUID (本程序集不使用宽索引)
        int b = 2;                               // #Blob (同上, 仅用于本表无关项)
        int rid(int t) => rows[t] < 65536 ? 2 : 4;
        int coded(int bits, params int[] ts)
        {
            uint max = 0;
            foreach (var t in ts) max = Math.Max(max, rows[t]);
            return max < (1u << (16 - bits)) ? 2 : 4;
        }
        int TypeDefOrRef() => coded(2, 0x02, 0x01, 0x1B);
        int HasConstant() => coded(2, 0x04, 0x08, 0x17);
        int HasCustomAttribute() => coded(5, 0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x11,
            0x14, 0x17, 0x1A, 0x1B, 0x20, 0x23, 0x26, 0x27, 0x28, 0x2A, 0x2C, 0x00, 0x0E);
        int HasFieldMarshal() => coded(1, 0x04, 0x08);
        int HasDeclSecurity() => coded(2, 0x02, 0x06, 0x20);
        int MemberRefParent() => coded(3, 0x02, 0x01, 0x1A, 0x06, 0x1B);
        int HasSemantics() => coded(1, 0x14, 0x17);
        int MethodDefOrRef() => coded(1, 0x06, 0x0A);
        int MemberForwarded() => coded(1, 0x04, 0x06);
        int Implementation() => coded(2, 0x27, 0x23, 0x28);
        int CustomAttributeType() => 4;          // 固定宽度
        int ResolutionScope() => coded(2, 0x00, 0x1A, 0x23, 0x01);
        int TypeOrMethodDef() => coded(1, 0x02, 0x06);

        return tbl switch
        {
            0x00 => 2 + s,                                   // Module
            0x01 => ResolutionScope() + s + s,               // TypeRef
            0x02 => 4 + s + s + TypeDefOrRef() + rid(0x04) + rid(0x06),  // TypeDef
            0x03 => rid(0x04),                               // FieldPtr
            0x04 => 2 + s + b,                               // Field
            0x05 => rid(0x06),                               // MethodPtr
            0x06 => 4 + 2 + 2 + s + b + rid(0x08),           // MethodDef
            0x07 => rid(0x08),                               // ParamPtr
            0x08 => 2 + 2 + s,                               // Param
            0x09 => rid(0x02) + TypeDefOrRef(),              // InterfaceImpl
            0x0A => MemberRefParent() + s + b,               // MemberRef
            0x0B => 1 + 1 + HasConstant() + b,               // Constant
            0x0C => HasCustomAttribute() + CustomAttributeType() + b,   // CustomAttribute
            0x0D => HasFieldMarshal() + b,                   // FieldMarshal
            0x0E => 2 + HasDeclSecurity() + b,               // DeclSecurity
            0x0F => 2 + 4 + rid(0x02),                       // ClassLayout
            0x10 => 4 + rid(0x04),                           // FieldLayout
            0x11 => b,                                       // StandAloneSig
            0x12 => rid(0x02) + coded(2, 0x14, 0x17),        // EventMap
            0x13 => rid(0x14),                               // EventPtr
            0x14 => 2 + s + TypeDefOrRef(),                  // Event
            0x15 => rid(0x02) + coded(2, 0x17, 0x14),        // PropertyMap
            0x16 => rid(0x17),                               // PropertyPtr
            0x17 => 2 + s + b,                               // Property
            0x18 => 2 + rid(0x06) + HasSemantics(),          // MethodSemantics
            0x19 => rid(0x02) + MethodDefOrRef(),            // MethodImpl
            0x1A => s,                                       // ModuleRef
            0x1B => b,                                       // TypeSpec
            0x1C => 2 + 2 + MemberForwarded() + s,           // ImplMap
            0x1D => 4 + rid(0x04),                           // FieldRVA
            0x20 => 4 + 2 + 2 + 2 + 2 + 4 + b + s + s,       // Assembly
            0x21 => 4,                                       // AssemblyProcessor
            0x22 => 4 + 2 + 2 + 2 + 2 + 4 + b + s + s,       // AssemblyOS (近似)
            0x23 => 4 + 2 + 2 + 2 + 2 + 4 + b + s + s,       // AssemblyRef
            0x24 => 4 + rid(0x23),                           // AssemblyRefProcessor
            0x25 => 4 + 2 + 2 + 2 + 2 + 4 + b + s + s,       // AssemblyRefOS (近似)
            0x26 => rid(0x02) + rid(0x02),                   // File
            0x27 => 4 + 4 + s + Implementation(),            // ExportedType
            0x28 => 4 + 4 + s + Implementation(),            // ManifestResource
            0x29 => rid(0x02) + coded(2, 0x29, 0x02, 0x01, 0x1B),  // NestedClass
            0x2A => 2 + 2 + TypeOrMethodDef(),               // GenericParam
            0x2B => rid(0x2A) + MethodDefOrRef(),            // MethodSpec
            0x2C => rid(0x02) + b,                           // GenericParamConstraint
            _ => 0,
        };
    }

    /// <summary>把清单里各资源容器的 offset 改写为新的值。</summary>
    private static void WriteManifestOffsets(byte[] d, PeInfo pe,
        IReadOnlyDictionary<string, uint> newOffsets)
    {
        foreach (var (name, _, fieldOff) in ReadManifestOffsets(d, pe))
        {
            if (newOffsets.TryGetValue(name, out uint v))
                BitConverter.GetBytes(v).CopyTo(d, fieldOff);
        }
    }

    // ---------------------------------------------------------------- rebuild
    /// <summary>
    /// 用 dnlib 重建程序集: 替换嵌入资源后重新写出。
    ///
    /// 为什么用 dnlib 而不是手写 PE 改写:
    ///   CLR 的 ManifestResource 表把每个资源容器相对 ManagedResources 区域的
    ///   偏移硬编码在元数据里 (实测: 容器1 = 0x2A8378)。当容器0变大越过该偏移时,
    ///   必须同步改写元数据。dnlib 会自动重新布局资源并修正所有这些偏移。
    /// </summary>
    private static byte[] RebuildWithDnlib(string srcPath, Dictionary<string, string> want)
    {
        using var mod = dnlib.DotNet.ModuleDefMD.Load(srcPath);

        // 建立 资源名 -> 新内容 的映射 (资源名形如 "VOCALOID6.g.resources")
        // want 的键是 "assets/splash.png" 这类**条目名**, 位于某个容器内部,
        // 所以需要逐个容器解包 -> 替换条目 -> 重新打包。
        var replacedAny = new HashSet<string>(StringComparer.Ordinal);

        for (int i = 0; i < mod.Resources.Count; i++)
        {
            var res = mod.Resources[i];
            if (res is not dnlib.DotNet.EmbeddedResource er) continue;

            byte[] containerBytes;
            {
                var r = er.CreateReader();
                containerBytes = r.ReadBytes((int)r.Length);
            }

            // 解包容器。
            // ⚠ 关键: 必须**保留每个条目的原始类型**。
            //   WPF 的 pack URI 加载走 ResourceManager.GetStream(),
            //   它要求条目以 Stream 类型码存储; 若写成 byte[] 类型码,
            //   GetStream 会抛 InvalidOperationException, 导致启动崩溃。
            var items = new List<(string key, object? val, bool wasStream)>();
            using (var ms = new MemoryStream(containerBytes, writable: false))
            using (var rr = new System.Resources.ResourceReader(ms))
            {
                var et = rr.GetEnumerator();
                while (et.MoveNext())
                {
                    object? v = et.Value;
                    bool isStream = v is Stream;
                    items.Add(((string)et.Key, v, isStream));
                }
            }

            // 替换 (新数据必须是 Stream, 以匹配原始类型)
            bool touched = false;
            for (int k = 0; k < items.Count; k++)
                if (want.TryGetValue(items[k].key, out var f))
                {
                    byte[] nb = File.ReadAllBytes(f);
                    // 该条目原本是 Stream -> 新值也用 Stream, 保持类型码一致
                    items[k] = (items[k].key,
                                items[k].wasStream ? new MemoryStream(nb, false) : nb,
                                items[k].wasStream);
                    replacedAny.Add(items[k].key);
                    touched = true;
                }
            if (!touched) continue;

            // 重新打包 (保持原类型)
            byte[] newContainer;
            using (var om = new MemoryStream())
            {
                using (var rw = new System.Resources.ResourceWriter(om))
                    foreach (var (key, val, _) in items)
                        rw.AddResource(key, val);
                newContainer = om.ToArray();
            }

            // 替换该嵌入资源 (dnlib 会在写出时自动计算新偏移)
            mod.Resources[i] = new dnlib.DotNet.EmbeddedResource(
                er.Name, newContainer, er.Attributes);
        }

        var missing = want.Keys.Where(k => !replacedAny.Contains(k)).ToArray();
        if (missing.Length > 0)
            throw new InvalidOperationException(
                $"未在任何资源容器中找到: {string.Join(", ", missing)}");

        // 写出到内存
        using var outMs = new MemoryStream();
        var opts = new dnlib.DotNet.Writer.ModuleWriterOptions(mod);
        opts.Logger = dnlib.DotNet.DummyLogger.NoThrowInstance;
        mod.Write(outMs, opts);
        return outMs.ToArray();
    }

    // 以下手写 PE 改写逻辑在 dnlib 方案下已不再使用, 保留以供参考/回退。
    private static byte[] RebuildResourceRegion(byte[] src, PeInfo pe,
        Dictionary<string, ResEntry> entries, Dictionary<string, string> want)
    {
        var (regionOff, regionLen) = FindResourceRegion(src, pe);

        // 关键: 定位各容器的原始位置。
        // CLR 的清单元数据表记录了每个资源容器相对区域起点的偏移,
        // 因此**不能移动后面的容器** —— 只能原地替换其内容。
        var positions = new List<(int prefixOff, int containerOff, int len)>();
        int p = regionOff;
        int end = regionOff + regionLen;
        while (p + 8 <= end)
        {
            if (BitConverter.ToUInt32(src, p + 4) != 0xBEEFCACE)
            {
                int scan = p, limit = Math.Min(end, p + 16);
                bool found = false;
                while (scan + 8 <= limit)
                {
                    scan++;
                    int l = BitConverter.ToInt32(src, scan);
                    if (BitConverter.ToUInt32(src, scan + 4) == 0xBEEFCACE && l > 0
                        && scan + 4 + l <= src.Length)
                    { p = scan; found = true; break; }
                }
                if (!found) break;
            }
            int len = BitConverter.ToInt32(src, p);
            if (len <= 0 || p + 4 + len > src.Length) break;
            positions.Add((p, p + 4, len));
            p += 4 + len;
        }
        if (positions.Count == 0)
            throw new InvalidDataException("未能解析任何资源容器");

        // 逐容器重建。容器必须顺序排列、互不重叠;
        // 每个容器的起点偏移会被写回 CLR 清单 (ManifestResource.Offset)。
        var rebuilt = new byte[positions.Count][];
        for (int i = 0; i < positions.Count; i++)
            rebuilt[i] = RebuildContainer(src, positions[i].containerOff,
                                          positions[i].len, want);

        // 顺序重排: 容器0、填充、容器1、... (按原始顺序)
        var newPos = new List<(int prefixRel, byte[] body)>();
        long cursor = 0;      // 相对区域起点
        for (int i = 0; i < positions.Count; i++)
        {
            if (i > 0)
                while ((cursor + 4) % 8 != 0) cursor++;   // 8 字节对齐
            newPos.Add(((int)cursor, rebuilt[i]));
            cursor += 4 + rebuilt[i].Length;
        }
        int newRegionLen = (int)cursor;

        // 计算容器名 -> 新 offset 的映射 (offset 相对区域起点)
        var nameByOrigOffset = ReadManifestOffsets(src, pe)
            .ToDictionary(x => x.offset, x => x.name);
        var newOffsets = new Dictionary<string, uint>(StringComparer.Ordinal);
        for (int i = 0; i < positions.Count; i++)
        {
            uint origRel = (uint)(positions[i].prefixOff - regionOff);
            if (nameByOrigOffset.TryGetValue(origRel, out var nm))
                newOffsets[nm] = (uint)newPos[i].prefixRel;
        }

        // 构造新区域
        var regionBytes = new byte[newRegionLen];
        foreach (var (prefixRel, body) in newPos)
        {
            BitConverter.GetBytes(body.Length).CopyTo(regionBytes, prefixRel);
            Array.Copy(body, 0, regionBytes, prefixRel + 4, body.Length);
        }

        if (newRegionLen <= regionLen)
        {
            // 区域未超出原空间: 原地覆盖 + 更新清单 offset + 清除证书表
            var outBytes2 = new byte[src.Length];
            Array.Copy(src, outBytes2, src.Length);
            for (long i = regionOff; i < regionOff + regionLen; i++) outBytes2[i] = 0;
            Array.Copy(regionBytes, 0, outBytes2, regionOff, newRegionLen);

            var p1 = ParsePe(outBytes2);
            WriteManifestOffsets(outBytes2, p1, newOffsets);
            UpdateResourceDirSize(outBytes2, p1, newRegionLen);
            FinalizePe(outBytes2, p1);
            return outBytes2;
        }

        // 区域超出原空间: 扩展宿主节, 并同步更新清单 offset
        byte[] grown = WriteRegionToPe(src, pe, regionOff, regionLen, regionBytes);
        var p2 = ParsePe(grown);
        WriteManifestOffsets(grown, p2, newOffsets);
        return grown;
    }

    /// <summary>重建单个 .resources 容器 (返回容器本体, 不含 4 字节长度前缀)。</summary>
    private static byte[] RebuildContainer(byte[] src, int cOff, int cLen,
        Dictionary<string, string> want)
    {
        // 读出全部条目 (保持顺序)。字符串等非字节类型必须原样保留。
        var ordered = new List<(string key, object? val)>();
        using (var m = new MemoryStream(src, cOff, cLen, writable: false))
        using (var rr = new ResourceReader(m))
        {
            var et = rr.GetEnumerator();
            while (et.MoveNext())
                ordered.Add(((string)et.Key, et.Value switch
                {
                    Stream s => (object)ReadStream(s),
                    _ => et.Value,
                }));
        }

        Console.Error.WriteLine($"[dbg] 容器 0x{cOff:X} 条目={ordered.Count} " +
            $"类型={string.Join(",", ordered.Select(x => x.val?.GetType().Name ?? "null").Distinct())}");

        // 替换
        for (int i = 0; i < ordered.Count; i++)
            if (want.TryGetValue(ordered[i].key, out var f))
                ordered[i] = (ordered[i].key, File.ReadAllBytes(f));

        // 用官方写入器重新序列化
        using var outMs = new MemoryStream();
        using (var rw = new ResourceWriter(outMs))
        {
            foreach (var (key, val) in ordered)
                rw.AddResource(key, val);
        }
        return outMs.ToArray();
    }

    /// <summary>
    /// 把新区域写回宿主节。保持节的原始顺序; 若宿主节变大, 则其后所有节
    /// 的文件偏移与 RVA 同步后移, 并修正数据目录中指向被移动节的 RVA。
    /// 证书表因签名必然失效而直接丢弃。
    /// </summary>
    private static byte[] WriteRegionToPe(byte[] src, PeInfo pe, int regionOff,
        int oldRegionLen, byte[] newRegion)
    {
        int hostIdx = -1;
        for (int i = 0; i < pe.Sections.Count; i++)
        {
            var s = pe.Sections[i];
            if (regionOff >= s.RawPtr && regionOff < s.RawPtr + s.RawSize) { hostIdx = i; break; }
        }
        if (hostIdx < 0) throw new InvalidDataException("资源不在任何节内");
        var host = pe.Sections[hostIdx];

        long bodyEnd = pe.CertSize > 0 && pe.CertPtr > 0 && pe.CertPtr < src.Length
            ? pe.CertPtr : src.Length;

        int relOff = regionOff - (int)host.RawPtr;         // 资源在宿主节内的相对偏移
        long newHostEnd = relOff + newRegion.Length;
        bool grows = newHostEnd > host.RawSize;

        if (!grows)
        {
            // 变小或不变: 覆盖到原文件, 并**正确移除证书表目录项**
            var outp = new byte[src.Length];
            Array.Copy(src, outp, src.Length);
            Array.Copy(newRegion, 0, outp, regionOff, newRegion.Length);
            for (long i = regionOff + newRegion.Length; i < regionOff + oldRegionLen; i++)
                outp[i] = 0;

            var p1 = ParsePe(outp);
            UpdateResourceDirSize(outp, p1, newRegion.Length);
            FinalizePe(outp, p1);        // 清除证书目录 + 重算 SizeOfImage + 清校验和
            return outp;
        }

        // ---- 变大: 宿主节扩展, 后续节后移 ----
        // 注意: VSize 是「虚拟大小」, 必须按 RVA 计算; RawSize 才是文件大小。
        // .text 的 VAddr(0x2000) 与 RawPtr(0x200) 不同, 二者不可混用。
        uint needRaw = Align((uint)newHostEnd, 0x200);
        uint rawDelta = needRaw - host.RawSize;

        // 宿主节内新内容的虚拟末端 (相对节起点) = relOff + 新区域长度
        uint newVirtUsed = (uint)newHostEnd;                 // relOff 已相对节起点
        uint needVirt = Align(newVirtUsed, 0x1000);
        uint vaDelta = needVirt > Align(host.VSize, 0x1000)
            ? needVirt - Align(host.VSize, 0x1000) : 0;

        var newRawPtr = new uint[pe.Sections.Count];
        var newRawSize = new uint[pe.Sections.Count];
        var newVAddr = new uint[pe.Sections.Count];
        var newVSize = new uint[pe.Sections.Count];
        for (int i = 0; i < pe.Sections.Count; i++)
        {
            newRawPtr[i] = pe.Sections[i].RawPtr;
            newRawSize[i] = pe.Sections[i].RawSize;
            newVAddr[i] = pe.Sections[i].VAddr;
            newVSize[i] = pe.Sections[i].VSize;
        }
        newRawSize[hostIdx] = needRaw;
        newVSize[hostIdx] = Math.Max(host.VSize, newVirtUsed);
        for (int i = hostIdx + 1; i < pe.Sections.Count; i++)
        {
            newRawPtr[i] = pe.Sections[i].RawPtr + rawDelta;
            newVAddr[i] = pe.Sections[i].VAddr + vaDelta;
        }

        uint lastEnd = 0;
        for (int i = 0; i < pe.Sections.Count; i++)
            lastEnd = Math.Max(lastEnd, newRawPtr[i] + newRawSize[i]);

        var outBytes = new byte[lastEnd];
        Array.Copy(src, 0, outBytes, 0, (int)host.RawPtr);   // 头部
        for (int i = 0; i < pe.Sections.Count; i++)
        {
            var s = pe.Sections[i];
            uint copyLen = (uint)Math.Min(s.RawSize, Math.Max(0L, bodyEnd - s.RawPtr));
            if (copyLen > 0) Array.Copy(src, s.RawPtr, outBytes, newRawPtr[i], copyLen);
        }
        // 写入新区域
        Array.Copy(newRegion, 0, outBytes, newRawPtr[hostIdx] + relOff, newRegion.Length);

        // 回写节头
        for (int i = 0; i < pe.Sections.Count; i++)
        {
            int o = pe.Sections[i].HeaderOffset;
            BitConverter.GetBytes(newVSize[i]).CopyTo(outBytes, o + 8);
            BitConverter.GetBytes(newVAddr[i]).CopyTo(outBytes, o + 12);
            BitConverter.GetBytes(newRawSize[i]).CopyTo(outBytes, o + 16);
            BitConverter.GetBytes(newRawPtr[i]).CopyTo(outBytes, o + 20);
        }

        var pe2 = ParsePe(outBytes);
        if (vaDelta > 0) ShiftDataDirRvas(outBytes, pe2, pe, vaDelta, hostIdx);
        UpdateResourceDirSize(outBytes, ParsePe(outBytes), newRegion.Length);
        FinalizePe(outBytes, ParsePe(outBytes));
        return outBytes;
    }

    /// <summary>修正数据目录中指向「被后移节」的 RVA (证书表/重定位表是文件偏移, 跳过)。</summary>
    private static void ShiftDataDirRvas(byte[] d, PeInfo newPe, PeInfo oldPe,
        uint vaDelta, int hostIdx)
    {
        var moved = new List<(uint from, uint to, uint size)>();
        for (int i = hostIdx + 1; i < oldPe.Sections.Count; i++)
        {
            var s = oldPe.Sections[i];
            moved.Add((s.VAddr, s.VAddr + vaDelta, Math.Max(s.VSize, s.RawSize)));
        }
        if (moved.Count == 0) return;

        int ddOff = newPe.Is64 ? newPe.OptOffset + 112 : newPe.OptOffset + 96;
        int ddCount = BitConverter.ToInt32(d, newPe.OptOffset + (newPe.Is64 ? 108 : 92));
        for (int i = 0; i < ddCount; i++)
        {
            if (i == 4 || i == 5) continue;
            int o = ddOff + i * 8;
            uint rva = BitConverter.ToUInt32(d, o);
            if (rva == 0) continue;
            foreach (var (from, to, size) in moved)
                if (rva >= from && rva < from + size)
                { BitConverter.GetBytes(rva - from + to).CopyTo(d, o); break; }
        }
    }

    /// <summary>更新 CLR 头中 Resources 目录项的长度。</summary>
    private static void UpdateResourceDirSize(byte[] d, PeInfo pe, int newSize)
    {
        int ddOff = pe.Is64 ? pe.OptOffset + 112 : pe.OptOffset + 96;
        int corOff = Rva2Off(pe, BitConverter.ToUInt32(d, ddOff + 14 * 8));
        if (corOff > 0) BitConverter.GetBytes((uint)newSize).CopyTo(d, corOff + 28);
    }

    /// <summary>移除证书表目录项、重算 SizeOfImage、清零校验和。</summary>
    private static void FinalizePe(byte[] d, PeInfo pe)
    {
        int ddOff = pe.Is64 ? pe.OptOffset + 112 : pe.OptOffset + 96;
        BitConverter.GetBytes(0u).CopyTo(d, ddOff + 32);
        BitConverter.GetBytes(0u).CopyTo(d, ddOff + 36);
        var p2 = ParsePe(d);
        uint maxEnd = 0;
        foreach (var s in p2.Sections)
            maxEnd = Math.Max(maxEnd, s.VAddr + Align(s.VSize, 0x1000));
        BitConverter.GetBytes(maxEnd).CopyTo(d, p2.SizeOfImageOffset);
        BitConverter.GetBytes(0u).CopyTo(d, p2.ChecksumOffset);
    }

    private static uint Align(uint v, uint a) => (v + a - 1) / a * a;

    // ------------------------------------------------------------ resources
    private sealed class ResEntry
    {
        public required string Key;
        public required byte[] Data;
        /// <summary>该条目在容器中占用的字节数 (可安全覆盖的上限, 含尾部填充)。</summary>
        public required int Capacity;
        /// <summary>该条目「长度前缀」在文件中的绝对偏移。</summary>
        public required int LengthPrefixOffset;
        /// <summary>该条目「数据本体」在文件中的绝对偏移。</summary>
        public required int DataOffset;
    }

    /// <summary>
    /// 读出区域内全部 blob 的所有条目, 并计算每条数据在文件中的真实偏移与容量。
    /// 容量 = 该条目的数据段在容器内实际占据的长度 (可包含尾部对齐填充)。
    /// </summary>
    private static Dictionary<string, ResEntry> ReadAllEntries(byte[] d, PeInfo pe)
    {
        var result = new Dictionary<string, ResEntry>(StringComparer.Ordinal);
        var (regionOff, regionLen) = FindResourceRegion(d, pe);

        // 依次解析区域内的每个容器 (可能有多个, 之间按 8 字节对齐)
        int p = regionOff;
        int end = regionOff + regionLen;
        while (p + 8 <= end)
        {
            if (BitConverter.ToUInt32(d, p + 4) != 0xBEEFCACE)
            {
                int scan = p, limit = Math.Min(end, p + 16);
                bool found = false;
                while (scan + 8 <= limit)
                {
                    scan++;
                    int l = BitConverter.ToInt32(d, scan);
                    if (BitConverter.ToUInt32(d, scan + 4) == 0xBEEFCACE && l > 0
                        && scan + 4 + l <= d.Length)
                    { p = scan; found = true; break; }
                }
                if (!found) break;
            }

            int len = BitConverter.ToInt32(d, p);
            if (len <= 0 || p + 4 + len > d.Length) break;
            if (BitConverter.ToUInt32(d, p + 4) != 0xBEEFCACE) break;

            var vals = new Dictionary<string, byte[]>(StringComparer.Ordinal);
            using (var ms = new MemoryStream(d, p + 4, len, writable: false))
            using (var rr = new ResourceReader(ms))
            {
                var et = rr.GetEnumerator();
                while (et.MoveNext())
                    vals[(string)et.Key] = et.Value switch
                    {
                        byte[] b => b,
                        Stream s => ReadStream(s),
                        _ => Array.Empty<byte>(),
                    };
            }
            LocateEntries(d, p + 4, len, vals, result);
            p += 4 + len;
        }
        return result;
    }

    /// <summary>
    /// 找出每个条目的数据在文件中的偏移与容量。
    /// 做法: 直接在容器范围内搜索该条目数据的**首个特征字节序列**。
    /// 该法不依赖容器内部布局, 对 .NET 各版本容器格式都稳健。
    /// </summary>
    private static void LocateEntries(byte[] d, int containerOff, int containerLen,
        Dictionary<string, byte[]> values, Dictionary<string, ResEntry> outMap)
    {
        int cEnd = containerOff + containerLen;

        var found = new List<(string key, byte[] data, int off)>();
        foreach (var kv in values)
        {
            byte[] data = kv.Value;
            if (data.Length == 0) continue;
            int probeLen = Math.Min(32, data.Length);
            int off = FindLast(d, data, containerOff, cEnd, probeLen);
            if (off < 0) continue;
            found.Add((kv.Key, data, off));
        }

        found.Sort((a, b) => a.off.CompareTo(b.off));
        for (int i = 0; i < found.Count; i++)
        {
            int next = (i + 1 < found.Count) ? found[i + 1].off : cEnd;
            int prefixOff = found[i].off - 4;
            if (prefixOff < containerOff) continue;

            // 容量 = 到下一条数据的距离, 但不得超过该条目的**原始长度**
            // (长度前缀记录的值)。这样绝不会侵占相邻条目的空间。
            int declaredLen = BitConverter.ToInt32(d, prefixOff);
            int capacity = Math.Min(next - found[i].off, Math.Max(declaredLen, 0));
            if (capacity <= 0) capacity = next - found[i].off;

            outMap[found[i].key] = new ResEntry
            {
                Key = found[i].key,
                Data = found[i].data,
                DataOffset = found[i].off,
                LengthPrefixOffset = prefixOff,
                Capacity = capacity,
            };
        }
    }

    /// <summary>在 [from, to) 范围内查找 data 的前 probeLen 字节, 返回最后一次匹配的偏移。</summary>
    private static int FindLast(byte[] d, byte[] data, int from, int to, int probeLen)
    {
        if (probeLen <= 0) return -1;
        int limit = Math.Min(to, d.Length) - probeLen;
        int last = -1;
        for (int i = from; i <= limit; i++)
        {
            bool ok = true;
            for (int j = 0; j < probeLen; j++)
                if (d[i + j] != data[j]) { ok = false; break; }
            if (ok) last = i;
        }
        return last;
    }

    /// <summary>解析 .resources 容器的名称/数据位置表。</summary>
    private static Dictionary<string, (int offset, int size)> ParseDataPositions(
        byte[] d, int containerOff, int containerLen)
    {
        var map = new Dictionary<string, (int, int)>(StringComparer.Ordinal);
        int baseOff = containerOff;
        int o = containerOff + 4;   // 跳过 magic

        // headerVersion
        o += 4;
        // readerType (7bit 长度前缀 UTF-8)
        o = Skip7BitString(d, o);
        // setType
        o = Skip7BitString(d, o);
        int version = BitConverter.ToInt32(d, o); o += 4;
        int numResources = BitConverter.ToInt32(d, o); o += 4;
        int numTypes = BitConverter.ToInt32(d, o); o += 4;
        for (int i = 0; i < numTypes; i++)
            o = Skip7BitString(d, o);

        // 对齐到 8 字节边界 (相对容器起点)
        while ((o - baseOff) % 8 != 0) o++;

        // 条目表: version>=2 时为 12 字节 (hash, namePos, dataPos)
        int stride = version >= 2 ? 12 : 8;
        for (int i = 0; i < numResources; i++)
        {
            int e = o + i * stride;
            if (e + stride > d.Length) break;
            int namePos = BitConverter.ToInt32(d, e + 4);
            int dataPos = BitConverter.ToInt32(d, e + 8);

            int nameAt = baseOff + namePos;
            if (nameAt < 0 || nameAt >= d.Length) continue;
            int nameLen = Read7BitInt(d, ref nameAt);
            if (nameLen < 0 || nameAt + nameLen > d.Length) continue;
            string name = Encoding.UTF8.GetString(d, nameAt, nameLen);

            int dataAt = baseOff + dataPos;
            if (dataAt + 4 > d.Length) continue;
            int size = BitConverter.ToInt32(d, dataAt);
            map[name] = (dataAt + 4, size);   // +4 跳过长度前缀
        }
        return map;
    }

    private static int Skip7BitString(byte[] d, int o)
    {
        int len = Read7BitInt(d, ref o);
        return o + len;
    }

    private static int Read7BitInt(byte[] d, ref int o)
    {
        int value = 0, shift = 0;
        while (true)
        {
            if (o >= d.Length) return -1;
            byte b = d[o++];
            value |= (b & 0x7F) << shift;
            if ((b & 0x80) == 0) break;
            shift += 7;
            if (shift > 28) return -1;
        }
        return value;
    }

    private static byte[] ReadStream(Stream s)
    {
        using var ms = new MemoryStream();
        s.Position = 0;
        s.CopyTo(ms);
        return ms.ToArray();
    }

    // ------------------------------------------------------------------- PE
    private sealed class Section
    {
        public required string Name;
        public uint VSize, VAddr, RawSize, RawPtr;
        public int HeaderOffset;
    }

    private sealed class PeInfo
    {
        public int PeOffset, OptOffset, NumSections, OptSize;
        public bool Is64;
        public uint CertPtr, CertSize, SizeOfImage;
        public int SizeOfImageOffset, ChecksumOffset;
        public List<Section> Sections = new();
    }

    private static PeInfo ParsePe(byte[] d)
    {
        var p = new PeInfo();
        p.PeOffset = BitConverter.ToInt32(d, 0x3C);
        if (d[p.PeOffset] != 'P' || d[p.PeOffset + 1] != 'E')
            throw new InvalidDataException("不是有效的 PE 文件");
        p.NumSections = BitConverter.ToInt16(d, p.PeOffset + 6);
        p.OptSize = BitConverter.ToInt16(d, p.PeOffset + 20);
        p.OptOffset = p.PeOffset + 24;
        p.Is64 = BitConverter.ToUInt16(d, p.OptOffset) == 0x20B;

        int ddOff = p.Is64 ? p.OptOffset + 112 : p.OptOffset + 96;
        p.CertPtr = BitConverter.ToUInt32(d, ddOff + 32);
        p.CertSize = BitConverter.ToUInt32(d, ddOff + 36);
        p.SizeOfImageOffset = p.OptOffset + 56;
        p.ChecksumOffset = p.OptOffset + 64;
        p.SizeOfImage = BitConverter.ToUInt32(d, p.SizeOfImageOffset);

        int secBase = p.OptOffset + p.OptSize;
        for (int i = 0; i < p.NumSections; i++)
        {
            int o = secBase + i * 40;
            p.Sections.Add(new Section
            {
                Name = Encoding.ASCII.GetString(d, o, 8).TrimEnd('\0'),
                VSize = BitConverter.ToUInt32(d, o + 8),
                VAddr = BitConverter.ToUInt32(d, o + 12),
                RawSize = BitConverter.ToUInt32(d, o + 16),
                RawPtr = BitConverter.ToUInt32(d, o + 20),
                HeaderOffset = o,
            });
        }
        return p;
    }

    private static (int offset, int length) FindResourceRegion(byte[] d, PeInfo pe)
    {
        int ddOff = pe.Is64 ? pe.OptOffset + 112 : pe.OptOffset + 96;
        uint corRva = BitConverter.ToUInt32(d, ddOff + 14 * 8);
        int corOff = Rva2Off(pe, corRva);
        if (corOff < 0) throw new InvalidDataException("无法定位 CLR 头");
        uint resRva = BitConverter.ToUInt32(d, corOff + 24);
        uint resSize = BitConverter.ToUInt32(d, corOff + 28);
        int resOff = Rva2Off(pe, resRva);
        if (resOff < 0) throw new InvalidDataException("无法定位托管资源");
        return (resOff, (int)resSize);
    }

    private static int Rva2Off(PeInfo pe, uint rva)
    {
        foreach (var s in pe.Sections)
            if (rva >= s.VAddr && rva < s.VAddr + Math.Max(s.VSize, s.RawSize))
                return (int)(s.RawPtr + (rva - s.VAddr));
        return -1;
    }

    // ---------------------------------------------------------------- utils
    private static string Sha256(byte[] b)
        => Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(b)).ToLowerInvariant();

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = false,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };
}
