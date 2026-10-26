using System;
using System.Runtime.InteropServices;
public static class Mdid {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr LoadLibraryEx(string file, IntPtr reserved, uint flags);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr FindResource(IntPtr module, IntPtr name, string type);
 [DllImport("kernel32.dll")] static extern IntPtr LoadResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll")] static extern IntPtr LockResource(IntPtr resource);
 [DllImport("kernel32.dll")] static extern uint SizeofResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr module);
 public static string Read(string path) {
  IntPtr mod=LoadLibraryEx(path,IntPtr.Zero,2); if(mod==IntPtr.Zero) throw new Exception("Não foi possível ler o APX: "+path);
  try { IntPtr r=FindResource(mod,(IntPtr)32500,"MDID"); if(r==IntPtr.Zero) throw new Exception("MDID não encontrado: "+path);
   byte[] data=new byte[SizeofResource(mod,r)]; Marshal.Copy(LockResource(LoadResource(mod,r)),data,0,data.Length); return BitConverter.ToString(data);
  } finally {FreeLibrary(mod);}
 }
 public static void Main(string[] args){foreach(string p in args) Console.WriteLine(p+" = "+Read(p));}
}
