using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 자동 업데이트 관리
    /// 서버에서 새 버전 감지 시 자동으로 다운로드하고 설치
    /// </summary>
    public class AutoUpdater : IDisposable
    {
        private readonly AgentConfig _config;
        private readonly string _currentVersion;
        private Timer _checkTimer;
        private bool _isUpdating;

        public event EventHandler<string> LogMessage;
        public event EventHandler<UpdateInfo> UpdateAvailable;
        public event EventHandler<int> DownloadProgress;
        public event EventHandler UpdateStarting;

        /// <summary>
        /// 업데이트 파일 저장 경로
        /// </summary>
        private static string UpdatePath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "ReceiptTap", "updates"
        );

        public AutoUpdater(AgentConfig config, string currentVersion)
        {
            _config = config;
            _currentVersion = currentVersion;

            // TLS 1.2 강제
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;
        }

        /// <summary>
        /// 시작 시 업데이트 확인 (1회만)
        /// </summary>
        public void Start()
        {
            // 시작 후 10초 뒤에 1회만 체크
            _checkTimer = new Timer(
                async _ =>
                {
                    await CheckForUpdateAsync();
                    _checkTimer?.Dispose();
                    _checkTimer = null;
                },
                null,
                TimeSpan.FromSeconds(10),
                Timeout.InfiniteTimeSpan
            );

            Log("시작 시 업데이트 확인 예약됨");
        }

        /// <summary>
        /// 수동 업데이트 확인
        /// </summary>
        public async Task<UpdateInfo> CheckForUpdateAsync()
        {
            if (_isUpdating)
            {
                Log("이미 업데이트 진행 중");
                return null;
            }

            try
            {
                Log("업데이트 확인 중...");

                using (var client = new WebClient())
                {
                    client.Headers.Add("User-Agent", $"ReceiptTap/{_currentVersion}");

                    if (!string.IsNullOrEmpty(_config.AuthToken))
                    {
                        client.Headers.Add("Authorization", $"Bearer {_config.AuthToken}");
                    }

                    var url = $"{_config.ServerUrl}/agent/v1/latest";
                    var json = await client.DownloadStringTaskAsync(url);
                    var info = JsonConvert.DeserializeObject<UpdateInfo>(json);

                    if (info == null)
                    {
                        Log("버전 정보 파싱 실패");
                        return null;
                    }

                    // 버전 비교
                    if (IsNewerVersion(info.Version, _currentVersion))
                    {
                        Log($"새 버전 발견: {info.Version} (현재: {_currentVersion})");
                        UpdateAvailable?.Invoke(this, info);

                        // 자동 업데이트 실행
                        await DownloadAndInstallAsync(info);
                        return info;
                    }
                    else
                    {
                        Log($"최신 버전 사용 중: {_currentVersion}");
                        return null;
                    }
                }
            }
            catch (Exception ex)
            {
                Log($"업데이트 확인 실패: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// 다운로드 및 설치
        /// </summary>
        private async Task DownloadAndInstallAsync(UpdateInfo info)
        {
            _isUpdating = true;

            try
            {
                Directory.CreateDirectory(UpdatePath);

                var installerPath = Path.Combine(UpdatePath, $"ReceiptTap_Setup_{info.Version}.exe");

                // 이미 다운로드됐는지 확인
                if (File.Exists(installerPath) && VerifyChecksum(installerPath, info.Checksum))
                {
                    Log("이미 다운로드된 설치 파일 사용");
                }
                else
                {
                    Log($"다운로드 시작: {info.DownloadUrl}");

                    using (var client = new WebClient())
                    {
                        client.Headers.Add("User-Agent", $"ReceiptTap/{_currentVersion}");

                        client.DownloadProgressChanged += (s, e) =>
                        {
                            DownloadProgress?.Invoke(this, e.ProgressPercentage);
                        };

                        await client.DownloadFileTaskAsync(info.DownloadUrl, installerPath);
                    }

                    Log("다운로드 완료");

                    // 체크섬 검증
                    if (!string.IsNullOrEmpty(info.Checksum))
                    {
                        if (!VerifyChecksum(installerPath, info.Checksum))
                        {
                            Log("체크섬 불일치 - 다운로드 파일 삭제");
                            File.Delete(installerPath);
                            _isUpdating = false;
                            return;
                        }
                        Log("체크섬 검증 성공");
                    }
                }

                // 설치 실행
                await InstallUpdateAsync(installerPath);
            }
            catch (Exception ex)
            {
                Log($"업데이트 실패: {ex.Message}");
                _isUpdating = false;
            }
        }

        /// <summary>
        /// 설치 파일 실행
        /// </summary>
        private async Task InstallUpdateAsync(string installerPath)
        {
            Log("업데이트 설치 시작...");
            UpdateStarting?.Invoke(this, EventArgs.Empty);

            // 잠시 대기 (현재 작업 마무리)
            await Task.Delay(2000);

            try
            {
                // 업데이트 스크립트 생성
                var scriptPath = Path.Combine(UpdatePath, "update.bat");
                var currentExe = Process.GetCurrentProcess().MainModule.FileName;
                var serviceName = "ReceiptTap";

                var script = $@"@echo off
:: 서비스 중지
net stop {serviceName} >nul 2>&1

:: 기존 프로세스 종료 대기
timeout /t 3 /nobreak >nul

:: 설치 파일 실행 (자동 모드)
""{installerPath}"" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS

:: 서비스 시작
net start {serviceName} >nul 2>&1

:: 트레이 앱 재시작
start """" ""{currentExe}""

:: 스크립트 삭제
del ""%~f0""
";

                File.WriteAllText(scriptPath, script, Encoding.Default);

                // 스크립트 실행 (현재 프로세스와 독립적으로)
                var psi = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = $"/c \"{scriptPath}\"",
                    UseShellExecute = true,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden
                };

                Process.Start(psi);

                Log("업데이트 스크립트 실행됨 - 프로그램이 재시작됩니다");

                // 현재 앱 종료
                Environment.Exit(0);
            }
            catch (Exception ex)
            {
                Log($"설치 실행 실패: {ex.Message}");
                _isUpdating = false;
            }
        }

        /// <summary>
        /// 버전 비교 (새 버전이면 true)
        /// </summary>
        private bool IsNewerVersion(string newVersion, string currentVersion)
        {
            try
            {
                var newParts = newVersion.Split('.');
                var currentParts = currentVersion.Split('.');

                for (int i = 0; i < Math.Max(newParts.Length, currentParts.Length); i++)
                {
                    int newNum = i < newParts.Length ? int.Parse(newParts[i]) : 0;
                    int currentNum = i < currentParts.Length ? int.Parse(currentParts[i]) : 0;

                    if (newNum > currentNum) return true;
                    if (newNum < currentNum) return false;
                }

                return false; // 같은 버전
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// SHA256 체크섬 검증
        /// </summary>
        private bool VerifyChecksum(string filePath, string expectedChecksum)
        {
            using (var sha256 = SHA256.Create())
            using (var stream = File.OpenRead(filePath))
            {
                var hash = sha256.ComputeHash(stream);
                var actualChecksum = BitConverter.ToString(hash).Replace("-", "").ToLowerInvariant();
                return actualChecksum.Equals(expectedChecksum, StringComparison.OrdinalIgnoreCase);
            }
        }

        /// <summary>
        /// 이전 업데이트 파일 정리 (현재 버전 제외)
        /// </summary>
        public void CleanupOldUpdates()
        {
            try
            {
                if (!Directory.Exists(UpdatePath)) return;

                foreach (var file in Directory.GetFiles(UpdatePath, "ReceiptTap_Setup_*.exe"))
                {
                    // 현재 버전 파일은 유지
                    if (file.Contains(_currentVersion)) continue;

                    // 3일 이상 된 파일만 삭제
                    var fileInfo = new FileInfo(file);
                    if (fileInfo.LastWriteTime < DateTime.Now.AddDays(-3))
                    {
                        File.Delete(file);
                        Log($"이전 업데이트 파일 삭제: {Path.GetFileName(file)}");
                    }
                }
            }
            catch (Exception ex)
            {
                Log($"정리 실패: {ex.Message}");
            }
        }

        private void Log(string message)
        {
            LogMessage?.Invoke(this, message);
        }

        public void Dispose()
        {
            _checkTimer?.Dispose();
        }
    }

    /// <summary>
    /// 업데이트 정보
    /// </summary>
    public class UpdateInfo
    {
        [JsonProperty("version")]
        public string Version { get; set; }

        [JsonProperty("download_url")]
        public string DownloadUrl { get; set; }

        [JsonProperty("checksum")]
        public string Checksum { get; set; }

        [JsonProperty("file_size")]
        public long FileSize { get; set; }

        [JsonProperty("release_notes")]
        public string ReleaseNotes { get; set; }

        [JsonProperty("mandatory")]
        public bool Mandatory { get; set; }
    }
}
