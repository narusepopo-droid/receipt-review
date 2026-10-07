using System;
using System.Windows.Forms;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    public class SettingsForm : Form
    {
        private AgentConfig _config;
        private ComboBox _captureModeCombo;
        private TextBox _comPortTextBox;
        private TextBox _printerIpTextBox;
        private Button _saveButton;
        private Button _testButton;

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

            _comPortTextBox = new TextBox
            {
                Location = new System.Drawing.Point(120, 57),
                Size = new System.Drawing.Size(100, 25),
                Text = "COM1"
            };
            Controls.Add(_comPortTextBox);

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
            _comPortTextBox.Text = _config.ComPort ?? "COM1";
            _printerIpTextBox.Text = _config.PrinterIp ?? "192.168.0.100";
            OnCaptureModeChanged(null, null);
        }

        private void OnCaptureModeChanged(object sender, EventArgs e)
        {
            var isSerial = _captureModeCombo.SelectedIndex == 0;
            _comPortTextBox.Enabled = isSerial;
            _printerIpTextBox.Enabled = !isSerial;
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
            _config.ComPort = _comPortTextBox.Text;
            _config.PrinterIp = _printerIpTextBox.Text;
            _config.Save();

            DialogResult = DialogResult.OK;
            Close();
        }
    }
}
