using System;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    static class Program
    {
        // 컴퓨터 전체에서 1개만 실행 (같은 영수증 중복 업로드 방지)
        private const string MutexName = @"Global\ReceiptTap.Agent.SingleInstance";

        [STAThread]
        static void Main()
        {
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
                    MessageBox.Show("영수증리뷰 프로그램이 이미 실행 중입니다.\n작업표시줄 오른쪽 아래의 초록색 N 아이콘을 눌러주세요.",
                        "영수증리뷰", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }

                try
                {
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
