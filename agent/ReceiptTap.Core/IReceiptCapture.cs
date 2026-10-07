using System;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 영수증 캡처 인터페이스
    /// 각 캡처 방식(시리얼/네트워크)이 이 인터페이스를 구현
    /// </summary>
    public interface IReceiptCapture : IDisposable
    {
        /// <summary>
        /// 캡처 방식 이름
        /// </summary>
        string CaptureMode { get; }

        /// <summary>
        /// 캡처 시작
        /// </summary>
        void Start();

        /// <summary>
        /// 캡처 중지
        /// </summary>
        void Stop();

        /// <summary>
        /// 현재 캡처 중인지
        /// </summary>
        bool IsCapturing { get; }

        /// <summary>
        /// 영수증 캡처 이벤트
        /// </summary>
        event EventHandler<ReceiptCapturedEventArgs> ReceiptCaptured;

        /// <summary>
        /// 에러 발생 이벤트
        /// </summary>
        event EventHandler<CaptureErrorEventArgs> ErrorOccurred;
    }

    /// <summary>
    /// 영수증 캡처 이벤트 인자
    /// </summary>
    public class ReceiptCapturedEventArgs : EventArgs
    {
        public byte[] RawData { get; set; }
        public DateTime CapturedAt { get; set; }
        public string Source { get; set; }
    }

    /// <summary>
    /// 캡처 에러 이벤트 인자
    /// </summary>
    public class CaptureErrorEventArgs : EventArgs
    {
        public Exception Exception { get; set; }
        public string Message { get; set; }
    }
}
