using System;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    static class Program
    {
        // 컴퓨터 전체에서 1개만 실행 (같은 영수증 중복 업로드 방지)
        private const string MutexName = @"Global\ReceiptTap.Agent.SingleInstance";

        private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string AutoStartArg = "--autostart";

        [STAThread]
        static void Main(string[] args)
        {
            bool autoStart = Array.Exists(args ?? new string[0],
                a => string.Equals(a, AutoStartArg, StringComparison.OrdinalIgnoreCase));
            using (var mutex = new Mutex(false, MutexName))
            {
                bool owned;
                try
                {
                    // 업데이트 직후 재시작처럼 이전 프로그램이 막 종료 중인 경우를 위해 잠시 대기
                    owned = mutex.WaitOne(TimeSpan.FromSeconds(10));
                }
                catch (AbandonedMutexException)
                {
                    owned = true;
                }

                if (!owned)
                {
                    if (autoStart) return;   // PC 켤 때 자동 실행인데 이미 켜져 있으면 조용히 끝
                    MessageBox.Show("영수증리뷰 프로그램이 이미 실행 중입니다.\n작업표시줄 오른쪽 아래의 초록색 N 아이콘을 눌러주세요.",
                        "영수증리뷰", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }

                try
                {
                    EnsureAutoStart();
                    Run();
                }
                finally
                {
                    try { mutex.ReleaseMutex(); } catch { }
                }
            }
        }

        static void Run()
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                Application.ThreadException += (s, e) => LogError(e.Exception);
                AppDomain.CurrentDomain.UnhandledException += (s, e) => LogError(e.ExceptionObject as Exception);

                Application.Run(new TrayApplicationContext());
            }
            catch (Exception ex)
            {
                LogError(ex);
                MessageBox.Show($"프로그램 시작 오류:\n{ex.Message}\n\n로그 폴더의 error.txt 를 담당자에게 보내주세요.",
                    "영수증리뷰 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// PC 켤 때 자동 실행 등록 — 관리자 권한 없이 '현재 사용자' 시작 프로그램에 등록.
        /// 처음 한 번 실행만 하면 됨 (설치 파일·install.bat 이 이미 컴퓨터 전체로 등록했으면 중복 등록 안 함).
        /// 프로그램 위치가 바뀌면(다른 폴더에서 실행) 새 위치로 고침.
        /// </summary>
        static void EnsureAutoStart()
        {
            try
            {
                string exe = Application.ExecutablePath;
                string want = "\"" + exe + "\" " + AutoStartArg;
                string machine = null;
                using (var lm = Registry.LocalMachine.OpenSubKey(RunKey))
                    machine = lm?.GetValue("ReceiptTap") as string;
                using (var cu = Registry.CurrentUser.CreateSubKey(RunKey))
                {
                    if (cu == null) return;
                    if (machine != null && machine.IndexOf(exe, StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        if (cu.GetValue("ReceiptTap") != null) cu.DeleteValue("ReceiptTap", false);   // 컴퓨터 전체 등록으로 충분
                        return;
                    }
                    if (!string.Equals(cu.GetValue("ReceiptTap") as string, want, StringComparison.OrdinalIgnoreCase))
                        cu.SetValue("ReceiptTap", want);
                }
            }
            catch (Exception ex)
            {
                LogError(ex);
            }
        }

        static void LogError(Exception ex)
        {
            try
            {
                Directory.CreateDirectory(AgentConfig.LogPath);
                var logPath = Path.Combine(AgentConfig.LogPath, "error.txt");
                File.AppendAllText(logPath, $"[{DateTime.Now}]\r\n{ex?.ToString() ?? "Unknown error"}\r\n\r\n");
            }
            catch { }
        }
    }
}
