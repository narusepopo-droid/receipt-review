using System;
using System.Net;
using System.Text;
using System.Windows.Forms;
using Newtonsoft.Json;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    public class ActivationForm : Form
    {
        private TextBox _codeTextBox;
        private Button _activateButton;
        private Label _statusLabel;

        public ActivationForm()
        {
            InitializeComponents();
        }

        private void InitializeComponents()
        {
            Text = "ReceiptTap 활성화";
            Size = new System.Drawing.Size(400, 200);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;

            var label = new Label
            {
                Text = "활성화 코드를 입력하세요:",
                Location = new System.Drawing.Point(20, 20),
                AutoSize = true
            };
            Controls.Add(label);

            _codeTextBox = new TextBox
            {
                Location = new System.Drawing.Point(20, 50),
                Size = new System.Drawing.Size(340, 30),
                Font = new System.Drawing.Font("Consolas", 14),
                MaxLength = 8,
                CharacterCasing = CharacterCasing.Upper
            };
            Controls.Add(_codeTextBox);

            _activateButton = new Button
            {
                Text = "활성화",
                Location = new System.Drawing.Point(20, 90),
                Size = new System.Drawing.Size(340, 35)
            };
            _activateButton.Click += OnActivate;
            Controls.Add(_activateButton);

            _statusLabel = new Label
            {
                Location = new System.Drawing.Point(20, 130),
                Size = new System.Drawing.Size(340, 20),
                ForeColor = System.Drawing.Color.Red
            };
            Controls.Add(_statusLabel);
        }

        private async void OnActivate(object sender, EventArgs e)
        {
            var code = _codeTextBox.Text.Trim();
            if (code.Length != 8)
            {
                _statusLabel.Text = "8자리 코드를 입력하세요.";
                return;
            }

            _activateButton.Enabled = false;
            _statusLabel.Text = "활성화 중...";

            try
            {
                var config = AgentConfig.Load();
                var url = $"{config.ServerUrl}/agent/v1/activate";

                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;
                var request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = "POST";
                request.ContentType = "application/json";

                var payload = JsonConvert.SerializeObject(new { activation_code = code });
                var data = Encoding.UTF8.GetBytes(payload);

                using (var stream = await request.GetRequestStreamAsync())
                {
                    stream.Write(data, 0, data.Length);
                }

                using (var response = (HttpWebResponse)await request.GetResponseAsync())
                {
                    using (var reader = new System.IO.StreamReader(response.GetResponseStream()))
                    {
                        var body = await reader.ReadToEndAsync();
                        var result = Newtonsoft.Json.Linq.JObject.Parse(body);

                        config.AgentKey = result["agent_key"]?.ToString();
                        config.Activated = true;
                        config.Save();

                        MessageBox.Show("활성화 완료!", "ReceiptTap", MessageBoxButtons.OK, MessageBoxIcon.Information);
                        DialogResult = DialogResult.OK;
                        Close();
                    }
                }
            }
            catch (WebException ex)
            {
                var response = ex.Response as HttpWebResponse;
                if (response?.StatusCode == HttpStatusCode.NotFound)
                {
                    _statusLabel.Text = "유효하지 않은 활성화 코드입니다.";
                }
                else
                {
                    _statusLabel.Text = "서버 연결 실패: " + ex.Message;
                }
            }
            catch (Exception ex)
            {
                _statusLabel.Text = "오류: " + ex.Message;
            }
            finally
            {
                _activateButton.Enabled = true;
            }
        }
    }
}
