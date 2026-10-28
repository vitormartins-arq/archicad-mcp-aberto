using System;
using System.Runtime.InteropServices;
public static class Mdid {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr LoadLibraryEx(string file, IntPtr reserved, uint flags);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr FindResource(IntPtr module, IntPtr name, string type);
 [DllImport("kernel32.dll")] static extern IntPtr LoadResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll")] static extern IntPtr LockResource(IntPtr resource);
 [DllImport("kernel32.dll")] static extern uint SizeofResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr module);
 public static string ReadOptional(string path) {
  IntPtr mod=LoadLibraryEx(path,IntPtr.Zero,2); if(mod==IntPtr.Zero) throw new Exception("Não foi possível ler o APX: "+path);
  try { IntPtr r=FindResource(mod,(IntPtr)32500,"MDID"); if(r==IntPtr.Zero) return null;
   uint size=SizeofResource(mod,r);if(size<8||size>256) throw new Exception("MDID inválido: "+path);
   IntPtr dataPtr=LockResource(LoadResource(mod,r));if(dataPtr==IntPtr.Zero) throw new Exception("Não foi possível ler o recurso MDID: "+path);
   byte[] data=new byte[size]; Marshal.Copy(dataPtr,data,0,data.Length); return BitConverter.ToString(data);
  } finally {FreeLibrary(mod);}
 }
 public static string Read(string path) {string value=ReadOptional(path);if(value==null) throw new Exception("MDID não encontrado: "+path);return value;}
 public static void Main(string[] args){foreach(string p in args) Console.WriteLine(p+" = "+Read(p));}
}
