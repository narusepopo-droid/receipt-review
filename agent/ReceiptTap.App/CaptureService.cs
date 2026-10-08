using System;
using System.Threading;
using System.Threading.Tasks;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    /// <summary>
    /// 캡처 서비스 - 캡처 + 업로드 + 큐 관리 + 자동 업데이트
    /// UI(STA) 스레드에서 생성·Start 할 것 (SPMC COM 객체 규칙)
    /// </summary>
    public class CaptureService : IDisposable
    {
        public const string VERSION = "1.1.0";

        private readonly AgentConfig _config;
        private AutoPortCapture _capture;
        private ReceiptUploader _uploader;
        private LocalQueue _queue;
        private AutoUpdater _autoUpdater;
        private Timer _heartbeatTimer;
        private Timer _queueRetryTimer;
        private bool _isRunning;
        private bool _serverOk = true;

        public event EventHandler<AgentStatus> StatusChanged;
        public event EventHandler<string> LogMessage;
        public event EventHandler<UpdateInfo> UpdateAvailable;
        /// <summary>영수증 1건 처리 완료 (업로드 결과 포함)</summary>
        public event EventHandler<CapturedReceipt> ReceiptProcessed;
        /// <summary>영수증 프린터 포트를 자동으로 찾음</summary>
        public event EventHandler<string> PortDetected;

        public AgentStatus CurrentStatus { get; private set; } = AgentStatus.Idle;
        public string StatusDetail { get; private set; } = "";
        public CapturedReceipt LastReceipt { get; private set; }
        public int TodayCount { get; private set; }
        private DateTime _todayDate = DateTime.Today;
        public DateTime? LastServerOkAt { get; private set; }
        public int QueueLength => SafeQueueCount();
        public string ReceiptPort => _capture?.ReceiptPort ?? _config.DetectedPort;
        public string[] WatchedPorts => _capture == null ? new string[0] : new System.Collections.Generic.List<string>(_capture.WatchedPorts).ToArray();
        public bool PortLocked => _config.PortLocked;

        public CaptureService(AgentConfig config)
        {
            _config = config;
            _queue = new LocalQueue(AgentConfig.QueuePath);

            _autoUpdater = new AutoUpdater(config, VERSION);
            _autoUpdater.LogMessage += (s, msg) => Log($"[업데이트] {msg}");
            _autoUpdater.UpdateAvailable += (s, info) => UpdateAvailable?.Invoke(this, info);
            _autoUpdater.UpdateStarting += (s, e) => Log("업데이트 설치를 위해 프로그램이 재시작됩니다...");
        }

        public void Start()
        {
            if (_isRunning) return;
            if (!_config.Activated || string.IsNullOrEmpty(_config.AuthToken))
            {
                Log("로그인이 필요합니다.");
                SetStatus(AgentStatus.Idle, "로그인이 필요합니다");
                return;
            }

            _isRunning = true;
            _uploader = new ReceiptUploader(_config.ServerUrl, _config.AuthToken);

            // 서버 관련 타이머는 캡처 성공 여부와 상관없이 시작 (서버에 상태 보고)
            _heartbeatTimer = new Timer(SendHeartbeat, null, TimeSpan.Zero, TimeSpan.FromMinutes(1));
            _queueRetryTimer = new Timer(RetryQueue, null, TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(30));
            _autoUpdater.Start();
            _autoUpdater.CleanupOldUpdates();

            StartCapture();
        }

        private void StartCapture()
        {
            if (_config.CaptureMode == "network")
            {
                Log("네트워크 프린터 캡처는 아직 지원하지 않습니다.");
                SetStatus(AgentStatus.CaptureError, "네트워크 프린터는 아직 지원하지 않습니다");
                return;
            }

            var locked = _config.PortLocked ? _config.ComPort : null;
            _capture = new AutoPortCapture(locked, _config.DetectedPort);
            _capture.ReceiptCaptured += OnReceiptCaptured;
            _capture.ErrorOccurred += (s, e) => Log($"캡처 오류: {e.Message}");
            _capture.LogMessage += (s, m) => Log(m);
            _capture.PortDetected += OnPortDetected;

            try
            {
                _capture.Start();
                Log($"캡처 시작 (v{VERSION}) - 감시 포트: {string.Join(", ", WatchedPorts)}" +
                    (locked != null ? " (고정)" : " (자동)"));
                RefreshStatus();
            }
            catch (Exception ex)
            {
                Log($"캡처 시작 실패: {ex.Message}");
                SetStatus(AgentStatus.CaptureError, ex.Message);
                _capture.Dispose();
                _capture = null;
            }
        }

        /// <summary>설정 변경 후 캡처만 다시 시작</summary>
        public void RestartCapture()
        {
            if (!_isRunning) { Start(); return; }
            _capture?.Dispose();
            _capture = null;
            StartCapture();
        }

        public void Stop()
        {
            if (!_isRunning) return;

            _heartbeatTimer?.Dispose();
            _queueRetryTimer?.Dispose();
            _autoUpdater?.Dispose();
            _capture?.Dispose();
            _capture = null;

            _isRunning = false;
            SetStatus(AgentStatus.Idle, "중지됨");
            Log("캡처 중지");
        }

        public async Task<UpdateInfo> CheckForUpdateAsync()
        {
            return await _autoUpdater.CheckForUpdateAsync();
        }

        private void OnPortDetected(object sender, string port)
        {
            _config.DetectedPort = port;
            try { _config.Save(); } catch { }
            PortDetected?.Invoke(this, port);
        }

        private async void OnReceiptCaptured(object sender, ReceiptCapturedEventArgs e)
        {
            if (_todayDate != DateTime.Today) { _todayDate = DateTime.Today; TodayCount = 0; }
            TodayCount++;

            var receipt = new CapturedReceipt
            {
                RawData = e.RawData,
                CapturedAt = e.CapturedAt,
                Port = e.Source,
                Text = SafeText(e.RawData),
                UploadState = "전송 중..."
            };
            LastReceipt = receipt;
            Log($"영수증 캡처: {e.Source}, {e.RawData.Length} bytes");
            RefreshStatus();

            try
            {
                var result = await _uploader.UploadAsync(e.RawData, e.CapturedAt, "serial", VERSION);
                if (result.Success)
                {
                    receipt.UploadState = "서버 전송 완료";
                    Log($"업로드 성공: {result.Response}");
                    MarkServer(true);
                }
                else
                {
                    receipt.UploadState = "서버 전송 실패 → 나중에 자동 재전송";
                    Log($"업로드 실패 (큐 저장): {result.Error}");
                    _queue.Enqueue(e.RawData, e.CapturedAt, "serial");
                    MarkServer(false);
                }
            }
            catch (Exception ex)
            {
                receipt.UploadState = "서버 전송 실패 → 나중에 자동 재전송";
                Log($"업로드 오류 (큐 저장): {ex.Message}");
                _queue.Enqueue(e.RawData, e.CapturedAt, "serial");
                MarkServer(false);
            }

            ReceiptProcessed?.Invoke(this, receipt);
        }

        private static string SafeText(byte[] data)
        {
            try { return EscPosText.ToText(data); } catch { return "(내용 표시 실패)"; }
        }

        private async void SendHeartbeat(object state)
        {
            if (_uploader == null) return;
            try
            {
                var ok = await _uploader.SendHeartbeatAsync(VERSION, "serial", LastReceipt?.CapturedAt, SafeQueueCount());
                MarkServer(ok);
            }
            catch
            {
                MarkServer(false);
            }
        }

        private async void RetryQueue(object state)
        {
            if (_uploader == null || SafeQueueCount() == 0) return;

            foreach (var item in _queue.GetPendingItems())
            {
                try
                {
                    var data = _queue.LoadData(item);
                    var result = await _uploader.UploadAsync(data, item.CapturedAt, item.CaptureMode, VERSION);
                    if (!result.Success) break;
                    _queue.Remove(item.Id);
                    Log($"큐 재시도 성공: {item.Id}");
                    MarkServer(true);
                }
                catch
                {
                    break;
                }
            }
        }

        private void MarkServer(bool ok)
        {
            _serverOk = ok;
            if (ok) LastServerOkAt = DateTime.Now;
            RefreshStatus();
        }

        /// <summary>현재 상황으로 상태 다시 계산</summary>
        private void RefreshStatus()
        {
            if (!_isRunning) return;
            if (_capture == null || !_capture.IsCapturing)
            {
                if (CurrentStatus != AgentStatus.CaptureError)
                    SetStatus(AgentStatus.CaptureError, "영수증 감시가 시작되지 않았습니다");
                return;
            }
            if (!_serverOk)
            {
                SetStatus(AgentStatus.Disconnected, $"서버 연결 안 됨 (대기 중인 영수증 {SafeQueueCount()}건)");
                return;
            }
            if (string.IsNullOrEmpty(ReceiptPort))
            {
                SetStatus(AgentStatus.Searching, "프린터 찾는 중 - 포스에서 영수증을 1장 출력해 주세요");
                return;
            }
            SetStatus(AgentStatus.Connected, $"{ReceiptPort} 프린터에서 영수증 수신 중");
        }

        private void SetStatus(AgentStatus status, string detail)
        {
            CurrentStatus = status;
            StatusDetail = detail;
            StatusChanged?.Invoke(this, status);
        }

        private int SafeQueueCount()
        {
            try { return _queue.Count; } catch { return 0; }
        }

        private void Log(string message)
        {
            LogMessage?.Invoke(this, message);
            try
            {
                var logDir = AgentConfig.LogPath;
                System.IO.Directory.CreateDirectory(logDir);
                var logFile = System.IO.Path.Combine(logDir, $"{DateTime.Now:yyyy-MM-dd}.log");
                System.IO.File.AppendAllText(logFile, $"{DateTime.Now:HH:mm:ss} {message}\r\n");
            }
            catch { }
        }

        public void Dispose()
        {
            Stop();
        }
    }

    public class CapturedReceipt
    {
        public byte[] RawData { get; set; }
        public DateTime CapturedAt { get; set; }
        public string Port { get; set; }
        public string Text { get; set; }
        public string UploadState { get; set; }
    }
}
