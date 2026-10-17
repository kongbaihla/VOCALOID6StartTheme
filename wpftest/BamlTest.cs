// bamltest: 真正尝试用 WPF 解析 BAML —— 这是启动时 splash 窗口要做的事
using System;
using System.IO;
using System.Reflection;
using System.Resources;
using System.Windows;
using System.Windows.Baml2006;
using System.Xaml;

class BamlTest
{
    static int Main(string[] args)
    {
        string dll = Path.GetFullPath(args[0]);
        Console.WriteLine($"测试: {Path.GetFileName(dll)}");
        var asm = Assembly.LoadFrom(dll);

        foreach (var rn in asm.GetManifestResourceNames())
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
                if (!key.EndsWith(".baml")) continue;
                if (key != "mainwindow/splashwindow.baml") continue;

                object val = et.Value;
                Console.WriteLine($"  {key}: 类型={val?.GetType().Name}");

                byte[] baml = val switch
                {
                    byte[] b => b,
                    Stream st => ReadAll(st),
                    _ => null
                };
                if (baml == null) { Console.WriteLine("    无法取得字节"); continue; }
                Console.WriteLine($"    大小={baml.Length}  头8={BitConverter.ToString(baml, 0, 8)}");

                // 尝试用 WPF 的 BAML 读取器解析 (真实启动路径)
                try
                {
                    using var bs = new MemoryStream(baml, false);
                    var reader = new Baml2006Reader(bs);
                    int nodes = 0;
                    while (reader.Read()) nodes++;
                    Console.WriteLine($"    [BAML 解析成功] 节点数={nodes}");
                }
                catch (Exception e)
                {
                    Console.WriteLine($"    [BAML 解析失败] {e.GetType().Name}: {e.Message}");
                    return 1;
                }
            }
        }
        Console.WriteLine("结果: 通过");
        return 0;
    }

    static byte[] ReadAll(Stream s)
    {
        using var m = new MemoryStream();
        s.Position = 0; s.CopyTo(m);
        return m.ToArray();
    }
}
