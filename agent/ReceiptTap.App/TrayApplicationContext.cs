using System;
using System.Drawing;
using System.Windows.Forms;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    /// <summary>
    /// 트레이 앱 컨텍스트
    /// </summary>
    public class TrayApplicationContext : ApplicationContext
    {
        private NotifyIcon _trayIcon;
        private AgentConfig _config;
        private ContextMenuStrip _menu;
        private CaptureService _captureService;

        public TrayApplicationContext()
        {
            _config = AgentConfig.Load();
            InitializeTrayIcon();
            StartCaptureService();
        }

        private void StartCaptureService()
        {
            if (!_config.Activated) return;

            _captureService = new CaptureService(_config);
            _captureService.StatusChanged += (s, status) => UpdateStatus(status);
            _captureService.LogMessage += (s, msg) => System.Diagnostics.Debug.WriteLine(msg);
            _captureService.Start();
        }

        private void InitializeTrayIcon()
        {
            _menu = new ContextMenuStrip();
            _menu.Items.Add("상태: 대기 중", null, null);
            _menu.Items.Add("-");
            _menu.Items.Add("설정", null, OnSettings);
            _menu.Items.Add("로그 보기", null, OnViewLogs);
            _menu.Items.Add("-");
            _menu.Items.Add("종료", null, OnExit);

            _trayIcon = new NotifyIcon
            {
                Icon = GetStatusIcon(AgentStatus.Idle),
                Text = "ReceiptTap - 영수증 리뷰",
                ContextMenuStrip = _menu,
                Visible = true
            };

            _trayIcon.DoubleClick += OnSettings;

            // 활성화 안 됐으면 설정 창 열기
            if (!_config.Activated)
            {
                ShowActivationDialog();
            }
        }

        private Icon GetStatusIcon(AgentStatus status)
        {
            // TODO: 실제 아이콘 파일로 교체
            // 초록: 정상, 노랑: 서버 연결 안 됨, 빨강: 캡처 안 됨
            return SystemIcons.Application;
        }

        private void ShowActivationDialog()
        {
            using (var dialog = new ActivationForm())
            {
                if (dialog.ShowDialog() == DialogResult.OK)
                {
                    _config = AgentConfig.Load();
                    UpdateStatus(AgentStatus.Connected);
                }
            }
        }

        private void UpdateStatus(AgentStatus status)
        {
            _trayIcon.Icon = GetStatusIcon(status);
            _menu.Items[0].Text = $"상태: {GetStatusText(status)}";
        }

        private string GetStatusText(AgentStatus status)
        {
            switch (status)
            {
                case AgentStatus.Connected: return "연결됨 (정상)";
                case AgentStatus.Disconnected: return "서버 연결 안 됨";
                case AgentStatus.CaptureError: return "캡처 오류";
                default: return "대기 중";
            }
        }

        private void OnSettings(object sender, EventArgs e)
        {
            using (var dialog = new SettingsForm(_config))
            {
                if (dialog.ShowDialog() == DialogResult.OK)
                {
                    _config = AgentConfig.Load();
                }
            }
        }

        private void OnViewLogs(object sender, EventArgs e)
        {
            var logPath = AgentConfig.LogPath;
            if (System.IO.Directory.Exists(logPath))
            {
                System.Diagnostics.Process.Start("explorer.exe", logPath);
            }
            else
            {
                MessageBox.Show("로그 폴더가 없습니다.", "ReceiptTap", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        }

        private void OnExit(object sender, EventArgs e)
        {
            _trayIcon.Visible = false;
            Application.Exit();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _captureService?.Dispose();
                _trayIcon?.Dispose();
                _menu?.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    public enum AgentStatus
    {
        Idle,
        Connected,
        Disconnected,
        CaptureError
    }
}
