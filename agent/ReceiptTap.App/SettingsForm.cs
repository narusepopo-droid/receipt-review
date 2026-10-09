using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO.Ports;
using System.Linq;
using System.Windows.Forms;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    /// <summary>
    /// 상태판 + 설정 창
    /// 왼쪽: 현재 상태(프린터 포트, 서버 연결, 오늘 읽은 영수증 등), 프린터 연결 설정
    /// 오른쪽: 최근 읽어온 영수증 내용
    /// </summary>
    public class SettingsForm : Form
    {
        private enum WaitMode { None, AutoConnect, Test }

        private const int WAIT_SECONDS = 90;

        private readonly AgentConfig _config;
        private readonly CaptureService _service;

        private Panel _statusDot;
        private Label _statusTitle, _statusDetail;
        private Label _storeVal, _portVal, _watchVal, _serverVal, _todayVal, _queueVal, _versionVal;
        private RadioButton _autoRadio, _manualRadio;
        private ComboBox _portCombo;
        private Button _applyBtn, _autoConnectBtn, _testBtn;
        private Label _waitLbl;
        private Label _receiptHeader, _uploadLbl;
        private TextBox _receiptBox;
        private Timer _uiTimer;

        private WaitMode _wait = WaitMode.None;
        private DateTime _waitUntil;
        private CapturedReceipt _shownReceipt;

        private static readonly Font UiFont = new Font("맑은 고딕", 9.5f);
        private static readonly Font BoldFont = new Font("맑은 고딕", 9.5f, FontStyle.Bold);

        public SettingsForm(AgentConfig config, CaptureService service)
        {
            _config = config;
            _service = service;
            InitializeComponents();
            LoadPorts();
            LoadConfig();

            if (_service != null)
            {
                _service.ReceiptProcessed += OnReceiptProcessed;
                _service.StatusChanged += OnStatusChanged;
            }

            _uiTimer = new Timer { Interval = 1000 };
            _uiTimer.Tick += (s, e) => RefreshAll();
            _uiTimer.Start();
            RefreshAll();
        }

        // ───────────────────────── 화면 구성 ─────────────────────────

        private void InitializeComponents()
        {
            Text = "영수증리뷰 - 상태 및 설정";
            Icon = AppIcons.App;
            Font = UiFont;
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(860, 600);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            BackColor = Color.White;

            // ── 상단 상태 카드 ──
            var statusCard = new Panel
            {
                Location = new Point(16, 16),
                Size = new Size(420, 84),
                BackColor = Color.FromArgb(246, 248, 250)
            };
            Controls.Add(statusCard);

            _statusDot = new Panel { Location = new Point(16, 18), Size = new Size(22, 22) };
            _statusDot.Paint += (s, e) =>
            {
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using (var b = new SolidBrush(AppIcons.StatusColor(CurrentStatus)))
                    e.Graphics.FillEllipse(b, 1, 1, 19, 19);
            };
            statusCard.Controls.Add(_statusDot);

            _statusTitle = new Label
            {
                Location = new Point(46, 14),
                Size = new Size(360, 28),
                Font = new Font("맑은 고딕", 14f, FontStyle.Bold)
            };
            statusCard.Controls.Add(_statusTitle);

            _statusDetail = new Label
            {
                Location = new Point(48, 46),
                Size = new Size(360, 34),
                ForeColor = Color.FromArgb(90, 90, 90)
            };
            statusCard.Controls.Add(_statusDetail);

            // ── 정보 표 ──
            int y = 116;
            _storeVal = AddInfoRow("매장", ref y);
            _portVal = AddInfoRow("프린터 포트", ref y);
            _watchVal = AddInfoRow("감시 중인 포트", ref y);
            _serverVal = AddInfoRow("서버 연결", ref y);
            _todayVal = AddInfoRow("오늘 읽은 영수증", ref y);
            _queueVal = AddInfoRow("전송 대기", ref y);
            _versionVal = AddInfoRow("프로그램 버전", ref y);

            // ── 프린터 연결 설정 ──
            var group = new GroupBox
            {
                Text = "프린터 연결",
                Location = new Point(16, y + 8),
                Size = new Size(420, 210),
                Font = BoldFont
            };
            Controls.Add(group);

            _autoRadio = new RadioButton
            {
                Text = "자동 (권장) - 영수증이 나오는 포트를 알아서 찾음",
                Location = new Point(14, 26),
                AutoSize = true,
                Font = UiFont
            };
            group.Controls.Add(_autoRadio);

            _manualRadio = new RadioButton
            {
                Text = "직접 선택:",
                Location = new Point(14, 56),
                AutoSize = true,
                Font = UiFont
            };
            group.Controls.Add(_manualRadio);

            _portCombo = new ComboBox
            {
                Location = new Point(110, 54),
                Size = new Size(220, 25),
                DropDownStyle = ComboBoxStyle.DropDownList,
                Font = UiFont
            };
            group.Controls.Add(_portCombo);

            _applyBtn = new Button
            {
                Text = "적용",
                Location = new Point(338, 53),
                Size = new Size(66, 27),
                Font = UiFont
            };
            _applyBtn.Click += OnApplyManual;
            group.Controls.Add(_applyBtn);

            _autoRadio.CheckedChanged += (s, e) => UpdateManualEnabled();
            _manualRadio.CheckedChanged += (s, e) => UpdateManualEnabled();

            _autoConnectBtn = new Button
            {
                Text = "자동 연결\r\n(프린터 찾기)",
                Location = new Point(14, 94),
                Size = new Size(190, 54),
                BackColor = AppIcons.Brand,
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = BoldFont
            };
            _autoConnectBtn.FlatAppearance.BorderSize = 0;
            _autoConnectBtn.Click += OnAutoConnect;
            group.Controls.Add(_autoConnectBtn);

            _testBtn = new Button
            {
                Text = "테스트 확인\r\n(영수증 읽기 확인)",
                Location = new Point(214, 94),
                Size = new Size(190, 54),
                FlatStyle = FlatStyle.Flat,
                Font = BoldFont
            };
            _testBtn.Click += OnTest;
            group.Controls.Add(_testBtn);

            _waitLbl = new Label
            {
                Location = new Point(14, 154),
                Size = new Size(392, 48),
                Font = UiFont
            };
            group.Controls.Add(_waitLbl);

            // ── 오른쪽: 최근 영수증 ──
            var rTitle = new Label
            {
                Text = "최근 읽어온 영수증",
                Location = new Point(456, 16),
                AutoSize = true,
                Font = new Font("맑은 고딕", 11f, FontStyle.Bold)
            };
            Controls.Add(rTitle);

            _receiptHeader = new Label
            {
                Location = new Point(456, 42),
                Size = new Size(388, 20),
                ForeColor = Color.FromArgb(90, 90, 90)
            };
            Controls.Add(_receiptHeader);

            _receiptBox = new TextBox
            {
                Location = new Point(456, 66),
                Size = new Size(388, 440),
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                WordWrap = false,
                BackColor = Color.FromArgb(255, 254, 250),
                Font = new Font("GulimChe", 9.5f),
                BorderStyle = BorderStyle.FixedSingle
            };
            Controls.Add(_receiptBox);

            _uploadLbl = new Label
            {
                Location = new Point(456, 512),
                Size = new Size(388, 22),
                Font = BoldFont
            };
            Controls.Add(_uploadLbl);

            // ── 아래 버튼 ──
            var logBtn = new Button
            {
                Text = "로그 보기",
                Location = new Point(456, 548),
                Size = new Size(110, 34)
            };
            logBtn.Click += (s, e) => OpenLogs();
            Controls.Add(logBtn);

            var closeBtn = new Button
            {
                Text = "닫기",
                Location = new Point(734, 548),
                Size = new Size(110, 34)
            };
            closeBtn.Click += (s, e) => Close();
            Controls.Add(closeBtn);
            CancelButton = closeBtn;
        }

        private Label AddInfoRow(string name, ref int y)
        {
            Controls.Add(new Label
            {
                Text = name,
                Location = new Point(20, y),
                Size = new Size(120, 22),
                ForeColor = Color.FromArgb(110, 110, 110)
            });
            var val = new Label
            {
                Location = new Point(140, y),
                Size = new Size(296, 22),
                Font = BoldFont,
                AutoEllipsis = true
            };
            Controls.Add(val);
            y += 26;
            return val;
        }

        // ───────────────────────── 데이터 ─────────────────────────

        private AgentStatus CurrentStatus => _service?.CurrentStatus ?? AgentStatus.Idle;

        private void LoadPorts()
        {
            _portCombo.Items.Clear();
            try
            {
                foreach (var p in SpmcHost.GetPorts().Where(p => p.Present))
                    _portCombo.Items.Add(p);
            }
            catch
            {
                // SPMC 없으면 윈도우 포트 목록이라도 표시
                foreach (var name in SafePortNames())
                    _portCombo.Items.Add(new SpmcPortInfo { Name = name, Port = name, Present = true });
            }
            // 윈도우에 등록된 프린터 (네트워크·와이파이 프린터 등)
            try
            {
                foreach (var pr in SpoolerCapture.ListPrinters())
                    _portCombo.Items.Add(new SpmcPortInfo { Name = $"[프린터] {pr.Name}", Port = SpoolerCapture.SourcePrefix + pr.Name, Present = true });
            }
            catch { }
        }

        private static string[] SafePortNames()
        {
            try { return SerialPort.GetPortNames(); } catch { return new string[0]; }
        }

        private void LoadConfig()
        {
            _autoRadio.Checked = !_config.PortLocked;
            _manualRadio.Checked = _config.PortLocked;

            var want = _config.PortLocked ? _config.ComPort : (_service?.ReceiptPort ?? _config.DetectedPort);
            for (int i = 0; i < _portCombo.Items.Count; i++)
            {
                if (((SpmcPortInfo)_portCombo.Items[i]).Key.Equals(want ?? "", StringComparison.OrdinalIgnoreCase))
                {
                    _portCombo.SelectedIndex = i;
                    break;
                }
            }
            if (_portCombo.SelectedIndex < 0 && _portCombo.Items.Count > 0)
                _portCombo.SelectedIndex = 0;

            UpdateManualEnabled();
            if (_service?.LastReceipt != null) ShowReceipt(_service.LastReceipt, false);
            else
            {
                _receiptHeader.Text = "아직 읽어온 영수증이 없습니다";
                _receiptBox.Text = "\r\n\r\n  포스에서 영수증을 1장 출력하면\r\n  여기에 내용이 표시됩니다.";
            }
        }

        private void UpdateManualEnabled()
        {
            _portCombo.Enabled = _manualRadio.Checked;
            _applyBtn.Enabled = _manualRadio.Checked && _service != null;
            if (_autoRadio.Checked && _config.PortLocked && _service != null)
            {
                // 자동으로 되돌림
                _config.PortLocked = false;
                _config.DetectedPort = null;
                SaveAndRestart("자동 모드로 바꿨습니다. 포스에서 영수증을 1장 출력해 주세요.");
            }
        }

        private void RefreshAll()
        {
            if (_service == null)
            {
                _statusTitle.Text = "로그인 필요";
                _statusDetail.Text = "트레이 아이콘 메뉴에서 로그인해 주세요.";
                _autoConnectBtn.Enabled = _testBtn.Enabled = _applyBtn.Enabled = false;
            }
            else
            {
                _statusTitle.Text = StatusTitle(_service.CurrentStatus);
                _statusDetail.Text = _service.StatusDetail;
            }
            _statusDot.Invalidate();

            _storeVal.Text = string.IsNullOrEmpty(_config.StoreName) ? "-" : _config.StoreName;

            var port = _service?.ReceiptPort;
            _portVal.Text = string.IsNullOrEmpty(port)
                ? "찾는 중 (영수증 1장 출력 필요)"
                : DisplayPort(port) + (_config.PortLocked ? " (직접 선택)" : " (자동 연결됨)");
            _portVal.ForeColor = string.IsNullOrEmpty(port) ? Color.FromArgb(41, 121, 255) : Color.FromArgb(0, 140, 60);

            var watched = _service?.WatchedPorts ?? new string[0];
            _watchVal.Text = watched.Length == 0 ? "없음" : string.Join(", ", watched);

            if (_service?.LastServerOkAt != null)
            {
                _serverVal.Text = $"정상 (마지막 확인 {_service.LastServerOkAt:HH:mm:ss})";
                _serverVal.ForeColor = _service.CurrentStatus == AgentStatus.Disconnected ? Color.FromArgb(200, 120, 0) : Color.FromArgb(0, 140, 60);
                if (_service.CurrentStatus == AgentStatus.Disconnected) _serverVal.Text = $"연결 안 됨 (마지막 정상 {_service.LastServerOkAt:HH:mm:ss})";
            }
            else
            {
                _serverVal.Text = _service == null ? "-" : "확인 중...";
                _serverVal.ForeColor = Color.Black;
            }

            var last = _service?.LastReceipt;
            _todayVal.Text = _service == null ? "-" :
                $"{_service.TodayCount}건" + (last != null ? $"  (마지막 {last.CapturedAt:HH:mm:ss})" : "");
            _queueVal.Text = _service == null ? "-" : $"{_service.QueueLength}건";
            _versionVal.Text = CaptureService.VERSION;

            UpdateWaitLabel();

            // 다른 경로로 새 영수증이 들어왔으면 표시 갱신 (업로드 결과 포함)
            if (last != null && (last != _shownReceipt || _uploadLbl.Text != UploadText(last)))
                ShowReceipt(last, false);
        }

        public static string DisplayPort(string port) =>
            port != null && port.StartsWith(SpoolerCapture.SourcePrefix)
                ? "프린터 " + port.Substring(SpoolerCapture.SourcePrefix.Length)
                : port;

        private static string StatusTitle(AgentStatus s)
        {
            switch (s)
            {
                case AgentStatus.Connected: return "정상 작동 중";
                case AgentStatus.Searching: return "프린터 찾는 중";
                case AgentStatus.Disconnected: return "서버 연결 안 됨";
                case AgentStatus.CaptureError: return "영수증 읽기 오류";
                case AgentStatus.LoginRequired: return "다시 로그인 필요";
                default: return "대기 중";
            }
        }

        // ───────────────────────── 버튼 ─────────────────────────

        private void OnAutoConnect(object sender, EventArgs e)
        {
            _config.PortLocked = false;
            _config.DetectedPort = null;
            _autoRadio.Checked = true;
            SaveAndRestart(null);
            StartWait(WaitMode.AutoConnect);
        }

        private void OnTest(object sender, EventArgs e)
        {
            StartWait(WaitMode.Test);
        }

        private void OnApplyManual(object sender, EventArgs e)
        {
            if (!(_portCombo.SelectedItem is SpmcPortInfo p)) return;
            _config.PortLocked = true;
            _config.ComPort = p.Key;
            _config.DetectedPort = null;
            SaveAndRestart(null);
            StartWait(WaitMode.Test);
        }

        private void SaveAndRestart(string message)
        {
            try { _config.Save(); } catch { }
            Cursor = Cursors.WaitCursor;
            try { _service?.RestartCapture(); }
            finally { Cursor = Cursors.Default; }
            if (message != null) SetWaitText(message, Color.FromArgb(41, 121, 255));
            RefreshAll();
        }

        private void StartWait(WaitMode mode)
        {
            if (_service == null) return;
            if (_service.CurrentStatus == AgentStatus.CaptureError)
            {
                SetWaitText("✖ 영수증 감시를 시작하지 못했습니다: " + _service.StatusDetail, Color.FromArgb(229, 57, 53));
                return;
            }
            _wait = mode;
            _waitUntil = DateTime.Now.AddSeconds(WAIT_SECONDS);
            UpdateWaitLabel();
        }

        private void UpdateWaitLabel()
        {
            if (_wait == WaitMode.None) return;
            var left = (int)Math.Ceiling((_waitUntil - DateTime.Now).TotalSeconds);
            if (left <= 0)
            {
                _wait = WaitMode.None;
                SetWaitText("✖ 영수증이 들어오지 않았습니다.\r\n포스에서 출력했는데도 안 되면 '로그 보기'를 눌러 담당자에게 보내주세요.",
                    Color.FromArgb(229, 57, 53));
                return;
            }
            SetWaitText($"▶ 지금 포스에서 영수증을 1장 출력해 주세요... ({left}초)", Color.FromArgb(41, 121, 255));
        }

        private void SetWaitText(string text, Color color)
        {
            _waitLbl.Text = text;
            _waitLbl.ForeColor = color;
        }

        // ───────────────────────── 이벤트 ─────────────────────────

        private void OnReceiptProcessed(object sender, CapturedReceipt r)
        {
            if (IsDisposed) return;
            try { BeginInvoke((Action)(() => HandleReceipt(r))); } catch { }
        }

        private void OnStatusChanged(object sender, AgentStatus s)
        {
            if (IsDisposed) return;
            try { BeginInvoke((Action)RefreshAll); } catch { }
        }

        private void HandleReceipt(CapturedReceipt r)
        {
            if (IsDisposed) return;
            var wasWaiting = _wait;
            _wait = WaitMode.None;
            ShowReceipt(r, true);

            if (wasWaiting == WaitMode.AutoConnect)
                SetWaitText($"✔ 연결 성공! {DisplayPort(r.Port)}에서 영수증을 읽었습니다.\r\n이제 영수증이 나올 때마다 자동으로 읽어옵니다.", Color.FromArgb(0, 140, 60));
            else if (wasWaiting == WaitMode.Test)
                SetWaitText($"✔ 테스트 성공! {DisplayPort(r.Port)}에서 영수증을 읽었습니다.", Color.FromArgb(0, 140, 60));
            RefreshAll();
        }

        private void ShowReceipt(CapturedReceipt r, bool flash)
        {
            _shownReceipt = r;
            _receiptHeader.Text = $"{r.CapturedAt:yyyy-MM-dd HH:mm:ss}  ·  {DisplayPort(r.Port)}  ·  {r.RawData.Length:N0}바이트";
            _receiptBox.Text = (r.Text ?? "").Replace("\n", "\r\n");
            _uploadLbl.Text = UploadText(r);
            _uploadLbl.ForeColor = (r.UploadState ?? "").Contains("완료") ? Color.FromArgb(0, 140, 60)
                : (r.UploadState ?? "").Contains("실패") ? Color.FromArgb(200, 120, 0) : Color.FromArgb(90, 90, 90);
            if (flash) { Activate(); }
        }

        private static string UploadText(CapturedReceipt r) => "서버: " + (r.UploadState ?? "-");

        private static void OpenLogs()
        {
            var logPath = AgentConfig.LogPath;
            System.IO.Directory.CreateDirectory(logPath);
            System.Diagnostics.Process.Start("explorer.exe", logPath);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            _uiTimer?.Stop();
            _uiTimer?.Dispose();
            if (_service != null)
            {
                _service.ReceiptProcessed -= OnReceiptProcessed;
                _service.StatusChanged -= OnStatusChanged;
            }
            base.OnFormClosed(e);
        }
    }
}
