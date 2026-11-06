using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Windows.Forms;

internal static class Launcher {
    const string Hash = "__PAYLOAD_HASH__";
    static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
    static bool Valid(string dir) {
        using (var sha = SHA256.Create())
        using (var reader = new StreamReader(Assembly.GetExecutingAssembly().GetManifestResourceStream("index"))) {
            string line;
            while ((line = reader.ReadLine()) != null) {
                string path = Path.Combine(dir, line.Substring(65));
                if (!File.Exists(path)) return false;
                using (var f = File.OpenRead(path))
                    if (Hex(sha.ComputeHash(f)) != line.Substring(0,64)) return false;
            }
        }
        return true;
    }
    static void Extract(string dir) {
        using (var input = File.OpenRead(Application.ExecutablePath)) {
            input.Seek(-8, SeekOrigin.End);
            long offset = new BinaryReader(input).ReadInt64();
            if (offset <= 0 || offset >= input.Length-8) throw new IOException("Invalid archive offset.");
            input.Position = offset;
            var psi = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory,"tar.exe"), "-xf -");
            psi.WorkingDirectory = dir;
            psi.UseShellExecute = false; psi.RedirectStandardInput = true; psi.CreateNoWindow = true;
            using (var tar = Process.Start(psi))
            using (var sha = SHA256.Create()) {
                long left = input.Length-offset-8;
                byte[] block = new byte[1024*1024];
                using (var pipe = tar.StandardInput.BaseStream) {
                    while (left > 0) {
                        int n = input.Read(block,0,(int)Math.Min(left,block.Length));
                        if (n == 0) throw new EndOfStreamException();
                        sha.TransformBlock(block,0,n,block,0);
                        pipe.Write(block,0,n); left -= n;
                    }
                }
                sha.TransformFinalBlock(new byte[0],0,0);
                tar.WaitForExit();
                if (tar.ExitCode != 0 || Hex(sha.Hash) != Hash) throw new IOException("Offline archive verification failed.");
            }
        }
    }
    static void Run(bool verify) {
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "RuZhOffline",Hash.Substring(0,20));
        Directory.CreateDirectory(root);
        string pointer = Path.Combine(root,"active.txt"), dir;
        using (var mutex = new Mutex(false, "Local\\RuZhOffline-"+Hash)) {
            try { mutex.WaitOne(); } catch (AbandonedMutexException) { }
            try {
                string id = File.Exists(pointer) ? File.ReadAllText(pointer) : "";
                dir = System.Text.RegularExpressions.Regex.IsMatch(id, "^[0-9a-f]{12}$")
                    ? Path.Combine(root,id) : "";
                if (dir.Length == 0 || !Valid(dir)) {
                    string name = Guid.NewGuid().ToString("N").Substring(0,12);
                    dir = Path.Combine(root,name);
                    Directory.CreateDirectory(dir);
                    Extract(dir);
                    if (!Valid(dir)) throw new IOException("Extracted file verification failed.");
                    string next = Path.Combine(root,name+".txt");
                    File.WriteAllText(next,name);
                    if (File.Exists(pointer)) File.Replace(next,pointer,null); else File.Move(next,pointer);
                }
            } finally { mutex.ReleaseMutex(); }
        }
        if (verify) return;
        var start = new ProcessStartInfo(Path.Combine(dir,"app","ru-zh-subtitles.exe"));
        start.WorkingDirectory = Path.Combine(dir,"app");
        start.UseShellExecute = false;
        start.EnvironmentVariables["LOCALAPPDATA"] = Path.Combine(dir,"profile");
        start.EnvironmentVariables["HF_HOME"] = Path.Combine(dir,"profile","hf");
        start.EnvironmentVariables["HF_MODULES_CACHE"] = Path.Combine(dir,"profile","hf","modules");
        start.EnvironmentVariables["HF_HUB_CACHE"] = Path.Combine(dir,"profile","ru-zh-live-subtitles","models","hf-home","hub");
        start.EnvironmentVariables["HF_HUB_OFFLINE"] = "1"; start.EnvironmentVariables["TRANSFORMERS_OFFLINE"] = "1";
        Process.Start(start);
    }
    [STAThread] static int Main(string[] args) {
        bool verify = args.Length == 1 && args[0] == "--verify-only";
        Exception failure = null;
        if (verify) { try { Run(true); } catch(Exception e) { failure=e; } }
        else using (var form = new Form()) {
            form.Text="Russian–Chinese Live Subtitles"; form.Width=460; form.Height=110;
            form.StartPosition=FormStartPosition.CenterScreen; form.ControlBox=false;
            form.Controls.Add(new Label { Dock=DockStyle.Fill, TextAlign=System.Drawing.ContentAlignment.MiddleCenter,
                Text="Checking offline files. First launch prepares the models on this PC." });
            form.Shown += delegate {
                var thread=new Thread(delegate() {
                    try { Run(false); } catch(Exception e) { failure=e; }
                    form.BeginInvoke(new Action(form.Close));
                }); thread.Start();
            };
            Application.Run(form);
        }
        if(failure!=null) {
            if(!verify) MessageBox.Show(failure.Message,"Offline subtitle startup");
            Console.Error.WriteLine(failure); return 1;
        }
        return 0;
    }
}

