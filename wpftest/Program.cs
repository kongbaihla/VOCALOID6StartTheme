// wpftest: 模拟 WPF 的资源加载路径
// WPF 通过 Assembly.GetManifestResourceStream + 资源名查找 baml/png,
// 并用 pack URI 解析。这个测试检查真实启动时的关键环节。
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Resources;
using System.Windows;

class WpfTest
{
    static int Main(string[] args)
    {
        string dll = Path.GetFullPath(args[0]);
        Console.WriteLine($"测试: {Path.GetFileName(dll)}  ({new FileInfo(dll).Length:N0} 字节)");

        Assembly asm;
        try { asm = Assembly.LoadFrom(dll); }
        catch (Exception e) { Console.WriteLine($"  [失败] 加载: {e.GetType().Name}: {e.Message}"); return 1; }
        Console.WriteLine($"  加载 OK: {asm.FullName}");

        // 1) 清单资源
        string[] names = asm.GetManifestResourceNames();
        Console.WriteLine($"  清单资源: {string.Join(", ", names)}");

        // 2) 逐个读取 g.resources, 枚举全部条目并验证每个条目的数据可完整读出
        int total = 0, bad = 0;
        var errs = new List<string>();
        foreach (var rn in names)
        {
            if (!rn.EndsWith(".g.resources")) continue;
            using var s = asm.GetManifestResourceStream(rn);
            if (s == null) { Console.WriteLine($"  [{rn}] null"); continue; }
            var ms = new MemoryStream();
            s.CopyTo(ms);
            byte[] raw = ms.ToArray();

            using var inner = new MemoryStream(raw, 0, raw.Length, false);
            using var rr = new ResourceReader(inner);
            var et = rr.GetEnumerator();
            while (et.MoveNext())
            {
                total++;
                string key = (string)et.Key;
                try
                {
                    object v = et.Value;
                    byte[] data = v switch
                    {
                        byte[] b => b,
                        Stream st => ReadAll(st),
                        _ => Array.Empty<byte>()
                    };
                    if (data.Length == 0)
                    { bad++; errs.Add($"{key}: 空数据"); }
                }
                catch (Exception e)
                { bad++; errs.Add($"{key}: {e.GetType().Name} {e.Message}"); }
            }
        }
        Console.WriteLine($"  资源条目: {total}  异常: {bad}");
        foreach (var e in errs.GetRange(0, Math.Min(10, errs.Count)))
            Console.WriteLine($"    !! {e}");

        // 3) 关键: 验证 splash.png 是合法 PNG, 且尺寸正确
        foreach (var rn in names)
        {
            if (!rn.EndsWith(".g.resources")) continue;
            using var s = asm.GetManifestResourceStream(rn);
            var ms = new MemoryStream(); s.CopyTo(ms);
            byte[] raw = ms.ToArray();
            using var inner = new MemoryStream(raw, 0, raw.Length, false);
            using var rr = new ResourceReader(inner);
            var et = rr.GetEnumerator();
            while (et.MoveNext())
            {
                string key = (string)et.Key;
                if (key != "assets/splash.png") continue;
                byte[] png = et.Value switch
                { byte[] b => b, Stream st => ReadAll(st), _ => null };
                if (png == null) { Console.WriteLine("  splash: null"); continue; }
                bool sig = png.Length > 8 && png[0]==0x89 && png[1]==0x50 && png[2]==0x4E && png[3]==0x47;
                int w = 0, h = 0;
                if (sig && png.Length > 24)
                {
                    w = (png[16]<<24)|(png[17]<<16)|(png[18]<<8)|png[19];
                    h = (png[20]<<24)|(png[21]<<16)|(png[22]<<8)|png[23];
                }
                bool iend = false;
                for (int i = png.Length - 12; i >= 0 && i < png.Length - 4; i++)
                    if (png[i]=='I'&&png[i+1]=='E'&&png[i+2]=='N'&&png[i+3]=='D') { iend = true; break; }
                Console.WriteLine($"  splash.png: {png.Length:N0} 字节  签名={sig}  {w}x{h}  含IEND={iend}");
            }
        }

        // 4) 模拟 WPF 的 pack URI 资源查找 (核心!)
        //    WPF 内部用 ResourceManager 按 "assets/splash.png" 查 baml/png
        try
        {
            var rm = new ResourceManager("VOCALOID6.g", asm);
            var obj = rm.GetObject("assets/splash.png");
            Console.WriteLine($"  ResourceManager('VOCALOID6.g') 查 assets/splash.png: " +
                              (obj == null ? "null" : obj.GetType().Name));
            var baml = rm.GetObject("mainwindow/splashwindow.baml");
            Console.WriteLine($"  ResourceManager 查 splashwindow.baml: " +
                              (baml == null ? "null" : baml.GetType().Name));
        }
        catch (Exception e)
        {
            Console.WriteLine($"  [失败] ResourceManager: {e.GetType().Name}: {e.Message}");
            return 1;
        }

        Console.WriteLine(bad == 0 ? "结果: 全部通过" : "结果: 存在异常");
        return bad == 0 ? 0 : 1;
    }

    static byte[] ReadAll(Stream s)
    {
        using var m = new MemoryStream();
        s.Position = 0; s.CopyTo(m);
        return m.ToArray();
    }
}
