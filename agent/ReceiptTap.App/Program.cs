using System;
using System.IO;
using System.Windows.Forms;

namespace ReceiptTap.App
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                // 전역 예외 처리
                Application.ThreadException += (s, e) => LogError(e.Exception);
                AppDomain.CurrentDomain.UnhandledException += (s, e) => LogError(e.ExceptionObject as Exception);

                Application.Run(new TrayApplicationContext());
            }
            catch (Exception ex)
            {
                LogError(ex);
                MessageBox.Show($"프로그램 시작 오류:\n{ex.Message}\n\n자세한 내용은 error.txt를 확인하세요.",
                    "ReceiptTap 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        static void LogError(Exception ex)
        {
            try
            {
                var logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "error.txt");
                var msg = $"[{DateTime.Now}]\n{ex?.ToString() ?? "Unknown error"}\n\n";
                File.AppendAllText(logPath, msg);
            }
            catch { }
        }
    }
}
