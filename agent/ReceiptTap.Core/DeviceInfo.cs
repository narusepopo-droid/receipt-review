using System;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 이 PC 고유번호 (매장당 포스 PC 1대 제한용).
    /// 윈도우 MachineGuid 를 해시해서 보냄 → 원래 값은 서버에 남지 않음. 윈도우를 새로 설치하면 바뀜(=PC 변경).
    /// </summary>
    public static class DeviceInfo
    {
        private static string _id;

        public static string DeviceId
        {
            get
            {
                if (_id != null) return _id;
                var raw = ReadMachineGuid();
                if (string.IsNullOrEmpty(raw)) raw = Environment.MachineName + "|" + Environment.UserDomainName;
                using (var sha = SHA256.Create())
                {
                    var h = sha.ComputeHash(Encoding.UTF8.GetBytes("receipttap:" + raw));
                    _id = "RT-" + BitConverter.ToString(h, 0, 16).Replace("-", "");
                }
                return _id;
            }
        }

        public static string DeviceName => Environment.MachineName;

        private static string ReadMachineGuid()
        {
            try
            {
                // 32비트 프로그램이어도 64비트 레지스트리 값을 읽어야 같은 값이 나옴
                using (var hk = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
                using (var k = hk.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography"))
                    return k?.GetValue("MachineGuid") as string;
            }
            catch
            {
                return null;
            }
        }
    }
}
