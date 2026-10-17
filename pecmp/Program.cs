// pecmp: 逐字段对比两个 PE 文件
using System;
using System.Collections.Generic;
using System.IO;

class PeCmp
{
    record Sec(string Name, uint VSize, uint VAddr, uint RawSize, uint RawPtr, uint Chars);

    static (int pe, int nsec, int opt, int optsize, ushort magic,
            List<Sec> secs, uint[] dd, uint sizeImg, uint checksum,
            uint sizeHdr, uint fileAlign, uint secAlign, ushort dllChars)
        Parse(byte[] d)
    {
        int pe = BitConverter.ToInt32(d, 0x3C);
        int nsec = BitConverter.ToInt16(d, pe + 6);
        int optsize = BitConverter.ToInt16(d, pe + 20);
        ushort dllChars = BitConverter.ToUInt16(d, pe + 22);
        int opt = pe + 24;
        ushort magic = BitConverter.ToUInt16(d, opt);
        uint fileAlign = BitConverter.ToUInt32(d, opt + 36);
        uint secAlign = BitConverter.ToUInt32(d, opt + 32);
        uint sizeImg = BitConverter.ToUInt32(d, opt + 56);
        uint sizeHdr = BitConverter.ToUInt32(d, opt + 60);
        uint checksum = BitConverter.ToUInt32(d, opt + 64);
        int ddOff = magic == 0x20B ? opt + 112 : opt + 96;
        int ndd = BitConverter.ToInt32(d, opt + (magic == 0x20B ? 108 : 92));
        var dd = new uint[ndd * 2];
        for (int i = 0; i < ndd * 2; i++) dd[i] = BitConverter.ToUInt32(d, ddOff + i * 4);

        var secs = new List<Sec>();
        int sb = opt + optsize;
        for (int i = 0; i < nsec; i++)
        {
            int o = sb + i * 40;
            secs.Add(new Sec(
                System.Text.Encoding.ASCII.GetString(d, o, 8).TrimEnd('\0'),
                BitConverter.ToUInt32(d, o + 8), BitConverter.ToUInt32(d, o + 12),
                BitConverter.ToUInt32(d, o + 16), BitConverter.ToUInt32(d, o + 20),
                BitConverter.ToUInt32(d, o + 36)));
        }
        return (pe, nsec, opt, optsize, magic, secs, dd, sizeImg, checksum,
                sizeHdr, fileAlign, secAlign, dllChars);
    }

    static void Main(string[] a)
    {
        var A = File.ReadAllBytes(a[0]);
        var B = File.ReadAllBytes(a[1]);
        var pa = Parse(A); var pb = Parse(B);
        Console.WriteLine($"A = {Path.GetFileName(a[0])}  ({A.Length:N0} 字节)");
        Console.WriteLine($"B = {Path.GetFileName(a[1])}  ({B.Length:N0} 字节)");
        Console.WriteLine();

        void Cmp(string name, object x, object y)
        {
            bool same = x?.ToString() == y?.ToString();
            string mark = same ? "  " : "<<";
            Console.WriteLine($"  {mark} {name,-22} A={x,-22} B={y}");
        }

        Console.WriteLine("--- PE 头 ---");
        Cmp("DllCharacteristics", $"0x{pa.dllChars:X4}", $"0x{pb.dllChars:X4}");
        Cmp("FileAlignment", pa.fileAlign, pb.fileAlign);
        Cmp("SectionAlignment", pa.secAlign, pb.secAlign);
        Cmp("SizeOfHeaders", pa.sizeHdr, pb.sizeHdr);
        Cmp("SizeOfImage", $"0x{pa.sizeImg:X}", $"0x{pb.sizeImg:X}");
        Cmp("Checksum", $"0x{pa.checksum:X}", $"0x{pb.checksum:X}");

        Console.WriteLine("\n--- 数据目录 ---");
        string[] dn = { "Export", "Import", "Resource", "Exception", "Certificate",
            "Reloc", "Debug", "Arch", "GlobalPtr", "TLS", "LoadConfig", "BoundImport",
            "IAT", "DelayImport", "CLR", "Reserved" };
        for (int i = 0; i < Math.Min(16, pa.dd.Length / 2); i++)
        {
            uint ra = pa.dd[i * 2], sa = pa.dd[i * 2 + 1];
            uint rb = pb.dd[i * 2], sb = pb.dd[i * 2 + 1];
            bool same = ra == rb && sa == sb;
            if (!same)
                Console.WriteLine($"  << [{i,2}] {dn[i],-12} A=(0x{ra:X8},{sa,10})  B=(0x{rb:X8},{sb,10})");
        }

        Console.WriteLine("\n--- 节表 ---");
        Console.WriteLine($"  A: {pa.nsec} 节");
        foreach (var s in pa.secs)
            Console.WriteLine($"     {s.Name,-8} VA=0x{s.VAddr:X8} VSize=0x{s.VSize:X8} " +
                              $"Raw=0x{s.RawPtr:X8} RawSize=0x{s.RawSize:X8} Chars=0x{s.Chars:X8}");
        Console.WriteLine($"  B: {pb.nsec} 节");
        foreach (var s in pb.secs)
            Console.WriteLine($"     {s.Name,-8} VA=0x{s.VAddr:X8} VSize=0x{s.VSize:X8} " +
                              $"Raw=0x{s.RawPtr:X8} RawSize=0x{s.RawSize:X8} Chars=0x{s.Chars:X8}");

        // 节内容差异
        Console.WriteLine("\n--- 节内容对比 ---");
        for (int i = 0; i < Math.Min(pa.nsec, pb.nsec); i++)
        {
            var sa = pa.secs[i]; var sb2 = pb.secs[i];
            int len = (int)Math.Min(sa.RawSize, sb2.RawSize);
            int diff = 0, first = -1;
            for (int k = 0; k < len; k++)
            {
                if (A[sa.RawPtr + k] != B[sb2.RawPtr + k])
                { diff++; if (first < 0) first = k; }
            }
            Console.WriteLine($"  {sa.Name,-8} 长度={len:N0} 差异字节={diff:N0}" +
                              (first >= 0 ? $"  首个差异@+0x{first:X}" : ""));
        }
    }
}
