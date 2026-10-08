using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 에이전트 설정
    /// </summary>
    public class AgentConfig
    {
        private static readonly string ConfigPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "ReceiptTap", "config.json"
        );

        public string ServerUrl { get; set; } = "https://review.placemaster.co.kr";
        public string AgentKey { get; set; }
        public string AuthToken { get; set; }
        public int StoreId { get; set; }
        public string StoreName { get; set; }
        public string StoreCode { get; set; }
        public string CaptureMode { get; set; } = "serial";
        /// <summary>점주가 직접 고정한 포트 (PortLocked=true 일 때만 사용)</summary>
        public string ComPort { get; set; }
        /// <summary>true 면 ComPort 만 감시, false 면 모든 포트 자동 감시</summary>
        public bool PortLocked { get; set; }
        /// <summary>자동 감시로 영수증이 들어온 포트 (표시용)</summary>
        public string DetectedPort { get; set; }
        public string PrinterIp { get; set; }
        public int PrinterPort { get; set; } = 9100;
        public bool Activated { get; set; }

        /// <summary>
        /// 설정 로드
        /// </summary>
        public static AgentConfig Load()
        {
            try
            {
                if (File.Exists(ConfigPath))
                {
                    var json = File.ReadAllText(ConfigPath);
                    var config = JsonConvert.DeserializeObject<AgentConfig>(json);

                    // 민감 정보 복호화 (DPAPI)
                    if (!string.IsNullOrEmpty(config.AgentKey))
                    {
                        config.AgentKey = Decrypt(config.AgentKey);
                    }
                    if (!string.IsNullOrEmpty(config.AuthToken))
                    {
                        config.AuthToken = Decrypt(config.AuthToken);
                    }

                    return config;
                }
            }
            catch
            {
                // 설정 파일 오류 시 기본값
            }

            return new AgentConfig();
        }

        /// <summary>
        /// 설정 저장
        /// </summary>
        public void Save()
        {
            var dir = Path.GetDirectoryName(ConfigPath);
            Directory.CreateDirectory(dir);

            // 민감 정보 암호화 (DPAPI)
            var configToSave = new AgentConfig
            {
                ServerUrl = this.ServerUrl,
                AgentKey = !string.IsNullOrEmpty(this.AgentKey) ? Encrypt(this.AgentKey) : null,
                AuthToken = !string.IsNullOrEmpty(this.AuthToken) ? Encrypt(this.AuthToken) : null,
                StoreId = this.StoreId,
                StoreName = this.StoreName,
                StoreCode = this.StoreCode,
                CaptureMode = this.CaptureMode,
                ComPort = this.ComPort,
                PortLocked = this.PortLocked,
                DetectedPort = this.DetectedPort,
                PrinterIp = this.PrinterIp,
                PrinterPort = this.PrinterPort,
                Activated = this.Activated
            };

            var json = JsonConvert.SerializeObject(configToSave, Formatting.Indented);
            File.WriteAllText(ConfigPath, json);
        }

        /// <summary>
        /// DPAPI 암호화
        /// </summary>
        private static string Encrypt(string plainText)
        {
            var data = Encoding.UTF8.GetBytes(plainText);
            var encrypted = ProtectedData.Protect(data, null, DataProtectionScope.LocalMachine);
            return Convert.ToBase64String(encrypted);
        }

        /// <summary>
        /// DPAPI 복호화
        /// </summary>
        private static string Decrypt(string encryptedText)
        {
            var data = Convert.FromBase64String(encryptedText);
            var decrypted = ProtectedData.Unprotect(data, null, DataProtectionScope.LocalMachine);
            return Encoding.UTF8.GetString(decrypted);
        }

        /// <summary>
        /// 큐 경로
        /// </summary>
        public static string QueuePath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "ReceiptTap", "queue"
        );

        /// <summary>
        /// 로그 경로
        /// </summary>
        public static string LogPath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "ReceiptTap", "logs"
        );
    }
}
