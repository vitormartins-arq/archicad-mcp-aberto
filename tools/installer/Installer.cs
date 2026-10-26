using System;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Reflection;
using System.Collections.Generic;
using System.Windows.Forms;
using Microsoft.Win32;

public class Installer : Form {
 PackageInfo config; TextBox path; Button install,restore; Label info;
 string Extensions {
  get {
   string root=Path.GetFullPath(path.Text.Trim()); InstallCore.NoLinks(root);
   string exe=Path.Combine(root,"Archicad.exe");
   if(!File.Exists(exe)||FileVersionInfo.GetVersionInfo(exe).FileMajorPart!=config.archicad) throw new Exception("Escolha a pasta do Archicad "+config.archicad+" (versão incompatível ou não encontrada).");
   string[] options={Path.Combine(root,"Extensões"),Path.Combine(root,"Add-Ons")};
   var found=options.Where(Directory.Exists).ToArray();
   if(found.Length!=1) throw new Exception("Não foi possível identificar a pasta nativa de extensões.");
   return found[0];
  }
 }
 List<string> RegistryKeys() {
  var result=new List<string>();
  using(var root=Registry.CurrentUser.OpenSubKey("Software\\GRAPHISOFT\\Archicad")) {
   if(root!=null) foreach(string name in root.GetSubKeyNames())
    if(name.StartsWith("Archicad "+config.archicad+".",StringComparison.OrdinalIgnoreCase)) result.Add("Software\\GRAPHISOFT\\Archicad\\"+name+"\\Add-On Manager");
  }
  if(result.Count==0) throw new Exception("O Archicad desta versão ainda não foi aberto nesta conta do Windows. Abra e feche o programa uma vez antes de instalar.");
  if(result.Count>1) throw new Exception("Há mais de uma configuração do Archicad desta versão. Identifique a instalação de destino antes de migrar os caminhos do Gestor de Extensões.");
  return result;
 }
 void PrepareRegistry(InstallRecord record,string extensions) {
  foreach(string baseKey in RegistryKeys()) {
   using(var manager=Registry.CurrentUser.OpenSubKey(baseKey)) {
    if(manager!=null) {
     string actual=InstallCore.DecodePath(Convert.ToString(manager.GetValue("Actual Path","")));
     if(Directory.Exists(actual)&&!String.Equals(Path.GetFullPath(actual).TrimEnd('\\'),Path.GetFullPath(extensions).TrimEnd('\\'),StringComparison.OrdinalIgnoreCase))
      foreach(string f in InstallCore.Files(actual).Where(x=>x.EndsWith(".apx",StringComparison.OrdinalIgnoreCase)))
       if(Mdid.Read(f)==config.mdid) throw new Exception("Há uma cópia na pasta personalizada do Gestor de Extensões. Remova-a do carregamento antes de instalar: "+f);
    }
   }
   string key=baseKey+"\\Include";
   using(var include=Registry.CurrentUser.OpenSubKey(key)) {
    if(include!=null) foreach(string name in include.GetValueNames()) {
     string value=include.GetValue(name) as string;if(value==null) continue;
     string p=InstallCore.DecodePath(value);
     if(File.Exists(p)&&p.EndsWith(".apx",StringComparison.OrdinalIgnoreCase)&&Mdid.Read(p)==config.mdid)
      record.registry.Add(new RegistryState{key=key,name=name,value=value});
    }
   }
   // Reuse a matching existing slot, or reserve an unused Include slot.
   var old=record.registry.FirstOrDefault(x=>x.key==key);
   string slot=old==null?null:old.name;
   if(slot==null) using(var include=Registry.CurrentUser.OpenSubKey(key)) {
    int i=1;while(include!=null&&include.GetValue("#"+i+".")!=null)i++;slot="#"+i+".";
   }
   string uri=InstallCore.EncodePath(Path.Combine(record.target,config.apx));
   record.written.Add(new RegistryState{key=key,name=slot,value=uri});
  }
 }
 static void WriteRegistry(InstallRecord r) {
  foreach(var p in r.registry) using(var k=Registry.CurrentUser.CreateSubKey(p.key)) k.DeleteValue(p.name,false);
  foreach(var p in r.written) using(var k=Registry.CurrentUser.CreateSubKey(p.key)) k.SetValue(p.name,p.value,RegistryValueKind.String);
 }
 static void RestoreRegistry(InstallRecord r) {
  foreach(var p in r.written) using(var k=Registry.CurrentUser.CreateSubKey(p.key)) k.DeleteValue(p.name,false);
  foreach(var p in r.registry) using(var k=Registry.CurrentUser.CreateSubKey(p.key)) k.SetValue(p.name,p.value,RegistryValueKind.String);
 }
 static void RequireClosedArchicad() {
  if(Process.GetProcessesByName("Archicad").Length>0) throw new Exception("Salve seu trabalho e feche o Archicad antes de instalar ou restaurar. O instalador não fecha o programa automaticamente.");
 }
 void Run(bool previous) {
  install.Enabled=restore.Enabled=false;
  try {
   RequireClosedArchicad();string ext=Extensions;
   using(var mutex=new System.Threading.Mutex(false,"Global\\LAB-Archicad-"+config.archicad+"-"+config.mdid.Replace("-",""))) {
    if(!mutex.WaitOne(0)) throw new Exception("Outro instalador deste add-on está em execução.");
    try {
     if(previous) {
      string backups=Path.Combine(ext,"(LAB - Backups)",config.product);InstallCore.NoLinks(backups);
      if(!Directory.Exists(backups)) throw new Exception("Nenhuma instalação anterior para restaurar.");
      var records=Directory.GetDirectories(backups).Select(d=>Path.Combine(d,"restauracao.json")).Where(File.Exists).OrderByDescending(x=>x).ToList();
      InstallRecord r=null;
      foreach(string f in records) {var item=InstallCore.Json.Deserialize<InstallRecord>(File.ReadAllText(f));if(item.status=="instalado"){r=item;break;}}
      if(r==null) throw new Exception("Nenhum backup pendente de restauração.");
      if(!String.Equals(r.target,Path.Combine(ext,config.product),StringComparison.OrdinalIgnoreCase)) throw new Exception("O backup pertence a outra instalação.");
      InstallCore.Restore(r,()=>RestoreRegistry(r));
      MessageBox.Show("Versão anterior restaurada. A versão substituída foi preservada no backup.",Text);
     } else {
      var r=InstallCore.Prepare(ext,config);PrepareRegistry(r,ext);
      string stage=Path.Combine(ext,"(LAB - Preparação "+Guid.NewGuid().ToString("N")+")");Directory.CreateDirectory(stage);
      using(var zip=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")) InstallCore.Extract(zip,stage,config);
      RequireClosedArchicad();
      InstallCore.Apply(r,stage,config,()=>WriteRegistry(r),()=>RestoreRegistry(r));
      MessageBox.Show("Instalado em:\n"+r.target+"\n\nAbra o Archicad para carregar o add-on.\nBackup: "+r.backupRoot,Text);
     }
    } finally {mutex.ReleaseMutex();}
   }
  } catch(Exception ex) {MessageBox.Show(ex.Message,Text,MessageBoxButtons.OK,MessageBoxIcon.Warning);}
  finally {install.Enabled=restore.Enabled=true;}
 }
 public Installer(PackageInfo c) {
  config=c;Text=c.product+" — instalador "+c.revision;Width=670;Height=330;FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;
  info=new Label{Left=20,Top=20,Width=610,Height=95,Text="Instalar ou atualizar "+c.product+"\nArchicad "+c.archicad+" | conteúdo "+c.payload_revision+" | "+c.channel+"\n\nFeche o Archicad antes de continuar. A versão anterior será preservada para restauração."};Controls.Add(info);
  path=new TextBox{Left=20,Top=125,Width=520,Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),"Graphisoft","Archicad "+c.archicad)};Controls.Add(path);
  var browse=new Button{Left=550,Top=123,Width=80,Text="Escolher"};browse.Click+=(s,e)=>{using(var d=new FolderBrowserDialog{SelectedPath=path.Text,Description="Pasta do Archicad "+c.archicad})if(d.ShowDialog()==DialogResult.OK)path.Text=d.SelectedPath;};Controls.Add(browse);
  install=new Button{Left=20,Top=180,Width=200,Height=35,Text="Instalar / Atualizar"};install.Click+=(s,e)=>Run(false);Controls.Add(install);
  restore=new Button{Left=235,Top=180,Width=200,Height=35,Text="Restaurar versão anterior"};restore.Click+=(s,e)=>Run(true);Controls.Add(restore);
  var close=new Button{Left=450,Top=180,Width=180,Height=35,Text="Fechar"};close.Click+=(s,e)=>Close();Controls.Add(close);
  Controls.Add(new Label{Left=20,Top=235,Width=610,Height=45,Text="Destino: Extensões\\"+c.product+". O instalador trata somente este add-on; Tapir, D5 e demais extensões são preservados."});
 }
 [STAThread] public static void Main() {
  Application.EnableVisualStyles();
  using(var s=Assembly.GetExecutingAssembly().GetManifestResourceStream("package.json")) using(var reader=new StreamReader(s)) {
   var c=InstallCore.Json.Deserialize<PackageInfo>(reader.ReadToEnd());Application.Run(new Installer(c));
  }
 }
}
