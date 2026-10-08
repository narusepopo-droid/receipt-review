using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace ReceiptTap.Core
{
    /// <summary>
    /// HHD SPMC를 이용한 시리얼 포트 모니터링 캡처
    /// 포스 → 프린터 통신을 옆에서 읽기만 함 (비간섭)
    /// </summary>
    public class SpmcCapture : IReceiptCapture
    {
        private dynamic _monitor;
        private readonly string _comPort;
        private bool _isCapturing;
        private MemoryStream _buffer;
        private DateTime _lastDataTime;
        private Timer _cutTimer;
        private readonly object _lockObj = new object();

        // 출력 작업 경계 판별용
        private const int CUT_TIMEOUT_MS = 500;  // 500ms 동안 데이터 없으면 1건 종료
        private static readonly byte[] GS_V = { 0x1D, 0x56 };  // GS V (용지 커팅)

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
                // Interop DLL에서 직접 타입 로드 (COM 등록 불필요)
                var interopPath = System.IO.Path.Combine(
                    AppDomain.CurrentDomain.BaseDirectory,
                    "Interop.hhdspmcLib.dll"
                );

                if (!System.IO.File.Exists(interopPath))
                {
                    throw new InvalidOperationException("Interop.hhdspmcLib.dll 파일이 없습니다.");
                }

                var assembly = System.Reflection.Assembly.LoadFrom(interopPath);
                var monitorType = assembly.GetType("hhdspmcLib.MonitorClass");

                if (monitorType == null)
                {
                    // 대안: COM ProgID로 시도
                    var spmcType = Type.GetTypeFromProgID("HHDSPMC.Monitor");
                    if (spmcType == null)
                    {
                        throw new InvalidOperationException("SPMC를 초기화할 수 없습니다.");
                    }
                    _monitor = Activator.CreateInstance(spmcType);
                }
                else
                {
                    _monitor = Activator.CreateInstance(monitorType);
                }

                // 이벤트 연결
                // SPMC는 OnData 이벤트로 데이터를 전달
                // dynamic을 통한 이벤트 연결은 복잡하므로 폴링 방식으로 대체

                // 모니터링 시작
                _monitor.Connect(_comPort);
                _monitor.Start();

                _isCapturing = true;
                _lastDataTime = DateTime.Now;

                // 데이터 폴링 타이머
                _cutTimer = new Timer(CheckData, null, 100, 100);
            }
            catch (COMException ex)
            {
                OnError(ex, "SPMC 시작 실패: COM 오류");
            }
            catch (Exception ex)
            {
                OnError(ex, "SPMC 시작 실패");
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
                    _monitor.Stop();
                    _monitor.Disconnect();
                    Marshal.ReleaseComObject(_monitor);
                    _monitor = null;
                }

                // 남은 버퍼 처리
                FlushBuffer();

                _isCapturing = false;
            }
            catch (Exception ex)
            {
                OnError(ex, "SPMC 중지 실패");
            }
        }

        private void CheckData(object state)
        {
            if (!_isCapturing || _monitor == null) return;

            try
            {
                // SPMC에서 데이터 읽기
                // 실제 SPMC API에 따라 조정 필요
                byte[] data = null;

                try
                {
                    // SPMC의 GetData 또는 유사 메서드 호출
                    var result = _monitor.GetData();
                    if (result != null && result.Length > 0)
                    {
                        data = (byte[])result;
                    }
                }
                catch
                {
                    // 데이터 없음
                }

                if (data != null && data.Length > 0)
                {
                    lock (_lockObj)
                    {
                        _buffer.Write(data, 0, data.Length);
                        _lastDataTime = DateTime.Now;

                        // GS V (커팅) 명령 감지
                        if (ContainsCutCommand(data))
                        {
                            FlushBuffer();
                        }
                    }
                }
                else
                {
                    // 타임아웃 체크
                    if (_buffer.Length > 0 && (DateTime.Now - _lastDataTime).TotalMilliseconds > CUT_TIMEOUT_MS)
                    {
                        lock (_lockObj)
                        {
                            FlushBuffer();
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                OnError(ex, "데이터 읽기 실패");
            }
        }

        private bool ContainsCutCommand(byte[] data)
        {
            for (int i = 0; i < data.Length - 1; i++)
            {
                if (data[i] == GS_V[0] && data[i + 1] == GS_V[1])
                {
                    return true;
                }
            }
            return false;
        }

        private void FlushBuffer()
        {
            if (_buffer.Length == 0) return;

            var rawData = _buffer.ToArray();
            _buffer = new MemoryStream();

            // 이벤트 발생
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

        /// <summary>
        /// 사용 가능한 COM 포트 목록 가져오기
        /// </summary>
        public static string[] GetAvailablePorts()
        {
            return System.IO.Ports.SerialPort.GetPortNames();
        }

        /// <summary>
        /// SPMC가 설치되어 있는지 확인
        /// </summary>
        public static bool IsSpmcInstalled()
        {
            try
            {
                var spmcType = Type.GetTypeFromProgID("HHDSPMC.Monitor");
                return spmcType != null;
            }
            catch
            {
                return false;
            }
        }
    }
}
