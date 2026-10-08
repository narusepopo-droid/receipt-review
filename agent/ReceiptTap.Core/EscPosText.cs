using System;
using System.Collections.Generic;
using System.Text;

namespace ReceiptTap.Core
{
    /// <summary>
    /// ESC/POS 원본 바이트 → 사람이 읽을 수 있는 글자 (미리보기·영수증 판별용)
    /// 정식 파싱·렌더링은 서버에서 한다. 여기서는 "영수증이 맞는지", "무슨 내용인지" 확인만.
    /// </summary>
    public static class EscPosText
    {
        private const byte ESC = 0x1B, GS = 0x1D, FS = 0x1C, DLE = 0x10;
        private const int PREVIEW_WIDTH = 42; // 80mm 프린터 기본 42자 (한글 21자)

        private static Encoding _cp949;
        private static Encoding Cp949 => _cp949 ?? (_cp949 = Encoding.GetEncoding(949));

        /// <summary>
        /// GS V(커팅) 명령이 끝나는 위치(다음 바이트 인덱스). 없으면 -1
        /// </summary>
        public static int FindCutEnd(byte[] d)
        {
            for (int i = 0; i + 1 < d.Length; i++)
            {
                if (d[i] != GS || d[i + 1] != (byte)'V') continue;
                if (i + 2 >= d.Length) return -1;          // m 이 아직 안 들어옴
                byte m = d[i + 2];
                if (m == 65 || m == 66 || m == 97 || m == 98 || m == 103 || m == 104)
                {
                    if (i + 3 >= d.Length) return -1;      // n 이 아직 안 들어옴
                    return i + 4;
                }
                return i + 3;
            }
            return -1;
        }

        /// <summary>
        /// 영수증처럼 보이는지 (프린터 명령 + 여러 줄의 글자)
        /// 고객표시기·카드단말기 등 다른 시리얼 장치 데이터를 걸러내기 위함
        /// </summary>
        public static bool LooksLikeReceipt(byte[] d)
        {
            if (d == null || d.Length < 40) return false;

            bool hasCommand = false;
            for (int i = 0; i + 1 < d.Length; i++)
            {
                if (d[i] == ESC && (d[i + 1] == '@' || d[i + 1] == '!' || d[i + 1] == 'a' || d[i + 1] == 'E' || d[i + 1] == 'd'))
                { hasCommand = true; break; }
                if (d[i] == GS && (d[i + 1] == 'V' || d[i + 1] == '!' || d[i + 1] == 'v' || d[i + 1] == 'k'))
                { hasCommand = true; break; }
            }
            if (!hasCommand) return false;

            var text = ToText(d);
            int lines = 0, chars = 0;
            foreach (var line in text.Split('\n'))
            {
                var t = line.Trim();
                if (t.Length > 0) lines++;
                chars += t.Length;
            }
            return lines >= 3 && chars >= 30;
        }

        /// <summary>
        /// 원본 바이트를 글자로 변환 (정렬·이미지·바코드 표시 포함)
        /// </summary>
        public static string ToText(byte[] d)
        {
            var sb = new StringBuilder();
            var lineBytes = new List<byte>();
            int align = 0; // 0 좌, 1 가운데, 2 오른쪽
            int i = 0;

            void EndLine()
            {
                sb.Append(Align(Cp949.GetString(lineBytes.ToArray()), align)).Append('\n');
                lineBytes.Clear();
            }

            void Marker(string m)
            {
                if (lineBytes.Count > 0) EndLine();
                sb.Append(Align(m, 1)).Append('\n');
            }

            int Arg(int k) => i + k < d.Length ? d[i + k] : 0;

            while (i < d.Length)
            {
                byte b = d[i];

                if (b == ESC && i + 1 < d.Length)
                {
                    byte c = d[i + 1];
                    switch ((char)c)
                    {
                        case '@': i += 2; align = 0; break;
                        case 'a': align = Arg(2) % 48 > 2 ? 0 : Arg(2) % 48; i += 3; break;
                        case 'd':
                            if (lineBytes.Count > 0) EndLine();
                            for (int k = 0; k < Math.Min(Arg(2), 5); k++) sb.Append('\n');
                            i += 3; break;
                        case 'J': if (lineBytes.Count > 0) EndLine(); i += 3; break;
                        case '2': i += 2; break;
                        case 'p': i += 5; break;
                        case '*':
                            {
                                int m = Arg(2), n = Arg(3) + Arg(4) * 256;
                                int bytes = (m == 32 || m == 33) ? n * 3 : n;
                                i += 5 + bytes; break;
                            }
                        case 'c': i += 4; break;
                        default: i += 3; break; // ESC ! / E / - / t / G / M / 3 / R / SP 등 인자 1개
                    }
                    continue;
                }

                if (b == GS && i + 1 < d.Length)
                {
                    byte c = d[i + 1];
                    switch ((char)c)
                    {
                        case 'V':
                            {
                                int m = Arg(2);
                                i += (m == 65 || m == 66 || m == 97 || m == 98 || m == 103 || m == 104) ? 4 : 3;
                                if (lineBytes.Count > 0) EndLine();
                                sb.Append(new string('-', PREVIEW_WIDTH)).Append("\n[용지 커팅]\n");
                                break;
                            }
                        case 'v':
                            {
                                // GS v 0 m xL xH yL yH data
                                int x = Arg(4) + Arg(5) * 256, y = Arg(6) + Arg(7) * 256;
                                i += 8 + x * y;
                                Marker("[이미지/로고]");
                                break;
                            }
                        case '(':
                            {
                                int fn = Arg(2), len = Arg(3) + Arg(4) * 256;
                                i += 5 + len;
                                if (fn == 'k') Marker("[QR코드]");
                                break;
                            }
                        case 'k':
                            {
                                int m = Arg(2);
                                if (m <= 6)
                                {
                                    int j = i + 3;
                                    while (j < d.Length && d[j] != 0) j++;
                                    i = j + 1;
                                }
                                else i += 4 + Arg(3);
                                Marker("[바코드]");
                                break;
                            }
                        case 'L': case 'W': case 'P': i += 4; break;
                        case '*': i += 4 + Arg(2) * Arg(3) * 8; break;
                        case '/': i += 3; break;
                        default: i += 3; break; // GS ! / B / h / w / H / f / a / r 등
                    }
                    continue;
                }

                if (b == FS && i + 1 < d.Length)
                {
                    byte c = d[i + 1];
                    if (c == '&' || c == '.') i += 2;
                    else if (c == 'p') { i += 4; Marker("[이미지/로고]"); }
                    else i += 3; // FS ! / FS - / FS W 등
                    continue;
                }

                if (b == DLE && i + 1 < d.Length && (d[i + 1] == 0x04 || d[i + 1] == 0x05)) { i += 3; continue; }

                if (b == 0x0A) { EndLine(); i++; continue; }
                if (b == 0x0D || b == 0x00) { i++; continue; }
                if (b < 0x20) { i++; continue; }

                lineBytes.Add(b);
                i++;
            }

            if (lineBytes.Count > 0) EndLine();
            return sb.ToString();
        }

        /// <summary>표시 폭 (한글 등 2바이트 글자는 2칸)</summary>
        private static int DisplayWidth(string s)
        {
            int w = 0;
            foreach (var ch in s) w += ch > 0x7F ? 2 : 1;
            return w;
        }

        private static string Align(string s, int align)
        {
            if (align == 0) return s;
            int pad = PREVIEW_WIDTH - DisplayWidth(s);
            if (pad <= 0) return s;
            return new string(' ', align == 1 ? pad / 2 : pad) + s;
        }
    }
}
