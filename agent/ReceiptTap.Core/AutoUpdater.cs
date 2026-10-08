using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 자동 업데이트 (관리자 권한 불필요)
    /// 1) 서버 /agent/v1/latest 확인 (시작 30초 후, 이후 6시간마다)
    /// 2) 새 버전이면 zip 다운로드 → SHA-256 검증 → 압축 풀기
    /// 3) 프로그램 종료 후 파일 교체 스크립트가 새 파일 복사 → 다시 실행
    ///    복사 실패 시 백업으로 되돌림
    /// 설치 폴더는 설치 시 일반 사용자 쓰기 권한을 줌 (ReceiptTap.iss)
    /// </summary>
    public class AutoUpdater : IDisposable
    {
        private static readonly TimeSpan FirstCheckDelay = TimeSpan.FromSeconds(30);
        private static readonly TimeSpan CheckInterval = TimeSpan.FromHours(6);

        private readonly AgentConfig _config;
        private readonly string _currentVersion;
        private Timer _checkTimer;
        private int _isUpdating;

        public event EventHandler<string> LogMessage;
        public event EventHandler<UpdateInfo> UpdateAvailable;
        public event EventHandler<int> DownloadProgress;
        /// <summary>파일 교체를 위해 곧 종료됨 (구독자는 정리 작업 수행)</summary>
        public event EventHandler UpdateStarting;

        private static string UpdatePath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "ReceiptTap", "updates"
        );

        private static string FailedMarker => Path.Combine(UpdatePath, "failed.txt");

        private static string AppDir => AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');

        public AutoUpdater(AgentConfig config, string currentVersion)
        {
            _config = config;
            _currentVersion = currentVersion;
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072; // TLS 1.2
        }

        public void Start()
        {
            _checkTimer = new Timer(async _ => await CheckForUpdateAsync(), null, FirstCheckDelay, CheckInterval);
            Log("업데이트 확인 예약됨 (30초 후, 이후 6시간마다)");
        }

        public async Task<UpdateInfo> CheckForUpdateAsync()
        {
            if (Interlocked.CompareExchange(ref _isUpdating, 1, 0) != 0)
                return null;

            try
            {
                var info = await FetchLatestAsync();
                if (info == null || !IsNewerVersion(info.Version, _currentVersion))
                {
                    Log($"최신 버전 사용 중: {_currentVersion}");
                    return null;
                }
                if (string.IsNullOrEmpty(info.DownloadUrl) || string.IsNullOrEmpty(info.Checksum))
                {
                    Log($"새 버전 {info.Version} 정보가 불완전함 (주소/체크섬 없음) - 건너뜀");
                    return null;
                }
                if (RecentlyFailed(info.Version))
                {
                    Log($"새 버전 {info.Version}: 최근 업데이트 실패 기록이 있어 24시간 뒤 재시도");
                    return null;
                }
                if (!CanWriteAppDir())
                {
                    Log($"새 버전 {info.Version} 있음 - 설치 폴더에 쓰기 권한이 없어 자동 업데이트 불가 (설치 파일로 재설치 필요)");
                    return null;
                }

                Log($"새 버전 발견: {info.Version} (현재: {_currentVersion})");
                UpdateAvailable?.Invoke(this, info);

                var extracted = await DownloadAndExtractAsync(info);
                if (extracted == null) return null;

                LaunchSwapAndExit(info.Version, extracted);
                return info;
            }
            catch (Exception ex)
            {
                Log($"업데이트 확인 실패: {ex.Message}");
                return null;
            }
            finally
            {
                Interlocked.Exchange(ref _isUpdating, 0);
            }
        }

        private async Task<UpdateInfo> FetchLatestAsync()
        {
            using (var client = new WebClient())
            {
                client.Encoding = Encoding.UTF8;
                client.Headers.Add("User-Agent", $"ReceiptTap/{_currentVersion}");
                if (!string.IsNullOrEmpty(_config.AuthToken))
                    client.Headers.Add("Authorization", $"Bearer {_config.AuthToken}");

                var json = await client.DownloadStringTaskAsync($"{_config.ServerUrl}/agent/v1/latest");
                return JsonConvert.DeserializeObject<UpdateInfo>(json);
            }
        }

        /// <summary>zip 다운로드 + 검증 + 압축 풀기. 성공 시 풀린 폴더 경로</summary>
        private async Task<string> DownloadAndExtractAsync(UpdateInfo info)
        {
            Directory.CreateDirectory(UpdatePath);
            var zipPath = Path.Combine(UpdatePath, $"ReceiptTap_v{info.Version}.zip");
            var extractDir = Path.Combine(UpdatePath, info.Version);

            if (!(File.Exists(zipPath) && VerifyChecksum(zipPath, info.Checksum)))
            {
                Log($"다운로드 시작: {info.DownloadUrl}");
                using (var client = new WebClient())
                {
                    client.Headers.Add("User-Agent", $"ReceiptTap/{_currentVersion}");
                    client.DownloadProgressChanged += (s, e) => DownloadProgress?.Invoke(this, e.ProgressPercentage);
                    await client.DownloadFileTaskAsync(info.DownloadUrl, zipPath);
                }
                if (!VerifyChecksum(zipPath, info.Checksum))
                {
                    Log("체크섬 불일치 - 다운로드 파일 삭제");
                    TryDelete(zipPath);
                    MarkFailed(info.Version);
                    return null;
                }
                Log("다운로드·체크섬 검증 완료");
            }

            if (Directory.Exists(extractDir)) Directory.Delete(extractDir, true);
            ZipFile.ExtractToDirectory(zipPath, extractDir);

            // zip 안에 폴더가 하나 더 있는 경우 대비
            var root = extractDir;
            if (!File.Exists(Path.Combine(root, "ReceiptTap.exe")))
            {
                var sub = Directory.GetDirectories(extractDir);
                if (sub.Length == 1 && File.Exists(Path.Combine(sub[0], "ReceiptTap.exe"))) root = sub[0];
                else
                {
                    Log("업데이트 파일에 ReceiptTap.exe 가 없음 - 중단");
                    MarkFailed(info.Version);
                    return null;
                }
            }
            return root;
        }

        /// <summary>
        /// 파일 교체 스크립트 실행 후 종료.
        /// SPMC 드라이버/DLL·라이선스는 교체하지 않음 (등록된 COM, 카솔 공존 보호)
        /// </summary>
        private void LaunchSwapAndExit(string version, string sourceDir)
        {
            var pid = Process.GetCurrentProcess().Id;
            var backupDir = Path.Combine(UpdatePath, "backup_" + _currentVersion);
            var scriptPath = Path.Combine(UpdatePath, "update.cmd");
            var logPath = Path.Combine(UpdatePath, "update.log");
            var exe = Path.Combine(AppDir, "ReceiptTap.exe");
            const string exclude = "/XF hhdspmc.dll SPMC_License.spmclic install.bat /XD drivers";

            var script = $@"@echo off
chcp 65001 >nul
echo [%date% %time%] update {_currentVersion} -^> {version} > ""{logPath}""
:wait
tasklist /FI ""PID eq {pid}"" 2>nul | find ""{pid}"" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
robocopy ""{AppDir}"" ""{backupDir}"" /E /R:2 /W:1 {exclude} >> ""{logPath}""
robocopy ""{sourceDir}"" ""{AppDir}"" /E /R:5 /W:2 {exclude} >> ""{logPath}""
if errorlevel 8 (
  echo COPY FAILED - rollback >> ""{logPath}""
  robocopy ""{backupDir}"" ""{AppDir}"" /E /R:5 /W:2 >> ""{logPath}""
  echo {version} > ""{FailedMarker}""
)
start """" ""{exe}""
";
            // cmd 는 BOM 없는 UTF-8 + chcp 65001 로 한글 경로 처리
            File.WriteAllText(scriptPath, script, new UTF8Encoding(false));

            Log($"업데이트 설치: 프로그램을 잠시 종료하고 {version} 으로 교체합니다");
            try { UpdateStarting?.Invoke(this, EventArgs.Empty); } catch { }

            Process.Start(new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = $"/c \"{scriptPath}\"",
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = UpdatePath
            });

            Environment.Exit(0);
        }

        private static bool CanWriteAppDir()
        {
            try
            {
                var probe = Path.Combine(AppDir, ".write_test");
                File.WriteAllText(probe, "x");
                File.Delete(probe);
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static bool RecentlyFailed(string version)
        {
            try
            {
                if (!File.Exists(FailedMarker)) return false;
                var fi = new FileInfo(FailedMarker);
                return File.ReadAllText(FailedMarker).Trim() == version && fi.LastWriteTime > DateTime.Now.AddHours(-24);
            }
            catch { return false; }
        }

        private static void MarkFailed(string version)
        {
            try { Directory.CreateDirectory(UpdatePath); File.WriteAllText(FailedMarker, version); } catch { }
        }

        private static void TryDelete(string path)
        {
            try { File.Delete(path); } catch { }
        }

        public static bool IsNewerVersion(string newVersion, string currentVersion)
        {
            try
            {
                var a = (newVersion ?? "0").Split('.');
                var b = (currentVersion ?? "0").Split('.');
                for (int i = 0; i < Math.Max(a.Length, b.Length); i++)
                {
                    int x = i < a.Length ? int.Parse(a[i]) : 0;
                    int y = i < b.Length ? int.Parse(b[i]) : 0;
                    if (x != y) return x > y;
                }
                return false;
            }
            catch
            {
                return false;
            }
        }

        private static bool VerifyChecksum(string filePath, string expected)
        {
            if (string.IsNullOrEmpty(expected)) return false;
            using (var sha256 = SHA256.Create())
            using (var stream = File.OpenRead(filePath))
            {
                var actual = BitConverter.ToString(sha256.ComputeHash(stream)).Replace("-", "");
                return actual.Equals(expected, StringComparison.OrdinalIgnoreCase);
            }
        }

        /// <summary>오래된 업데이트 파일 정리 (3일 지난 것)</summary>
        public void CleanupOldUpdates()
        {
            try
            {
                if (!Directory.Exists(UpdatePath)) return;
                var limit = DateTime.Now.AddDays(-3);
                foreach (var f in Directory.GetFiles(UpdatePath))
                {
                    if (f.EndsWith("failed.txt")) continue;
                    if (File.GetLastWriteTime(f) < limit) TryDelete(f);
                }
                foreach (var d in Directory.GetDirectories(UpdatePath))
                {
                    if (Directory.GetLastWriteTime(d) < limit)
                    {
                        try { Directory.Delete(d, true); } catch { }
                    }
                }
            }
            catch (Exception ex)
            {
                Log($"정리 실패: {ex.Message}");
            }
        }

        private void Log(string message) => LogMessage?.Invoke(this, message);

        public void Dispose()
        {
            _checkTimer?.Dispose();
            _checkTimer = null;
        }
    }

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
