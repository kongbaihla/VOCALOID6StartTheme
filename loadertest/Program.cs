// loader-test: 真实加载改写后的 DLL, 验证资源可解析
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Resources;

class LoaderTest
{
    static int Main(string[] args)
    {
        if (args.Length < 1) { Console.Error.WriteLine("用法: loader-test <dll>"); return 2; }
        string dll = Path.GetFullPath(args[0]);
        Console.WriteLine($"加载: {dll}  ({new FileInfo(dll).Length:N0} 字节)");

        try
        {
            var asm = Assembly.LoadFrom(dll);
            Console.WriteLine($"  程序集名: {asm.FullName}");

            var names = asm.GetManifestResourceNames();
            Console.WriteLine($"  清单资源: {string.Join(", ", names)}");

            int total = 0;
            byte[]? splash = null;
            byte[]? splashDev = null;

            foreach (var rn in names)
            {
                using var s = asm.GetManifestResourceStream(rn);
                if (s == null) { Console.WriteLine($"  [{rn}] stream=null"); continue; }
                var ms = new MemoryStream();
                try { s.CopyTo(ms); }
                catch (Exception ex)
                {
                    Console.WriteLine($"  [{rn}] 读取流失败: {ex.GetType().Name}: {ex.Message}");
                    continue;
                }
                byte[] raw = ms.ToArray();
                Console.WriteLine($"  [{rn}] {raw.Length:N0} 字节, 头8={BitConverter.ToString(raw, 0, Math.Min(8, raw.Length))}");

                void Harvest(ResourceReader rr)
                {
                    var et = rr.GetEnumerator();
                    while (et.MoveNext())
                    {
                        total++;
                        string k = (string)et.Key;
                        if (k != "assets/splash.png" && k != "assets/splash_dev.png") continue;
                        byte[]? got = et.Value switch
                        {
                            byte[] bb => bb,
                            Stream st => ReadAll(st),
                            _ => null
                        };
                        if (k == "assets/splash.png") splash = got; else splashDev = got;
                    }
                }

                // 形态1: 以 4 字节长度前缀开头的容器
                bool parsed = false;
                if (raw.Length > 8)
                {
                    int blobLen = BitConverter.ToInt32(raw, 0);
                    if (blobLen > 0 && blobLen + 4 <= raw.Length)
                    {
                        try
                        {
                            using var inner = new MemoryStream(raw, 4, blobLen, false);
                            using var rr = new ResourceReader(inner);
                            Harvest(rr);
                            parsed = true;
                        }
                        catch { }
                    }
                }
                // 形态2: 直接就是资源容器 (无长度前缀)
                if (!parsed)
                {
                    try
                    {
                        using var inner = new MemoryStream(raw, 0, raw.Length, false);
                        using var rr = new ResourceReader(inner);
                        Harvest(rr);
                    }
                    catch (Exception ex) { Console.WriteLine($"    无法作为资源容器解析: {ex.Message}"); }
                }
            }

            Console.WriteLine($"  资源条目总数: {total}");
            bool ok = true;
            foreach (var (label, bytes) in new[] { ("splash.png", splash), ("splash_dev.png", splashDev) })
            {
                if (bytes == null) { Console.WriteLine($"  !! 未找到 assets/{label}"); ok = false; continue; }
                bool png = bytes.Length > 8 && bytes[0] == 0x89 && bytes[1] == 0x50
                           && bytes[2] == 0x4E && bytes[3] == 0x47;
                string sha = Convert.ToHexString(
                    System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
                Console.WriteLine($"  assets/{label}: {bytes.Length:N0} 字节  PNG={png}  SHA256={sha}");
                if (!png) ok = false;
            }
            Console.WriteLine(ok ? "结果: 加载成功" : "结果: 加载异常");
            return ok ? 0 : 1;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"结果: 加载失败 -> {ex.GetType().Name}: {ex.Message}");
            return 1;
        }
    }

    static byte[] ReadAll(Stream s)
    {
        using var m = new MemoryStream();
        s.Position = 0;
        s.CopyTo(m);
        return m.ToArray();
    }
}
