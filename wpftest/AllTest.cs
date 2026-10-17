// alltest: 对容器内**每一个**条目做 WPF GetStream 检查
// 这是最终的安全门: 任何条目不是 Stream 都会被拒绝。
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Resources;

class AllTest
{
    static int Main(string[] args)
    {
        string dll = Path.GetFullPath(args[0]);
        var asm = Assembly.LoadFrom(dll);
        var rm = new ResourceManager("VOCALOID6.g", asm);

        int total = 0, notStream = 0, getStreamFail = 0;
        var bad = new List<string>();

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
                total++;
                string key = (string)et.Key;
                // 1) 原始类型必须是 Stream
                object obj = et.Value;
                if (!(obj is Stream))
                {
                    notStream++;
                    bad.Add($"{key}: 类型是 {obj?.GetType().Name ?? "null"}, 不是 Stream");
                }
                // 2) WPF 实际走的 GetStream 必须可用
                try
                {
                    var st = rm.GetStream(key);
                    if (st == null || st.Length == 0)
                    { getStreamFail++; bad.Add($"{key}: GetStream 返回空"); }
                }
                catch (Exception e)
                {
                    getStreamFail++;
                    bad.Add($"{key}: GetStream 抛 {e.GetType().Name}");
                }
            }
        }

        Console.WriteLine($"条目总数: {total}");
        Console.WriteLine($"非 Stream 类型: {notStream}");
        Console.WriteLine($"GetStream 失败: {getStreamFail}");
        foreach (var b in bad.GetRange(0, Math.Min(15, bad.Count)))
            Console.WriteLine("  !! " + b);

        bool ok = (notStream == 0 && getStreamFail == 0);
        Console.WriteLine(ok ? "结果: 全部通过 (WPF 可用)" : "结果: 存在不可用条目");
        return ok ? 0 : 1;
    }
}
