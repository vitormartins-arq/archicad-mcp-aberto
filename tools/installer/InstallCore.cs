using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Web.Script.Serialization;

public sealed class PackageInfo {
 public string product, revision, payload_revision, mdid, apx, channel;
 public int archicad;
 public Dictionary<string,string> files;
}
public sealed class SavedPath { public string source, backup; public bool directory; }
public sealed class RegistryState { public string key, name, value; }
public sealed class InstallRecord {
 public string target, backupRoot, status, product;
 public List<SavedPath> paths=new List<SavedPath>();
 public List<RegistryState> registry=new List<RegistryState>();
 public List<RegistryState> written=new List<RegistryState>();
}
public static class InstallCore {
 public static readonly JavaScriptSerializer Json=new JavaScriptSerializer {MaxJsonLength=16000000};
 public static string DecodePath(string s) {
  if(s.StartsWith("lan.flat:///",StringComparison.OrdinalIgnoreCase)) return Uri.UnescapeDataString(s.Substring(12)).Replace('/','\\');
  if(s.StartsWith("file:///",StringComparison.OrdinalIgnoreCase)) return new Uri(s).LocalPath;
  return s;
 }
 public static string EncodePath(string p) {return "lan.flat:///"+Uri.EscapeDataString(p.Replace('\\','/')).Replace("%2F","/").Replace("%3A",":");}
 public static string Hash(string p) {using(var s=File.OpenRead(p)) using(var h=SHA256.Create()) return BitConverter.ToString(h.ComputeHash(s)).Replace("-","").ToLowerInvariant();}
 public static void NoLinks(string path) {
  for(string p=Path.GetFullPath(path);p!=null;p=Path.GetDirectoryName(p))
   if((File.Exists(p)||Directory.Exists(p))&&(File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0) throw new Exception("Pasta com redirecionamento não permitida: "+p);
 }
 public static string Inside(string root,string name) {
  if(String.IsNullOrEmpty(name)||name.IndexOf('\\')>=0||name.IndexOf(':')>=0||name.StartsWith("/")||name.Split('/').Any(x=>x=="."||x==".."||x==""||x.EndsWith(".")||x.EndsWith(" "))) throw new Exception("Caminho inválido no pacote: "+name);
  string full=Path.GetFullPath(Path.Combine(root,name.Replace('/',Path.DirectorySeparatorChar)));
  if(!full.StartsWith(Path.GetFullPath(root)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new Exception("Caminho fora do destino.");
  return full;
 }
 public static IEnumerable<string> Files(string root) {
  NoLinks(root);
  foreach(string f in Directory.GetFiles(root)) {NoLinks(f);yield return f;}
  foreach(string d in Directory.GetDirectories(root)) {
   if(Path.GetFileName(d).StartsWith("(")) continue;
   foreach(string f in Files(d)) yield return f;
  }
 }
 public static void Verify(string root,PackageInfo c) {
  foreach(var f in c.files) {
   string p=Inside(root,f.Key); NoLinks(p);
   if(!File.Exists(p)||Hash(p)!=f.Value) throw new Exception("Verificação falhou: "+f.Key);
  }
  if(Mdid.Read(Inside(root,c.apx))!=c.mdid) throw new Exception("Identidade MDID diferente do pacote.");
 }
 public static void Extract(Stream zip,string stage,PackageInfo c) {
  var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
  using(var z=new ZipArchive(zip,ZipArchiveMode.Read)) {
   foreach(var e in z.Entries) {
    if(e.FullName.EndsWith("/")) continue;
    string path=Inside(stage,e.FullName);
    if(!seen.Add(e.FullName)||!c.files.ContainsKey(e.FullName)) throw new Exception("Arquivo duplicado ou não inventariado.");
    Directory.CreateDirectory(Path.GetDirectoryName(path));
    using(var input=e.Open()) using(var output=new FileStream(path,FileMode.CreateNew)) input.CopyTo(output);
   }
  }
  if(seen.Count!=c.files.Count) throw new Exception("Pacote incompleto.");
  Verify(stage,c);
 }
 static bool Same(string a,string b) {return String.Equals(Path.GetFullPath(a).TrimEnd('\\'),Path.GetFullPath(b).TrimEnd('\\'),StringComparison.OrdinalIgnoreCase);}
 public static List<string> Duplicates(string extensions,string target,PackageInfo c) {
  var result=new List<string>();
  foreach(string f in Files(extensions).Where(x=>x.EndsWith(".apx",StringComparison.OrdinalIgnoreCase))) {
   if(f.StartsWith(target+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) continue;
   try {if(Mdid.Read(f)==c.mdid) result.Add(f);} catch(Exception ex) {
    // Unknown APXs belong to other products; known LAB names require inspection.
    string n=Path.GetFileName(f);
    if(n.StartsWith("LAB - ",StringComparison.OrdinalIgnoreCase)||n=="ImportadorOBJ.apx"||n.StartsWith("ArchicadMcp",StringComparison.OrdinalIgnoreCase)||n.StartsWith("Archicad MCP",StringComparison.OrdinalIgnoreCase)) throw new Exception("Não foi possível conferir a cópia antiga: "+f,ex);
   }
  }
  return result;
 }
 public static void Save(InstallRecord r) {
  string p=Path.Combine(r.backupRoot,"restauracao.json"),tmp=p+".tmp";
  File.WriteAllText(tmp,Json.Serialize(r));
  if(File.Exists(p)) File.Replace(tmp,p,null); else File.Move(tmp,p);
 }
 public static InstallRecord Prepare(string extensions,PackageInfo c) {
  if(c.product!="LAB - Complemento MCP"&&c.product!="LAB - Importador de Blocos e Texturas") throw new Exception("Produto não autorizado.");
  NoLinks(extensions);
  string target=Path.Combine(extensions,c.product);
  string priorBackups=Path.Combine(extensions,"(LAB - Backups)",c.product);NoLinks(priorBackups);
  if(Directory.Exists(priorBackups)) foreach(string dir in Directory.GetDirectories(priorBackups)) {
   string journal=Path.Combine(dir,"restauracao.json");NoLinks(journal);
   if(File.Exists(journal)) {
    var previous=Json.Deserialize<InstallRecord>(File.ReadAllText(journal));
    if(previous.status!="instalado"&&previous.status!="restaurado"&&previous.status!="revertido") throw new Exception("Há uma atualização incompleta. Confira seu estado antes de repetir: "+journal);
   }
  }
  if(Directory.Exists(target)) {
   var apxs=Files(target).Where(p=>p.EndsWith(".apx",StringComparison.OrdinalIgnoreCase)).ToList();
   if(apxs.Count!=1||Mdid.Read(apxs[0])!=c.mdid) throw new Exception("A pasta de destino contém outro produto ou arquivos desconhecidos: "+target);
  }
  var r=new InstallRecord{product=c.product,target=target,status="preparado",backupRoot=Path.Combine(extensions,"(LAB - Backups)",c.product,DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N"))};
  NoLinks(r.backupRoot);
  if(Directory.Exists(target)) r.paths.Add(new SavedPath{source=target,backup=Path.Combine(r.backupRoot,"anterior"),directory=true});
  foreach(string f in Duplicates(extensions,target,c)) r.paths.Add(new SavedPath{source=f,backup=Path.Combine(r.backupRoot,"copia-"+r.paths.Count+".apx"),directory=false});
  return r;
 }
 public static void Move(string from,string to,bool directory) {
  NoLinks(from);NoLinks(to);Directory.CreateDirectory(Path.GetDirectoryName(to));
  if(directory) Directory.Move(from,to); else File.Move(from,to);
 }
 public static void Apply(InstallRecord r,string stage,PackageInfo c,Action registryWrite,Action registryRollback) {
  Verify(stage,c);Directory.CreateDirectory(r.backupRoot);Save(r);
  bool placed=false;
  try {
   foreach(var p in r.paths) {Move(p.source,p.backup,p.directory);Save(r);}
   Directory.Move(stage,r.target);placed=true;
   Verify(r.target,c);
   registryWrite();
   r.status="instalado";Save(r);
  } catch(Exception original) {
   Exception registryFailure=null;
   try {registryRollback();} catch(Exception ex) {registryFailure=ex;}
   if(placed&&Directory.Exists(r.target)) Move(r.target,Path.Combine(r.backupRoot,"instalacao-rejeitada"),true);
   foreach(var p in Enumerable.Reverse(r.paths)) if(p.directory?Directory.Exists(p.backup):File.Exists(p.backup)) Move(p.backup,p.source,p.directory);
   r.status=registryFailure==null?"revertido":"arquivos revertidos; conferir registro";Save(r);
   if(registryFailure!=null) throw new Exception("Arquivos anteriores restaurados, mas houve falha ao restaurar o registro. Backup: "+r.backupRoot,registryFailure);
   throw new Exception("Atualização revertida; versão anterior preservada. "+original.Message,original);
  }
 }
 public static void Restore(InstallRecord r,Action registryRollback) {
  // Refuse malicious journals or destinations outside the native extension root.
  string extensions=Directory.GetParent(r.target).FullName;
  if(!Same(r.target,Path.Combine(extensions,r.product))||!r.backupRoot.StartsWith(Path.Combine(extensions,"(LAB - Backups)")+"\\",StringComparison.OrdinalIgnoreCase)) throw new Exception("Backup inválido.");
  foreach(var p in r.paths) {
   if(!p.source.StartsWith(extensions+"\\",StringComparison.OrdinalIgnoreCase)||!p.backup.StartsWith(r.backupRoot+"\\",StringComparison.OrdinalIgnoreCase)) throw new Exception("Origem de restauração inválida.");
   if(!(p.directory?Directory.Exists(p.backup):File.Exists(p.backup))) throw new Exception("Backup incompleto: "+p.backup);
   if(!Same(p.source,r.target)&&(File.Exists(p.source)||Directory.Exists(p.source))) throw new Exception("O caminho antigo já está ocupado: "+p.source);
  }
  if(Directory.Exists(r.target)) Move(r.target,Path.Combine(r.backupRoot,"versao-substituida-ao-restaurar"),true);
  foreach(var p in Enumerable.Reverse(r.paths)) Move(p.backup,p.source,p.directory);
  registryRollback();r.status="restaurado";Save(r);
 }
}
