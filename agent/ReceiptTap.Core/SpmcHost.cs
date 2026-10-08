using System;
using System.Collections.Generic;
using System.IO;
using hhdspmcLib;

namespace ReceiptTap.Core
{
    /// <summary>
    /// SPMC 진입점 (프로그램 전체에서 1개만 사용)
    /// 올바른 순서: SerialMonitorClass 생성 → 라이선스 등록 → CreateMonitor → Connect(device)
    /// (HHD 공식 C# 예제, 카솔 PosAssist와 같은 방식)
    /// </summary>
    public static class SpmcHost
    {
        private static readonly object _lock = new object();
        private static SerialMonitor _sm;

        public const string LicenseFileName = "SPMC_License.spmclic";

        public static bool LicenseInstalled { get; private set; }
        public static string LicenseError { get; private set; }

        public static SerialMonitor Get()
        {
            lock (_lock)
            {
                if (_sm == null)
                {
                    try
                    {
                        _sm = new SerialMonitorClass();
                    }
                    catch (Exception ex)
                    {
                        throw new InvalidOperationException(
                            "SPMC가 설치(등록)되어 있지 않습니다. 프로그램을 다시 설치해 주세요. (" + ex.Message + ")", ex);
                    }
                    InstallLicense();
                }
                return _sm;
            }
        }

        private static void InstallLicense()
        {
            var path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, LicenseFileName);
            if (!File.Exists(path))
            {
                LicenseError = "라이선스 파일 없음: " + path;
                return;
            }
            try
            {
                _sm.InstallLicense(path);
                LicenseInstalled = true;
                LicenseError = null;
            }
            catch (Exception ex)
            {
                LicenseError = "라이선스 등록 실패: " + ex.Message;
            }
        }

        /// <summary>
        /// SPMC가 보는 시리얼 장치 목록
        /// </summary>
        public static List<SpmcPortInfo> GetPorts()
        {
            var list = new List<SpmcPortInfo>();
            foreach (Device d in Get().Devices)
            {
                list.Add(new SpmcPortInfo
                {
                    Name = d.Name ?? "",
                    Port = d.Port ?? "",
                    Present = d.Present,
                    OpenedBy = SafeOpenedBy(d)
                });
            }
            return list;
        }

        private static string SafeOpenedBy(Device d)
        {
            try { return d.OpenedBy ?? ""; } catch { return ""; }
        }

        /// <summary>
        /// 포트 이름(COM3 등)으로 장치 찾기. 포트 이름이 없는 장치는 장치 이름으로 비교
        /// </summary>
        public static Device FindDevice(string port)
        {
            if (string.IsNullOrEmpty(port)) return null;
            foreach (Device d in Get().Devices)
            {
                var p = d.Port ?? "";
                if (p.Equals(port, StringComparison.OrdinalIgnoreCase)) return d;
                if (p.Length == 0 && (d.Name ?? "").Equals(port, StringComparison.OrdinalIgnoreCase)) return d;
            }
            return null;
        }
    }

    public class SpmcPortInfo
    {
        public string Name { get; set; }
        public string Port { get; set; }
        public bool Present { get; set; }
        /// <summary>현재 이 포트를 열고 있는 프로그램 (포스 프로그램이면 프린터 포트일 가능성 높음)</summary>
        public string OpenedBy { get; set; }

        /// <summary>연결에 쓰는 키 (포트 이름, 없으면 장치 이름)</summary>
        public string Key => string.IsNullOrEmpty(Port) ? Name : Port;

        public override string ToString()
        {
            var s = string.IsNullOrEmpty(Port) ? Name : $"{Port} - {Name}";
            if (!string.IsNullOrEmpty(OpenedBy)) s += $"  [사용 중: {OpenedBy}]";
            if (!Present) s += "  (연결 안 됨)";
            return s;
        }
    }
}
