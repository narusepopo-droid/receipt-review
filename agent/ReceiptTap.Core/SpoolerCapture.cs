using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Threading;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 윈도우 인쇄 대기열(스풀러) 캡처 — 네트워크(LAN·와이파이) 프린터, 드라이버를 쓰는 USB 프린터용
    /// 포스가 윈도우 프린터로 인쇄하면, 그 인쇄 작업의 데이터(RAW = ESC/POS)를 공식 인쇄 API(ReadPrinter)로 읽는다.
    /// 출력 경로에는 끼어들지 않음.
    /// - 새 작업을 발견하는 즉시 작업 핸들을 열어 붙잡아 두므로, 인쇄가 바로 끝나도 데이터를 읽을 수 있음
    /// - 관리자 권한 불필요, 프린터 설정은 전혀 바꾸지 않음 (0.1초 간격 30장 연속 인쇄 30/30 확인)
    /// </summary>
    public class SpoolerCapture : IReceiptCapture
    {
        public const string SourcePrefix = "PRN:";
        private const int POLL_MS = 50;

        private readonly string _onlyPrinter;      // null 이면 모든 프린터
        private readonly HashSet<string> _seen = new HashSet<string>();
        // 처음 발견한 작업은 바로 핸들을 열어 붙잡아 둠 → 인쇄가 끝나도 데이터를 읽을 때까지 지워지지 않음
        private readonly Dictionary<string, IntPtr> _held = new Dictionary<string, IntPtr>();
        private Timer _timer;
        private int _busy;
        private bool _isCapturing;

        public string CaptureMode => "spooler";
        public bool IsCapturing => _isCapturing;
        public static bool IsAdmin
        {
            get
            {
                try { return new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator); }
                catch { return false; }
            }
        }

        public event EventHandler<ReceiptCapturedEventArgs> ReceiptCaptured;
        public event EventHandler<CaptureErrorEventArgs> ErrorOccurred;
        public event EventHandler<string> LogMessage;

        /// <param name="onlyPrinter">특정 프린터만 (null = 전체)</param>
        public SpoolerCapture(string onlyPrinter = null)
        {
            _onlyPrinter = onlyPrinter;
        }

        public void Start()
        {
            if (_isCapturing) return;
            var printers = ListPrinters();
            Log($"윈도우 프린터 감시 시작: {string.Join(", ", printers.Select(p => p.Name))}");
            // 시작 시점에 이미 있던 작업은 건너뜀
            foreach (var p in printers)
                foreach (var j in EnumJobs(p.Name))
                    _seen.Add(Key(p.Name, j.JobId));
            _isCapturing = true;
            _timer = new Timer(_ => Poll(), null, POLL_MS, POLL_MS);
        }

        private void Poll()
        {
            if (Interlocked.CompareExchange(ref _busy, 1, 0) != 0) return;
            try
            {
                foreach (var p in ListPrinters())
                {
                    if (_onlyPrinter != null && !p.Name.Equals(_onlyPrinter, StringComparison.OrdinalIgnoreCase)) continue;
                    foreach (var j in EnumJobs(p.Name))
                    {
                        var key = Key(p.Name, j.JobId);
                        if (_seen.Contains(key)) continue;

                        if (!IsRawDatatype(j.Datatype))
                        {
                            _seen.Add(key);
                            Log($"{p.Name}: '{j.Datatype}' 형식 인쇄는 읽지 않음 (프린터 언어 직접 출력만 지원)");
                            continue;
                        }
                        if (!_held.ContainsKey(key) && OpenPrinterNoDefaults($"{p.Name},Job {j.JobId}", out var hold, IntPtr.Zero))
                            _held[key] = hold;
                        if ((j.Status & JOB_STATUS_SPOOLING) != 0) continue;     // 아직 쓰는 중 (붙잡아 둔 상태)

                        _seen.Add(key);
                        byte[] data;
                        if (_held.TryGetValue(key, out var hJob))
                        {
                            data = ReadAll(hJob);
                            ClosePrinter(hJob);
                            _held.Remove(key);
                        }
                        else data = ReadJob(p.Name, j.JobId);
                        if (data != null && data.Length > 0)
                        {
                            ReceiptCaptured?.Invoke(this, new ReceiptCapturedEventArgs
                            {
                                RawData = data,
                                CapturedAt = DateTime.Now,
                                Source = SourcePrefix + p.Name
                            });
                        }
                    }
                }
                // 사라진 작업의 붙잡은 핸들 정리
                if (_held.Count > 50)
                {
                    foreach (var kv in _held.ToList()) { ClosePrinter(kv.Value); _held.Remove(kv.Key); }
                }
                if (_seen.Count > 5000) _seen.Clear();
            }
            catch (Exception ex)
            {
                ErrorOccurred?.Invoke(this, new CaptureErrorEventArgs { Exception = ex, Message = "인쇄 대기열 확인 오류: " + ex.Message });
            }
            finally
            {
                Interlocked.Exchange(ref _busy, 0);
            }
        }

        private static bool IsRawDatatype(string dt) =>
            string.IsNullOrEmpty(dt) || dt.StartsWith("RAW", StringComparison.OrdinalIgnoreCase) ||
            dt.Equals("TEXT", StringComparison.OrdinalIgnoreCase);

        private static string Key(string printer, int jobId) => printer + "#" + jobId;

        public void Stop()
        {
            _isCapturing = false;
            _timer?.Dispose();
            _timer = null;
            foreach (var h in _held.Values) ClosePrinter(h);
            _held.Clear();
        }

        public void Dispose() => Stop();

        private void Log(string m) => LogMessage?.Invoke(this, m);

        // ───────────────────────── winspool ─────────────────────────

        public class PrinterInfo
        {
            public string Name;
            public string Port;
            public string Driver;
            public uint Attributes;
            public override string ToString() => $"{Name} ({Port})";
        }

        public class JobInfo
        {
            public int JobId;
            public string Datatype;
            public string Document;
            public uint Status;
        }

        private const uint PRINTER_ENUM_LOCAL = 0x2, PRINTER_ENUM_CONNECTIONS = 0x4;
        private const uint JOB_STATUS_SPOOLING = 0x8, JOB_STATUS_PRINTED = 0x80, JOB_STATUS_COMPLETE = 0x1000;

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct PRINTER_INFO_2
        {
            public string pServerName, pPrinterName, pShareName, pPortName, pDriverName, pComment, pLocation;
            public IntPtr pDevMode;
            public string pSepFile, pPrintProcessor, pDatatype, pParameters;
            public IntPtr pSecurityDescriptor;
            public uint Attributes, Priority, DefaultPriority, StartTime, UntilTime, Status, cJobs, AveragePPM;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct JOB_INFO_1
        {
            public int JobId;
            public string pPrinterName, pMachineName, pUserName, pDocument, pDatatype, pStatus;
            public uint Status, Priority, Position, TotalPages, PagesPrinted;
            public SYSTEMTIME Submitted;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SYSTEMTIME { public ushort Y, M, DW, D, H, Mi, S, Ms; }

        [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool EnumPrinters(uint flags, string name, uint level, IntPtr buf, uint cb, out uint needed, out uint returned);

        [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "OpenPrinterW")]
        private static extern bool OpenPrinterNoDefaults(string name, out IntPtr h, IntPtr defaults);

        [DllImport("winspool.drv", SetLastError = true)]
        private static extern bool ClosePrinter(IntPtr h);

        [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool EnumJobs(IntPtr h, uint first, uint count, uint level, IntPtr buf, uint cb, out uint needed, out uint returned);

        [DllImport("winspool.drv", SetLastError = true)]
        private static extern bool ReadPrinter(IntPtr h, byte[] buf, int cb, out int read);


        public static List<PrinterInfo> ListPrinters()
        {
            var list = new List<PrinterInfo>();
            EnumPrinters(PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS, null, 2, IntPtr.Zero, 0, out var needed, out _);
            if (needed == 0) return list;
            var buf = Marshal.AllocHGlobal((int)needed);
            try
            {
                if (!EnumPrinters(PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS, null, 2, buf, needed, out _, out var count))
                    return list;
                var size = Marshal.SizeOf(typeof(PRINTER_INFO_2));
                for (int i = 0; i < count; i++)
                {
                    var pi = (PRINTER_INFO_2)Marshal.PtrToStructure(buf + i * size, typeof(PRINTER_INFO_2));
                    list.Add(new PrinterInfo { Name = pi.pPrinterName, Port = pi.pPortName, Driver = pi.pDriverName, Attributes = pi.Attributes });
                }
            }
            finally { Marshal.FreeHGlobal(buf); }
            return list;
        }

        public static List<JobInfo> EnumJobs(string printer)
        {
            var list = new List<JobInfo>();
            if (!OpenPrinterNoDefaults(printer, out var h, IntPtr.Zero)) return list;
            try
            {
                EnumJobs(h, 0, 255, 1, IntPtr.Zero, 0, out var needed, out _);
                if (needed == 0) return list;
                var buf = Marshal.AllocHGlobal((int)needed);
                try
                {
                    if (!EnumJobs(h, 0, 255, 1, buf, needed, out _, out var count)) return list;
                    var size = Marshal.SizeOf(typeof(JOB_INFO_1));
                    for (int i = 0; i < count; i++)
                    {
                        var j = (JOB_INFO_1)Marshal.PtrToStructure(buf + i * size, typeof(JOB_INFO_1));
                        list.Add(new JobInfo { JobId = j.JobId, Datatype = j.pDatatype, Document = j.pDocument, Status = j.Status });
                    }
                }
                finally { Marshal.FreeHGlobal(buf); }
            }
            finally { ClosePrinter(h); }
            return list;
        }

        /// <summary>인쇄 작업 데이터 읽기 ("프린터이름,Job 번호" 로 열면 스풀 데이터를 그대로 읽을 수 있음)</summary>
        public static byte[] ReadJob(string printer, int jobId)
        {
            if (!OpenPrinterNoDefaults($"{printer},Job {jobId}", out var h, IntPtr.Zero)) return null;
            try { return ReadAll(h); }
            finally { ClosePrinter(h); }
        }

        private static byte[] ReadAll(IntPtr h)
        {
            using (var ms = new MemoryStream())
            {
                var buf = new byte[8192];
                while (ReadPrinter(h, buf, buf.Length, out var read) && read > 0)
                {
                    ms.Write(buf, 0, read);
                    if (ms.Length > 4 * 1024 * 1024) break;
                }
                return ms.ToArray();
            }
        }
    }
}
