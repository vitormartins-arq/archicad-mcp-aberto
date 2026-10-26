using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.IO.Compression;

public static class InstallerTests {
 static int passed;
 static void Check(bool value,string label){if(!value) throw new Exception(label);passed++;Console.WriteLine("PASS "+label);}
 static void Reject(Action action,string label){try{action();}catch{passed++;Console.WriteLine("PASS "+label);return;}throw new Exception("Expected rejection: "+label);}
 static string Stage(string root,PackageInfo c,string sample) {string p=Path.Combine(root,"(stage-"+Guid.NewGuid().ToString("N")+")");Directory.CreateDirectory(p);File.Copy(sample,Path.Combine(p,c.apx));return p;}
 public static void Main(string[] args) {
  string sample=args[0],root=Path.Combine(Path.GetTempPath(),"LAB-installer-tests-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
  var c=new PackageInfo{product="LAB - Complemento MCP",mdid=Mdid.Read(sample),apx="LAB - Complemento MCP.apx",files=new Dictionary<string,string>{{"LAB - Complemento MCP.apx",InstallCore.Hash(sample)}}};
  Reject(()=>InstallCore.Inside(root,"../outside"),"reject parent traversal");
  Reject(()=>InstallCore.Inside(root,"C:/outside"),"reject rooted path");
  Reject(()=>InstallCore.Inside(root,"file.apx:stream"),"reject alternate streams");
  Reject(()=>InstallCore.Inside(root,"sub\\file.apx"),"reject ambiguous separators");
  string uriPath="C:\\Program Files\\Graphisoft\\Archicad 30\\Extensões\\LAB - Complemento MCP.apx";
  Check(InstallCore.DecodePath(InstallCore.EncodePath(uriPath))==uriPath,"Graphisoft Include URI roundtrip with spaces and accents");
  var r=InstallCore.Prepare(root,c);string stage=Stage(root,c,sample);
  bool registered=false;
  InstallCore.Apply(r,stage,c,()=>registered=true,()=>registered=false);
  Check(registered&&File.Exists(Path.Combine(r.target,c.apx)),"first install and registry callback");
  File.WriteAllText(Path.Combine(r.target,"old-engine.txt"),"old runtime");
  string loose=Path.Combine(root,"old-name.apx");File.Copy(sample,loose);
  File.WriteAllText(Path.Combine(root,"D5.apx"),"unrelated fixture");
  var update=InstallCore.Prepare(root,c);
  Check(update.paths.Count==2,"find previous managed folder and loose MDID duplicate");
  InstallCore.Apply(update,Stage(root,c,sample),c,()=>{},()=>{});
  Check(!File.Exists(loose)&&!File.Exists(Path.Combine(update.target,"old-engine.txt")),"remove old active APX and obsolete runtime");
  Check(File.Exists(Path.Combine(root,"D5.apx")),"preserve unrelated add-on");
  Check(InstallCore.Duplicates(root,update.target,c).Count==0,"backups ignored by recursive scan");
  InstallCore.Restore(update,()=>{});
  Check(File.Exists(loose)&&File.Exists(Path.Combine(update.target,"old-engine.txt")),"restore previous folder and loose APX");
  var failure=InstallCore.Prepare(root,c);bool reverted=false;
  Reject(()=>InstallCore.Apply(failure,Stage(root,c,sample),c,()=>{throw new Exception("registry simulation");},()=>reverted=true),"rollback on registry failure");
  Check(reverted&&File.Exists(loose)&&File.Exists(Path.Combine(failure.target,"old-engine.txt")),"rollback restores old files and registry callback");
  string corrupt=Stage(root,c,sample);File.AppendAllText(Path.Combine(corrupt,c.apx),"broken");
  Reject(()=>InstallCore.Apply(InstallCore.Prepare(root,c),corrupt,c,()=>{},()=>{}),"reject corrupted payload before replacement");
  Check(File.Exists(loose),"corrupted update leaves active copy intact");
  var unresolved=InstallCore.Prepare(root,c);Directory.CreateDirectory(unresolved.backupRoot);InstallCore.Save(unresolved);
  Reject(()=>InstallCore.Prepare(root,c),"refuse repeating an incomplete transaction");
  unresolved.status="revertido";InstallCore.Save(unresolved);
  string evil=Path.Combine(root,"(evil-stage)");Directory.CreateDirectory(evil);
  using(var m=new MemoryStream()) {
   using(var zip=new ZipArchive(m,ZipArchiveMode.Create,true)) using(var s=zip.CreateEntry("../escape.apx").Open()) s.WriteByte(1);
   m.Position=0;Reject(()=>InstallCore.Extract(m,evil,c),"reject zip escape before write");
  }
  string unexpected=Path.Combine(root,c.product,"unknown.apx");File.WriteAllText(unexpected,"unrelated");
  Reject(()=>InstallCore.Prepare(root,c),"refuse mixed destination with unknown APX");
  Console.WriteLine(passed+" checks passed; fixtures retained at "+root);
 }
}
