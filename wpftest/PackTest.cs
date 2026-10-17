// packtest: 模拟 WPF 启动时最真实的资源加载路径
// WPF 用 ResourceManager("VOCALOID6.g", asm).GetStream(name) 取得 baml/png,
// 并且 **要求返回 Stream**(而非 byte[])。这里逐一检查。
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Resources;

class PackTest
{
    static int Main(string[] args)
    {
        string dll = Path.GetFullPath(args[0]);
        Console.WriteLine($"测试: {Path.GetFileName(dll)}");
        var asm = Assembly.LoadFrom(dll);

        // 与 WPF 一致地构造 ResourceManager
        ResourceManager rm;
        try { rm = new ResourceManager("VOCALOID6.g", asm); }
        catch (Exception e)
        {
            Console.WriteLine($"  ResourceManager 构造失败: {e.Message}");
            return 1;
        }

        string[] keys =
        {
            "mainwindow/splashwindow.baml",
            "assets/splash.png",
            "assets/icon.ico",
            "assets/stylepanelicon.baml",
            "app.baml",
            "mainwindow/mainwindow.baml",
        };

        int problems = 0;
        foreach (var k in keys)
        {
            // 1) GetObject —— WPF 内部常走这条
            object obj = null;
            try { obj = rm.GetObject(k); }
            catch (Exception e) { Console.WriteLine($"  {k}: GetObject 抛异常 {e.GetType().Name}"); problems++; continue; }

            // 2) GetStream —— WPF 对 baml 走这条, **必须返回 Stream**
            Stream st = null;
            try { st = rm.GetStream(k); }
            catch (Exception e) { Console.WriteLine($"  {k}: GetStream 抛异常 {e.GetType().Name}: {e.Message}"); problems++; }

            string ot = obj?.GetType().Name ?? "null";
            string stt = st?.GetType().Name ?? "null";
            bool isStream = obj is Stream;
            bool streamOk = st is Stream && st.Length > 0;

            string mark = (obj != null && streamOk) ? "OK " : "!! ";
            if (obj == null || !streamOk) problems++;
            Console.WriteLine($"  {mark}{k,-38} GetObject={ot,-28} GetStream={stt,-24} " +
                              $"是Stream={isStream} 流可用={streamOk}");
        }

        Console.WriteLine();
        Console.WriteLine(problems == 0 ? "结果: WPF 资源路径全部可用" : $"结果: {problems} 项异常");
        return problems == 0 ? 0 : 1;
    }
}
