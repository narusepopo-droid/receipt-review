using System;
using System.IO;
using System.Threading;
using hhdspmcLib;

namespace ReceiptTap.Core
{
    public class SpmcCapture : IReceiptCapture
    {
        private MonitoringClass _monitor;
        private readonly string _comPort;
        private bool _isCapturing;
        private MemoryStream _buffer;
        private DateTime _lastDataTime;
        private Timer _cutTimer;
        private readonly object _lockObj = new object();

        private const int CUT_TIMEOUT_MS = 500;
        private static readonly byte[] GS_V = { 0x1D, 0x56 };

        public string CaptureMode => "serial";
        public bool IsCapturing => _isCapturing;

        public event EventHandler<ReceiptCapturedEventArgs> ReceiptCaptured;
        public event EventHandler<CaptureErrorEventArgs> ErrorOccurred;

        public SpmcCapture(string comPort)
        {
            _comPort = comPort;
            _buffer = new MemoryStream();
        }

        public void Start()
        {
            if (_isCapturing) return;

            try
            {
                _monitor = new MonitoringClass();
                _monitor.OnWrite += Monitor_OnWrite;
                _monitor.Connect(_comPort);

                _isCapturing = true;
                _lastDataTime = DateTime.Now;

                _cutTimer = new Timer(CheckTimeout, null, 100, 100);
            }
            catch (Exception ex)
            {
                OnError(ex, $"SPMC 시작 실패: {ex.Message}");
            }
        }

        private void Monitor_OnWrite(DateTime time, Array array)
        {
            if (array == null || array.Length == 0) return;

            try
            {
                byte[] data = (byte[])array;

                lock (_lockObj)
                {
                    _buffer.Write(data, 0, data.Length);
                    _lastDataTime = DateTime.Now;

                    if (ContainsCutCommand(data))
                    {
                        FlushBuffer();
                    }
                }
            }
            catch { }
        }

        private void CheckTimeout(object state)
        {
            if (_buffer.Length > 0 && (DateTime.Now - _lastDataTime).TotalMilliseconds > CUT_TIMEOUT_MS)
            {
                lock (_lockObj)
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

                if (_monitor != null)
                {
                    _monitor.Disconnect();
                    System.Runtime.InteropServices.Marshal.ReleaseComObject(_monitor);
                    _monitor = null;
                }

                FlushBuffer();
                _isCapturing = false;
            }
            catch (Exception ex)
            {
                OnError(ex, "SPMC 중지 실패");
            }
        }

        private bool ContainsCutCommand(byte[] data)
        {
            for (int i = 0; i < data.Length - 1; i++)
            {
                if (data[i] == GS_V[0] && data[i + 1] == GS_V[1])
                    return true;
            }
            return false;
        }

        private void FlushBuffer()
        {
            if (_buffer.Length == 0) return;

            var rawData = _buffer.ToArray();
            _buffer = new MemoryStream();

            ReceiptCaptured?.Invoke(this, new ReceiptCapturedEventArgs
            {
                RawData = rawData,
                CapturedAt = DateTime.Now,
                Source = _comPort
            });
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

        public static string[] GetAvailablePorts()
        {
            return System.IO.Ports.SerialPort.GetPortNames();
        }

        public static bool IsSpmcInstalled()
        {
            try
            {
                var monitor = new MonitoringClass();
                System.Runtime.InteropServices.Marshal.ReleaseComObject(monitor);
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
