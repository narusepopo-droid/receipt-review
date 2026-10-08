using System;
using System.IO.Ports;
using System.Linq;
using System.Windows.Forms;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    public class SettingsForm : Form
    {
        private AgentConfig _config;
        private ComboBox _captureModeCombo;
        private ComboBox _comPortCombo;
        private TextBox _printerIpTextBox;
        private Button _saveButton;
        private Button _testButton;
        private Button _detectButton;

        public SettingsForm(AgentConfig config)
        {
            _config = config;
            InitializeComponents();
            LoadConfig();
        }

        private void InitializeComponents()
        {
            Text = "ReceiptTap 설정";
            Size = new System.Drawing.Size(450, 300);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;

            // 캡처 방식
            var modeLabel = new Label
            {
                Text = "캡처 방식:",
                Location = new System.Drawing.Point(20, 20),
                AutoSize = true
            };
            Controls.Add(modeLabel);

            _captureModeCombo = new ComboBox
            {
                Location = new System.Drawing.Point(120, 17),
                Size = new System.Drawing.Size(200, 25),
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            _captureModeCombo.Items.AddRange(new[] { "시리얼 (COM 포트)", "네트워크 (TCP/IP)" });
            _captureModeCombo.SelectedIndexChanged += OnCaptureModeChanged;
            Controls.Add(_captureModeCombo);

            // COM 포트
            var comLabel = new Label
            {
                Text = "COM 포트:",
                Location = new System.Drawing.Point(20, 60),
                AutoSize = true
            };
            Controls.Add(comLabel);

            _comPortCombo = new ComboBox
            {
                Location = new System.Drawing.Point(120, 57),
                Size = new System.Drawing.Size(100, 25),
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            Controls.Add(_comPortCombo);

            _detectButton = new Button
            {
                Text = "자동 감지",
                Location = new System.Drawing.Point(230, 55),
                Size = new System.Drawing.Size(90, 28)
            };
            _detectButton.Click += OnDetect;
            Controls.Add(_detectButton);

            // 초기 COM 포트 목록 로드
            RefreshComPorts();

            // 프린터 IP
            var ipLabel = new Label
            {
                Text = "프린터 IP:",
                Location = new System.Drawing.Point(20, 100),
                AutoSize = true
            };
            Controls.Add(ipLabel);

            _printerIpTextBox = new TextBox
            {
                Location = new System.Drawing.Point(120, 97),
                Size = new System.Drawing.Size(150, 25),
                Text = "192.168.0.100"
            };
            Controls.Add(_printerIpTextBox);

            // 테스트 버튼
            _testButton = new Button
            {
                Text = "테스트 출력 확인",
                Location = new System.Drawing.Point(20, 150),
                Size = new System.Drawing.Size(150, 35)
            };
            _testButton.Click += OnTest;
            Controls.Add(_testButton);

            // 저장 버튼
            _saveButton = new Button
            {
                Text = "저장",
                Location = new System.Drawing.Point(200, 200),
                Size = new System.Drawing.Size(100, 35)
            };
            _saveButton.Click += OnSave;
            Controls.Add(_saveButton);

            // 취소 버튼
            var cancelButton = new Button
            {
                Text = "취소",
                Location = new System.Drawing.Point(310, 200),
                Size = new System.Drawing.Size(100, 35)
            };
            cancelButton.Click += (s, e) => Close();
            Controls.Add(cancelButton);
        }

        private void LoadConfig()
        {
            _captureModeCombo.SelectedIndex = _config.CaptureMode == "network" ? 1 : 0;

            // 저장된 COM 포트 선택
            var savedPort = _config.ComPort ?? "COM1";
            for (int i = 0; i < _comPortCombo.Items.Count; i++)
            {
                if (_comPortCombo.Items[i].ToString() == savedPort)
                {
                    _comPortCombo.SelectedIndex = i;
                    break;
                }
            }
            if (_comPortCombo.SelectedIndex < 0 && _comPortCombo.Items.Count > 0)
                _comPortCombo.SelectedIndex = 0;

            _printerIpTextBox.Text = _config.PrinterIp ?? "192.168.0.100";
            OnCaptureModeChanged(null, null);
        }

        private void OnCaptureModeChanged(object sender, EventArgs e)
        {
            var isSerial = _captureModeCombo.SelectedIndex == 0;
            _comPortCombo.Enabled = isSerial;
            _detectButton.Enabled = isSerial;
            _printerIpTextBox.Enabled = !isSerial;
        }

        private void RefreshComPorts()
        {
            _comPortCombo.Items.Clear();
            try
            {
                var ports = SerialPort.GetPortNames();
                foreach (var port in ports)
                {
                    _comPortCombo.Items.Add(port);
                }
            }
            catch { }

            if (_comPortCombo.Items.Count == 0)
            {
                _comPortCombo.Items.Add("COM1");
            }
        }

        private void OnDetect(object sender, EventArgs e)
        {
            RefreshComPorts();

            if (_comPortCombo.Items.Count == 0)
            {
                MessageBox.Show("COM 포트를 찾을 수 없습니다.", "자동 감지", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            // 첫 번째 포트 선택
            _comPortCombo.SelectedIndex = 0;

            var portList = string.Join(", ", _comPortCombo.Items.Cast<string>());
            MessageBox.Show(
                $"발견된 COM 포트: {portList}\n\n" +
                "영수증 프린터가 연결된 포트를 선택하세요.",
                "자동 감지",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );
        }

        private void OnTest(object sender, EventArgs e)
        {
            MessageBox.Show(
                "포스에서 영수증을 1장 출력해 주세요.\n\n" +
                "캡처가 성공하면 '캡처 성공!' 메시지가 표시됩니다.",
                "테스트 출력 확인",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );
            // TODO: 실제 캡처 테스트 구현
        }

        private void OnSave(object sender, EventArgs e)
        {
            _config.CaptureMode = _captureModeCombo.SelectedIndex == 0 ? "serial" : "network";
            _config.ComPort = _comPortCombo.SelectedItem?.ToString() ?? "COM1";
            _config.PrinterIp = _printerIpTextBox.Text;
            _config.Save();

            DialogResult = DialogResult.OK;
            Close();
        }
    }
}
