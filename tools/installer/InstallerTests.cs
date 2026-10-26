using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.IO.Compression;
using System.Reflection;

public static class InstallerTests {
 static int passed;
 static void Check(bool value,string label){if(!value) throw new Exception(label);passed++;Console.WriteLine("PASS "+label);}
 static void Reject(Action action,string label){try{action();}catch{passed++;Console.WriteLine("PASS "+label);return;}throw new Exception("Expected rejection: "+label);}
 static string Stage(string root,PackageInfo c,string sample) {string p=Path.Combine(root,"(stage-"+Guid.NewGuid().ToString("N")+")");Directory.CreateDirectory(p);File.Copy(sample,Path.Combine(p,c.apx));return p;}
 public static void Main(string[] args) {
  string sample=args[0],root=Path.Combine(Path.GetTempPath(),"LAB-installer-tests-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
  var c=new PackageInfo{product="LAB - Complemento MCP",archicad=30,mdid=Mdid.Read(sample),apx="LAB - Complemento MCP.apx",files=new Dictionary<string,string>{{"LAB - Complemento MCP.apx",InstallCore.Hash(sample)}}};
  string host=Path.Combine(root,"host"),ext=Path.Combine(host,"Extensões");Directory.CreateDirectory(ext);File.Copy(sample,Path.Combine(host,"Archicad.exe"));
  Check(InstallCore.ResolveExtensions(ext,30,p=>30)==ext,"accept selected native Extensions directory");
  Check(InstallCore.ResolveExtensions(host,30,p=>30)==ext,"normalize legacy Archicad root to Extensions");
  Reject(()=>InstallCore.ResolveExtensions(ext,29,p=>30),"reject incompatible Archicad major");
  string foreign=Path.Combine(root,"AI Assistant.apx");File.Copy(Assembly.GetExecutingAssembly().Location,foreign);
  Check(Mdid.ReadOptional(foreign)==null,"valid PE without legacy MDID is unrelated");
  Check(!InstallCore.RegisteredCopyMatches(foreign,c.mdid),"Graphisoft-like Include without MDID does not block installation");
  Reject(()=>Mdid.Read(foreign),"our payload identity check remains strict");
  string deleted=Path.Combine(root,"already-deleted.apx");
  Check(!InstallCore.RegisteredCopyMatches(deleted,c.mdid),"stale Include after manual deletion is ignored");
  string empty=Path.Combine(ext,c.product);Directory.CreateDirectory(empty);
  var emptyPlan=InstallCore.Prepare(ext,c);
  Check(emptyPlan.paths.Count==1&&emptyPlan.paths[0].source==empty,"preserve empty native folder after manual APX removal");
  InstallCore.Apply(emptyPlan,Stage(root,c,sample),c,()=>{},()=>{});
  Check(File.Exists(Path.Combine(empty,c.apx)),"install into previously emptied native folder");
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
  if(args.Length>1) {
   string real=InstallCore.ResolveExtensions(args[1],30);
   Check(InstallCore.ResolveExtensions(Directory.GetParent(real).FullName,30)==real,"actual notebook root and Extensions resolve to same native destination (read only)");
   var realPlan=InstallCore.Prepare(real,c);Installer.PrepareRegistry(realPlan,real,c);
   Check(realPlan.written.Count>0&&realPlan.written.All(x=>InstallCore.DecodePath(x.value)==Path.Combine(real,c.product,c.apx)),"actual notebook Include preflight passes without modifying registry");
   Check(realPlan.registry.All(x=>!x.value.Contains("AI%20Assistant")),"actual Graphisoft AI Assistant registration remains unrelated");
   if(args.Length>2) {
    var importer=new PackageInfo{product="LAB - Importador de Blocos e Texturas",archicad=30,mdid=Mdid.Read(args[2]),apx="ImportadorOBJ.apx"};
    var importerPlan=InstallCore.Prepare(real,importer);Installer.PrepareRegistry(importerPlan,real,importer);
    Check(importerPlan.written.Count>0&&importerPlan.written.All(x=>InstallCore.DecodePath(x.value)==Path.Combine(real,importer.product,importer.apx)),"actual importer Include preflight passes without modifying registry");
   }
  }
  Console.WriteLine(passed+" checks passed; fixtures retained at "+root);
 }
}
