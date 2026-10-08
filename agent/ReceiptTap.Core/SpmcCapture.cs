using System;
using System.IO;
using System.Threading;
using hhdspmcLib;

namespace ReceiptTap.Core
{
    /// <summary>
    /// SPMC 시리얼 포트 모니터링 캡처 (비간섭: 포스→프린터 쓰기 데이터를 옆에서 읽기만 함)
    /// </summary>
    public class SpmcCapture : IReceiptCapture
    {
        private Monitoring _monitor;
        private readonly string _comPort;
        private bool _isCapturing;
        private MemoryStream _buffer;
        private DateTime _lastDataTime;
        private Timer _cutTimer;
        private readonly object _lockObj = new object();

        private const int CUT_TIMEOUT_MS = 500;

        public string CaptureMode => "serial";
        public string Port => _comPort;
        public bool IsCapturing => _isCapturing;

        public event EventHandler<ReceiptCapturedEventArgs> ReceiptCaptured;
        public event EventHandler<CaptureErrorEventArgs> ErrorOccurred;

        public SpmcCapture(string comPort)
        {
            _comPort = comPort;
            _buffer = new MemoryStream();
        }

        /// <summary>
        /// 캡처 시작. 실패하면 예외를 던진다 (호출 쪽에서 상태를 "캡처 오류"로 표시해야 함)
        /// </summary>
        public void Start()
        {
            if (_isCapturing) return;

            try
            {
                var sm = SpmcHost.Get();
                var device = SpmcHost.FindDevice(_comPort);
                if (device == null)
                    throw new InvalidOperationException($"{_comPort} 포트를 찾을 수 없습니다.");

                _monitor = sm.CreateMonitor();
                _monitor.OnWrite += Monitor_OnWrite;
                _monitor.Connect(device);

                _isCapturing = true;
                _lastDataTime = DateTime.Now;
                _cutTimer = new Timer(CheckTimeout, null, 100, 100);
            }
            catch (Exception ex)
            {
                CleanupMonitor();
                OnError(ex, $"SPMC 시작 실패 ({_comPort}): {ex.Message}");
                throw;
            }
        }

        private void Monitor_OnWrite(DateTime time, Array array)
        {
            if (array == null || array.Length == 0) return;

            try
            {
                // SPMC는 byte/sbyte 배열을 줄 수 있으므로 그대로 복사 (카솔 방식)
                var data = new byte[array.Length];
                Buffer.BlockCopy(array, 0, data, 0, array.Length);

                lock (_lockObj)
                {
                    _buffer.Write(data, 0, data.Length);
                    _lastDataTime = DateTime.Now;
                    SplitAtCuts();
                }
            }
            catch (Exception ex)
            {
                OnError(ex, "데이터 수신 처리 오류: " + ex.Message);
            }
        }

        /// <summary>
        /// 버퍼에 GS V(커팅)가 있으면 그 지점까지를 영수증 1건으로 잘라 보낸다
        /// </summary>
        private void SplitAtCuts()
        {
            while (true)
            {
                var buf = _buffer.ToArray();
                int end = EscPosText.FindCutEnd(buf);
                if (end < 0) return;

                var receipt = new byte[end];
                Array.Copy(buf, receipt, end);
                _buffer = new MemoryStream();
                _buffer.Write(buf, end, buf.Length - end);
                Raise(receipt);
            }
        }

        private void CheckTimeout(object state)
        {
            lock (_lockObj)
            {
                if (_buffer.Length > 0 && (DateTime.Now - _lastDataTime).TotalMilliseconds > CUT_TIMEOUT_MS)
                {
                    FlushBuffer();
                }
            }
        }

        public void Stop()
        {
            if (!_isCapturing) return;

            try
            {
                _cutTimer?.Dispose();
                _cutTimer = null;
                CleanupMonitor();
                lock (_lockObj) FlushBuffer();
            }
            catch (Exception ex)
            {
                OnError(ex, "SPMC 중지 실패");
            }
            finally
            {
                _isCapturing = false;
            }
        }

        private void CleanupMonitor()
        {
            if (_monitor == null) return;
            try { _monitor.OnWrite -= Monitor_OnWrite; } catch { }
            try { if (_monitor.Connected) _monitor.Disconnect(); } catch { }
            try { System.Runtime.InteropServices.Marshal.ReleaseComObject(_monitor); } catch { }
            _monitor = null;
        }

        private void FlushBuffer()
        {
            if (_buffer.Length == 0) return;
            var rawData = _buffer.ToArray();
            _buffer = new MemoryStream();
            Raise(rawData);
        }

        private void Raise(byte[] rawData)
        {
            if (rawData.Length == 0) return;
            try
            {
                ReceiptCaptured?.Invoke(this, new ReceiptCapturedEventArgs
                {
                    RawData = rawData,
                    CapturedAt = DateTime.Now,
                    Source = _comPort
                });
            }
            catch (Exception ex)
            {
                OnError(ex, "영수증 처리 오류: " + ex.Message);
            }
        }

        private void OnError(Exception ex, string message)
        {
            ErrorOccurred?.Invoke(this, new CaptureErrorEventArgs
            {
                Exception = ex,
                Message = message
            });
        }

        public void Dispose()
        {
            Stop();
            _buffer?.Dispose();
        }

        public static bool IsSpmcInstalled()
        {
            try
            {
                SpmcHost.Get();
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
