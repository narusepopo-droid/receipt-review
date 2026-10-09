using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 모든 시리얼 포트를 동시에 지켜보다가, 영수증이 실제로 흘러간 포트를 찾아내는 캡처.
    /// - 점주가 포트를 고를 필요 없음: 설치 후 영수증 1장 출력하면 그 포트가 자동 등록됨
    /// - 고정 포트(lockedPort)를 주면 그 포트만 지켜봄
    /// - 영수증처럼 보이지 않는 데이터(고객표시기, 카드단말기 등)는 버림
    /// 반드시 UI(STA) 스레드에서 Start 할 것 (SPMC COM 객체 규칙)
    /// </summary>
    public class AutoPortCapture : IReceiptCapture
    {
        private readonly string _lockedPort;
        private readonly Dictionary<string, SpmcCapture> _captures =
            new Dictionary<string, SpmcCapture>(StringComparer.OrdinalIgnoreCase);
        private SpoolerCapture _spooler;
        private SynchronizationContext _uiContext;
        private Timer _rescanTimer;
        private bool _isCapturing;

        public string CaptureMode => "serial";
        public bool IsCapturing => _isCapturing;

        /// <summary>현재 지켜보는 포트 목록</summary>
        public IReadOnlyCollection<string> WatchedPorts
        {
            get
            {
                List<string> list;
                lock (_captures) list = _captures.Keys.ToList();
                if (_spooler != null && _spooler.IsCapturing) list.Add("윈도우 프린터");
                return list;
            }
        }

        /// <summary>마지막으로 영수증이 들어온 포트</summary>
        public string ReceiptPort { get; private set; }

        public event EventHandler<ReceiptCapturedEventArgs> ReceiptCaptured;
        public event EventHandler<CaptureErrorEventArgs> ErrorOccurred;
        /// <summary>영수증 포트를 (처음으로 또는 새로) 찾았을 때</summary>
        public event EventHandler<string> PortDetected;
        public event EventHandler<string> LogMessage;

        /// <param name="lockedPort">null 이면 모든 포트 자동 감시</param>
        /// <param name="knownPort">이전에 찾아둔 영수증 포트 (알림 중복 방지용)</param>
        public AutoPortCapture(string lockedPort = null, string knownPort = null)
        {
            _lockedPort = string.IsNullOrWhiteSpace(lockedPort) ? null : lockedPort;
            ReceiptPort = knownPort;
        }

        public void Start()
        {
            if (_isCapturing) return;
            _uiContext = SynchronizationContext.Current;

            var lockedPrinter = _lockedPort != null && _lockedPort.StartsWith(SpoolerCapture.SourcePrefix)
                ? _lockedPort.Substring(SpoolerCapture.SourcePrefix.Length) : null;
            var serialWanted = _lockedPort == null || lockedPrinter == null;
            var spoolerWanted = _lockedPort == null || lockedPrinter != null;

            // 1) 시리얼(COM) - SPMC
            string serialError = null;
            if (serialWanted)
            {
                try
                {
                    SpmcHost.Get();
                    if (!SpmcHost.LicenseInstalled)
                        Log("⚠ " + SpmcHost.LicenseError);
                    AttachPorts();
                }
                catch (Exception ex)
                {
                    serialError = ex.Message;
                    Log("시리얼 감시 불가: " + ex.Message);
                }
            }

            // 2) 윈도우 프린터 (네트워크·와이파이·드라이버 USB 프린터)
            if (spoolerWanted)
            {
                try
                {
                    _spooler = new SpoolerCapture(lockedPrinter);
                    _spooler.ReceiptCaptured += OnPortData;
                    _spooler.LogMessage += (s, m) => Log(m);
                    _spooler.ErrorOccurred += (s, e) => RaiseError(e.Exception, e.Message);
                    _spooler.Start();
                }
                catch (Exception ex)
                {
                    Log("윈도우 프린터 감시 불가: " + ex.Message);
                    _spooler = null;
                }
            }

            if (WatchedPorts.Count == 0)
                throw new InvalidOperationException(_lockedPort != null
                    ? $"{_lockedPort} 를 찾을 수 없습니다."
                    : "감시할 수 있는 프린터가 없습니다." + (serialError != null ? " (" + serialError + ")" : ""));

            _isCapturing = true;

            // USB-시리얼처럼 나중에 꽂히는 포트 대비, 1분마다 새 포트 확인 (UI 스레드에서 실행)
            if ((_lockedPort == null || !_lockedPort.StartsWith(SpoolerCapture.SourcePrefix)) && _uiContext != null)
                _rescanTimer = new Timer(_ => _uiContext.Post(__ => { if (_isCapturing) AttachPorts(); }, null),
                    null, TimeSpan.FromMinutes(1), TimeSpan.FromMinutes(1));
        }

        private void AttachPorts()
        {
            List<SpmcPortInfo> ports;
            try { ports = SpmcHost.GetPorts(); }
            catch (Exception ex) { RaiseError(ex, "포트 목록 조회 실패: " + ex.Message); return; }

            foreach (var p in ports)
            {
                if (!p.Present) continue;
                var key = p.Key;
                if (string.IsNullOrEmpty(key)) continue;
                if (_lockedPort != null && !key.Equals(_lockedPort, StringComparison.OrdinalIgnoreCase)) continue;
                lock (_captures) if (_captures.ContainsKey(key)) continue;

                var cap = new SpmcCapture(key);
                cap.ReceiptCaptured += OnPortData;
                cap.ErrorOccurred += (s, e) => RaiseError(e.Exception, e.Message);
                try
                {
                    cap.Start();
                    lock (_captures) _captures[key] = cap;
                    Log($"포트 감시 시작: {p}");
                }
                catch (Exception ex)
                {
                    Log($"포트 감시 실패: {key} ({ex.Message})");
                    cap.Dispose();
                }
            }
        }

        private void OnPortData(object sender, ReceiptCapturedEventArgs e)
        {
            if (!EscPosText.LooksLikeReceipt(e.RawData))
            {
                Log($"{e.Source}: 영수증이 아닌 데이터 {e.RawData.Length}바이트 무시");
                return;
            }

            var isNew = !string.Equals(ReceiptPort, e.Source, StringComparison.OrdinalIgnoreCase);
            ReceiptPort = e.Source;
            if (isNew)
            {
                Log($"영수증 프린터 포트 발견: {e.Source}");
                PortDetected?.Invoke(this, e.Source);
            }

            ReceiptCaptured?.Invoke(this, e);
        }

        public void Stop()
        {
            _isCapturing = false;
            _spooler?.Dispose();
            _spooler = null;
            _rescanTimer?.Dispose();
            _rescanTimer = null;

            List<SpmcCapture> list;
            lock (_captures) { list = _captures.Values.ToList(); _captures.Clear(); }
            foreach (var c in list)
            {
                try { c.Dispose(); } catch { }
            }
        }

        private void Log(string msg) => LogMessage?.Invoke(this, msg);

        private void RaiseError(Exception ex, string msg)
        {
            ErrorOccurred?.Invoke(this, new CaptureErrorEventArgs { Exception = ex, Message = msg });
        }

        public void Dispose() => Stop();
    }
}
