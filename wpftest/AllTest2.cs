// alltest2: 正确复现 WPF 的加载路径
//
// 关键: WPF 内部是 ResourceManagerWrapper, 它用**基名(baseName)**构造
// ResourceManager, baseName 来自程序集名 + ".g"。
// 之前我用固定名 "VOCALOID6.g", 而 ResourceReader 直读会自行解析类型,
// 所以掩盖了类型码问题 —— 必须走 ResourceManager.GetStream 才算数。
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Resources;

class AllTest2
{
    static int Main(string[] args)
    {
        string dll = Path.GetFullPath(args[0]);
        var asm = Assembly.LoadFrom(dll);
        string asmName = asm.GetName().Name;
        Console.WriteLine($"程序集: {asmName}");

        // WPF 用的 baseName: <AssemblyName>.g
        string baseName = asmName + ".g";
        ResourceManager rm;
        try { rm = new ResourceManager(baseName, asm); }
        catch (Exception e)
        {
            Console.WriteLine($"ResourceManager(\"{baseName}\") 构造失败: {e.Message}");
            return 2;
        }

        // 收集全部键 (只取 .g.resources 容器 —— WPF 的资源都在这里)
        var keys = new List<string>();
        foreach (var rn in asm.GetManifestResourceNames())
        {
            if (!rn.EndsWith(".g.resources")) continue;
            using var s = asm.GetManifestResourceStream(rn);
            var ms = new MemoryStream(); s.CopyTo(ms);
            byte[] raw = ms.ToArray();
            try
            {
                using var inner = new MemoryStream(raw, 0, raw.Length, false);
                using var rr = new ResourceReader(inner);
                var et = rr.GetEnumerator();
                while (et.MoveNext()) keys.Add((string)et.Key);
            }
            catch { }
        }
        Console.WriteLine($"键总数: {keys.Count}");

        int ok = 0; var bad = new List<string>();
        foreach (var key in keys)
        {
            try
            {
                var st = rm.GetStream(key);
                if (st != null && st.Length > 0) ok++;
                else bad.Add($"{key}: 空流");
            }
            catch (Exception e)
            {
                bad.Add($"{key}: {e.GetType().Name}: {e.Message.Split('\n')[0]}");
            }
        }

        Console.WriteLine($"GetStream 成功: {ok}");
        Console.WriteLine($"GetStream 失败: {bad.Count}");
        foreach (var b in bad.GetRange(0, Math.Min(12, bad.Count)))
            Console.WriteLine("  !! " + b);

        bool pass = bad.Count == 0;
        Console.WriteLine(pass ? "结果: 全部通过 (WPF 可用)" : "结果: 存在不可用条目 -> 启动会崩溃");
        return pass ? 0 : 1;
    }
}
