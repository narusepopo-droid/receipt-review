using System;
using System.Threading;
using System.Threading.Tasks;
using ReceiptTap.Core;

namespace ReceiptTap.App
{
    /// <summary>
    /// 캡처 서비스 - 캡처 + 업로드 + 큐 관리
    /// </summary>
    public class CaptureService : IDisposable
    {
        private readonly AgentConfig _config;
        private IReceiptCapture _capture;
        private ReceiptUploader _uploader;
        private LocalQueue _queue;
        private Timer _heartbeatTimer;
        private Timer _queueRetryTimer;
        private DateTime? _lastCaptureAt;
        private bool _isRunning;

        public event EventHandler<AgentStatus> StatusChanged;
        public event EventHandler<string> LogMessage;

        public AgentStatus CurrentStatus { get; private set; } = AgentStatus.Idle;

        public CaptureService(AgentConfig config)
        {
            _config = config;
            _queue = new LocalQueue(AgentConfig.QueuePath);
        }

        public void Start()
        {
            if (_isRunning) return;
            if (!_config.Activated || string.IsNullOrEmpty(_config.AgentKey))
            {
                Log("활성화가 필요합니다.");
                return;
            }

            try
            {
                _uploader = new ReceiptUploader(_config.ServerUrl, _config.AgentKey);

                // 캡처 방식에 따라 생성
                if (_config.CaptureMode == "serial" && !string.IsNullOrEmpty(_config.ComPort))
                {
                    _capture = new SpmcCapture(_config.ComPort);
                }
                else if (_config.CaptureMode == "network" && !string.IsNullOrEmpty(_config.PrinterIp))
                {
                    // 네트워크 캡처는 추후 구현
                    Log("네트워크 캡처는 아직 지원하지 않습니다.");
                    return;
                }
                else
                {
                    Log("캡처 설정이 필요합니다.");
                    return;
                }

                _capture.ReceiptCaptured += OnReceiptCaptured;
                _capture.ErrorOccurred += OnCaptureError;
                _capture.Start();

                // 하트비트 타이머 (1분마다)
                _heartbeatTimer = new Timer(SendHeartbeat, null, TimeSpan.Zero, TimeSpan.FromMinutes(1));

                // 큐 재시도 타이머 (30초마다)
                _queueRetryTimer = new Timer(RetryQueue, null, TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(30));

                _isRunning = true;
                UpdateStatus(AgentStatus.Connected);
                Log($"캡처 시작: {_config.CaptureMode} - {_config.ComPort ?? _config.PrinterIp}");
            }
            catch (Exception ex)
            {
                Log($"시작 실패: {ex.Message}");
                UpdateStatus(AgentStatus.CaptureError);
            }
        }

        public void Stop()
        {
            if (!_isRunning) return;

            _heartbeatTimer?.Dispose();
            _queueRetryTimer?.Dispose();
            _capture?.Stop();
            _capture?.Dispose();

            _isRunning = false;
            UpdateStatus(AgentStatus.Idle);
            Log("캡처 중지");
        }

        private async void OnReceiptCaptured(object sender, ReceiptCapturedEventArgs e)
        {
            _lastCaptureAt = e.CapturedAt;
            Log($"영수증 캡처: {e.RawData.Length} bytes");

            try
            {
                var result = await _uploader.UploadAsync(
                    e.RawData,
                    e.CapturedAt,
                    _capture.CaptureMode,
                    "1.0.0"
                );

                if (result.Success)
                {
                    Log($"업로드 성공: {result.Response}");
                    UpdateStatus(AgentStatus.Connected);
                }
                else
                {
                    Log($"업로드 실패 (큐 저장): {result.Error}");
                    _queue.Enqueue(e.RawData, e.CapturedAt, _capture.CaptureMode);
                    UpdateStatus(AgentStatus.Disconnected);
                }
            }
            catch (Exception ex)
            {
                Log($"업로드 오류 (큐 저장): {ex.Message}");
                _queue.Enqueue(e.RawData, e.CapturedAt, _capture.CaptureMode);
                UpdateStatus(AgentStatus.Disconnected);
            }
        }

        private void OnCaptureError(object sender, CaptureErrorEventArgs e)
        {
            Log($"캡처 오류: {e.Message}");
            UpdateStatus(AgentStatus.CaptureError);
        }

        private async void SendHeartbeat(object state)
        {
            if (_uploader == null) return;

            try
            {
                var success = await _uploader.SendHeartbeatAsync(
                    "1.0.0",
                    _capture?.CaptureMode ?? "unknown",
                    _lastCaptureAt,
                    _queue.Count
                );

                if (success && CurrentStatus == AgentStatus.Disconnected)
                {
                    UpdateStatus(AgentStatus.Connected);
                }
            }
            catch
            {
                // 하트비트 실패는 조용히 처리
            }
        }

        private async void RetryQueue(object state)
        {
            if (_uploader == null || _queue.Count == 0) return;

            foreach (var item in _queue.GetPendingItems())
            {
                try
                {
                    var data = _queue.LoadData(item);
                    var result = await _uploader.UploadAsync(
                        data,
                        item.CapturedAt,
                        item.CaptureMode,
                        "1.0.0"
                    );

                    if (result.Success)
                    {
                        _queue.Remove(item.Id);
                        Log($"큐 재시도 성공: {item.Id}");
                    }
                }
                catch
                {
                    // 재시도 실패, 다음에 다시 시도
                    break;
                }
            }
        }

        private void UpdateStatus(AgentStatus status)
        {
            CurrentStatus = status;
            StatusChanged?.Invoke(this, status);
        }

        private void Log(string message)
        {
            LogMessage?.Invoke(this, message);

            // 파일 로깅
            try
            {
                var logDir = AgentConfig.LogPath;
                System.IO.Directory.CreateDirectory(logDir);
                var logFile = System.IO.Path.Combine(logDir, $"{DateTime.Now:yyyy-MM-dd}.log");
                System.IO.File.AppendAllText(logFile, $"{DateTime.Now:HH:mm:ss} {message}\n");
            }
            catch { }
        }

        public void Dispose()
        {
            Stop();
        }
    }
}
