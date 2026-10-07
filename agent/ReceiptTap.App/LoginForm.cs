using System;
using System.Drawing;
using System.Net;
using System.Text;
using System.Windows.Forms;
using Newtonsoft.Json;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    public class LoginForm : Form
    {
        private TextBox _emailTextBox;
        private TextBox _passwordTextBox;
        private Button _loginButton;
        private Label _statusLabel;
        private LinkLabel _signupLink;

        public string AuthToken { get; private set; }
        public int StoreId { get; private set; }
        public string StoreName { get; private set; }
        public string StoreCode { get; private set; }

        public LoginForm()
        {
            InitializeComponents();
        }

        private void InitializeComponents()
        {
            Text = "영수증리뷰 로그인";
            Size = new Size(420, 320);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            BackColor = Color.White;

            // 로고/제목
            var titleLabel = new Label
            {
                Text = "영수증리뷰",
                Location = new Point(20, 20),
                AutoSize = true,
                Font = new Font("맑은 고딕", 18, FontStyle.Bold),
                ForeColor = Color.FromArgb(3, 199, 90)
            };
            Controls.Add(titleLabel);

            var subtitleLabel = new Label
            {
                Text = "가입 시 등록한 이메일과 비밀번호로 로그인하세요",
                Location = new Point(20, 55),
                AutoSize = true,
                Font = new Font("맑은 고딕", 9),
                ForeColor = Color.Gray
            };
            Controls.Add(subtitleLabel);

            // 이메일
            var emailLabel = new Label
            {
                Text = "이메일",
                Location = new Point(20, 95),
                AutoSize = true,
                Font = new Font("맑은 고딕", 10, FontStyle.Bold)
            };
            Controls.Add(emailLabel);

            _emailTextBox = new TextBox
            {
                Location = new Point(20, 118),
                Size = new Size(360, 30),
                Font = new Font("맑은 고딕", 11)
            };
            Controls.Add(_emailTextBox);

            // 비밀번호
            var passwordLabel = new Label
            {
                Text = "비밀번호",
                Location = new Point(20, 155),
                AutoSize = true,
                Font = new Font("맑은 고딕", 10, FontStyle.Bold)
            };
            Controls.Add(passwordLabel);

            _passwordTextBox = new TextBox
            {
                Location = new Point(20, 178),
                Size = new Size(360, 30),
                Font = new Font("맑은 고딕", 11),
                PasswordChar = '●'
            };
            _passwordTextBox.KeyDown += (s, e) =>
            {
                if (e.KeyCode == Keys.Enter)
                {
                    OnLogin(s, e);
                    e.SuppressKeyPress = true;
                }
            };
            Controls.Add(_passwordTextBox);

            // 로그인 버튼
            _loginButton = new Button
            {
                Text = "로그인",
                Location = new Point(20, 220),
                Size = new Size(360, 40),
                BackColor = Color.FromArgb(3, 199, 90),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("맑은 고딕", 11, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _loginButton.FlatAppearance.BorderSize = 0;
            _loginButton.Click += OnLogin;
            Controls.Add(_loginButton);

            // 상태 라벨
            _statusLabel = new Label
            {
                Location = new Point(20, 268),
                Size = new Size(280, 20),
                ForeColor = Color.Red,
                Font = new Font("맑은 고딕", 9)
            };
            Controls.Add(_statusLabel);

            // 가입 링크
            _signupLink = new LinkLabel
            {
                Text = "가입하기",
                Location = new Point(310, 268),
                AutoSize = true,
                Font = new Font("맑은 고딕", 9),
                LinkColor = Color.FromArgb(3, 199, 90)
            };
            _signupLink.Click += (s, e) =>
            {
                System.Diagnostics.Process.Start("https://placemaster.co.kr/receipt-signup.html");
            };
            Controls.Add(_signupLink);
        }

        private async void OnLogin(object sender, EventArgs e)
        {
            var email = _emailTextBox.Text.Trim();
            var password = _passwordTextBox.Text;

            if (string.IsNullOrEmpty(email) || string.IsNullOrEmpty(password))
            {
                _statusLabel.Text = "이메일과 비밀번호를 입력하세요.";
                return;
            }

            _loginButton.Enabled = false;
            _statusLabel.ForeColor = Color.Gray;
            _statusLabel.Text = "로그인 중...";

            try
            {
                var config = AgentConfig.Load();
                var url = $"{config.ServerUrl}/auth/login";

                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;
                var request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = "POST";
                request.ContentType = "application/json";

                var payload = JsonConvert.SerializeObject(new { email, password });
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
                        var result = JsonConvert.DeserializeObject<LoginResponse>(body);

                        if (result.success)
                        {
                            AuthToken = result.token;
                            StoreId = result.store_id ?? 0;
                            StoreName = result.store_name;
                            StoreCode = result.store_code;

                            // 설정 저장
                            config.AuthToken = result.token;
                            config.StoreId = result.store_id ?? 0;
                            config.StoreName = result.store_name;
                            config.StoreCode = result.store_code;
                            config.Save();

                            DialogResult = DialogResult.OK;
                            Close();
                        }
                        else
                        {
                            _statusLabel.ForeColor = Color.Red;
                            _statusLabel.Text = result.message ?? "로그인에 실패했습니다.";
                            _loginButton.Enabled = true;
                        }
                    }
                }
            }
            catch (WebException ex)
            {
                _statusLabel.ForeColor = Color.Red;

                if (ex.Response is HttpWebResponse errorResponse)
                {
                    using (var reader = new System.IO.StreamReader(errorResponse.GetResponseStream()))
                    {
                        var errorBody = reader.ReadToEnd();
                        try
                        {
                            var errorResult = JsonConvert.DeserializeObject<LoginResponse>(errorBody);
                            _statusLabel.Text = errorResult.message ?? "로그인에 실패했습니다.";
                        }
                        catch
                        {
                            _statusLabel.Text = "서버 오류가 발생했습니다.";
                        }
                    }
                }
                else
                {
                    _statusLabel.Text = "서버에 연결할 수 없습니다.";
                }

                _loginButton.Enabled = true;
            }
            catch (Exception ex)
            {
                _statusLabel.ForeColor = Color.Red;
                _statusLabel.Text = "오류: " + ex.Message;
                _loginButton.Enabled = true;
            }
        }

        private class LoginResponse
        {
            public bool success { get; set; }
            public string token { get; set; }
            public int? store_id { get; set; }
            public string store_name { get; set; }
            public string store_code { get; set; }
            public string message { get; set; }
        }
    }
}
