using System;
using System.Threading;
using System.Windows.Forms;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    /// <summary>
    /// 트레이 앱 컨텍스트 (작업표시줄 N 아이콘)
    /// </summary>
    public class TrayApplicationContext : ApplicationContext
    {
        private NotifyIcon _trayIcon;
        private AgentConfig _config;
        private ContextMenuStrip _menu;
        private ToolStripItem _statusItem;
        private CaptureService _captureService;
        private SettingsForm _settingsForm;
        private readonly SynchronizationContext _ui;

        public TrayApplicationContext()
        {
            // SPMC 이벤트·타이머 콜백을 UI 스레드로 넘기기 위해 필요
            if (!(SynchronizationContext.Current is WindowsFormsSynchronizationContext))
                SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
            _ui = SynchronizationContext.Current;

            _config = AgentConfig.Load();
            InitializeTrayIcon();

            if (!string.IsNullOrEmpty(_config.AuthToken))
            {
                _config.Activated = true;
                StartCaptureService();
            }
            else
            {
                ShowLoginDialog();
            }
        }

        private void StartCaptureService()
        {
            if (!_config.Activated || _captureService != null) return;

            _captureService = new CaptureService(_config);
            _captureService.StatusChanged += (s, status) => OnUi(() => UpdateStatus(status));
            _captureService.PortDetected += (s, port) => OnUi(() =>
                _trayIcon.ShowBalloonTip(4000, "프린터 자동 연결됨",
                    $"{SettingsForm.DisplayPort(port)}에서 영수증을 찾았습니다.\n이제 영수증이 자동으로 수집됩니다.", ToolTipIcon.Info));
            _captureService.ReceiptProcessed += (s, r) => OnUi(() =>
            {
                if (_settingsForm == null)
                    _trayIcon.ShowBalloonTip(2000, "영수증 읽음", $"{r.CapturedAt:HH:mm:ss} {r.Port} · {r.UploadState}", ToolTipIcon.None);
            });
            _captureService.LoginRequired += (s, e) => OnUi(() =>
                _trayIcon.ShowBalloonTip(5000, "다시 로그인해 주세요",
                    "로그인이 만료되어 영수증을 서버로 보내지 못하고 있습니다.\n이 알림을 눌러 다시 로그인해 주세요.", ToolTipIcon.Warning));
            _captureService.Start();
            UpdateStatus(_captureService.CurrentStatus);
        }

        private void InitializeTrayIcon()
        {
            _menu = new ContextMenuStrip();
            _statusItem = _menu.Items.Add("상태: 대기 중", null, OnSettings);
            _menu.Items.Add("-");
            _menu.Items.Add("상태 및 설정 열기", null, OnSettings);
            _menu.Items.Add("로그 보기", null, OnViewLogs);
            _menu.Items.Add("-");
            _menu.Items.Add("종료", null, OnExit);

            _trayIcon = new NotifyIcon
            {
                Icon = AppIcons.ForStatus(AgentStatus.Idle),
                Text = "영수증리뷰",
                ContextMenuStrip = _menu,
                Visible = true
            };

            _trayIcon.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) OnSettings(s, e); };
            _trayIcon.BalloonTipClicked += OnSettings;
        }

        private void ShowLoginDialog()
        {
            using (var dialog = new LoginForm())
            {
                if (dialog.ShowDialog() == DialogResult.OK)
                {
                    _config = AgentConfig.Load();
                    _config.Activated = true;
                    _config.Save();
                    // 이미 실행 중이면 (로그인 만료 후 재로그인) 새 토큰으로 다시 시작
                    if (_captureService != null)
                    {
                        _captureService.Dispose();
                        _captureService = null;
                    }
                    StartCaptureService();

                    _trayIcon.ShowBalloonTip(
                        4000,
                        "영수증리뷰",
                        $"{_config.StoreName}에 연결되었습니다!\n포스에서 영수증을 1장 출력하면 프린터가 자동 연결됩니다.",
                        ToolTipIcon.Info
                    );
                }
            }
        }

        private void OnUi(Action a)
        {
            if (_ui != null) _ui.Post(_ => { try { a(); } catch { } }, null);
            else a();
        }

        private void UpdateStatus(AgentStatus status)
        {
            _trayIcon.Icon = AppIcons.ForStatus(status);
            var text = $"상태: {GetStatusText(status)}";
            _statusItem.Text = text;

            var tip = "영수증리뷰 - " + GetStatusText(status);
            if (!string.IsNullOrEmpty(_captureService?.ReceiptPort)) tip += $" ({_captureService.ReceiptPort})";
            _trayIcon.Text = tip.Length > 63 ? tip.Substring(0, 63) : tip;
        }

        private string GetStatusText(AgentStatus status)
        {
            switch (status)
            {
                case AgentStatus.Connected: return "정상 작동 중";
                case AgentStatus.Searching: return "프린터 찾는 중";
                case AgentStatus.Disconnected: return "서버 연결 안 됨";
                case AgentStatus.CaptureError: return "영수증 읽기 오류";
                case AgentStatus.LoginRequired: return "다시 로그인 필요";
                default: return "대기 중";
            }
        }

        private void OnSettings(object sender, EventArgs e)
        {
            if (string.IsNullOrEmpty(_config.AuthToken) || _captureService?.CurrentStatus == AgentStatus.LoginRequired)
            {
                ShowLoginDialog();
                return;
            }

            if (_settingsForm != null && !_settingsForm.IsDisposed)
            {
                _settingsForm.WindowState = FormWindowState.Normal;
                _settingsForm.Activate();
                return;
            }

            _settingsForm = new SettingsForm(_config, _captureService);
            _settingsForm.FormClosed += (s, a) => _settingsForm = null;
            _settingsForm.Show();
            _settingsForm.Activate();
        }

        private void OnViewLogs(object sender, EventArgs e)
        {
            var logPath = AgentConfig.LogPath;
            System.IO.Directory.CreateDirectory(logPath);
            System.Diagnostics.Process.Start("explorer.exe", logPath);
        }

        private void OnExit(object sender, EventArgs e)
        {
            _trayIcon.Visible = false;
            _captureService?.Dispose();
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
        Searching,
        Disconnected,
        CaptureError,
        LoginRequired
    }
}
