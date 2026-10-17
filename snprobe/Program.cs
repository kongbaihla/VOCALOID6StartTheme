using System;
using System.Reflection;
using dnlib.DotNet;

class P {
    static void Main(string[] a) {
        foreach (var path in a) {
            Console.WriteLine("=== " + path);
            try {
                var an = AssemblyName.GetAssemblyName(path);
                var pk = an.GetPublicKey();
                var pkt = an.GetPublicKeyToken();
                Console.WriteLine($"  AssemblyName: {an.FullName}");
                Console.WriteLine($"  PublicKey 长度: {pk?.Length ?? 0}");
                Console.WriteLine($"  PublicKeyToken: {(pkt==null||pkt.Length==0 ? "<null>" : BitConverter.ToString(pkt))}");
                Console.WriteLine($"  强名称: {(pk!=null && pk.Length>0 ? "是" : "否")}");
            } catch (Exception e) { Console.WriteLine("  AssemblyName 失败: " + e.Message); }

            try {
                var m = ModuleDefMD.Load(path);
                var asm = m.Assembly;
                Console.WriteLine($"  dnlib Assembly: {asm?.FullName}");
                Console.WriteLine($"  dnlib PublicKey: {(asm?.PublicKey?.Data?.Length ?? 0)} 字节");
                Console.WriteLine($"  HasPublicKey 标志: {asm?.HasPublicKey}");
                
                Console.WriteLine($"  Cor20 运行时版本: {m.RuntimeVersion}");
                // 检查资源
                foreach (var r in m.Resources)
                    Console.WriteLine($"  资源: {r.Name} flags={r.Attributes} offset=0x{r.Offset:X}");
                m.Dispose();
            } catch (Exception e) { Console.WriteLine("  dnlib 失败: " + e.Message); }
            Console.WriteLine();
        }
    }
}
