// mres2: 用 System.Reflection.Metadata 正确定位每个资源容器的 offset,
// 并演示如何把它改写到新位置。
using System;
using System.Collections.Immutable;
using System.IO;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;

class Mres2
{
    static void Main(string[] args)
    {
        string p = args[0];
        using var fs = File.OpenRead(p);
        using var pe = new PEReader(fs);
        var md = pe.GetMetadataReader();

        Console.WriteLine($"ManifestResource 数量 = {md.ManifestResources.Count}");
        foreach (var handle in md.ManifestResources)
        {
            var mr = md.GetManifestResource(handle);
            string name = md.GetString(mr.Name);
            bool isPublic = (mr.Attributes & System.Reflection.ManifestResourceAttributes.Public) != 0;
            string impl;
            if (mr.Implementation.IsNil) impl = "<本程序集末尾>";
            else if (mr.Implementation.Kind == HandleKind.AssemblyFile)
                impl = "file " + md.GetString(md.GetAssemblyFile((AssemblyFileHandle)mr.Implementation).Name);
            else impl = mr.Implementation.Kind.ToString();

            Console.WriteLine($"  offset={mr.Offset,12:N0} (0x{mr.Offset:X8})  " +
                              $"public={isPublic}  name='{name}'  impl={impl}");
        }
    }
}
