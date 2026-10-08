using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;

namespace ReceiptTap.App
{
    /// <summary>
    /// 초록 N 마크 아이콘 (작업표시줄에서 잘 보이도록). 오른쪽 아래 점 색으로 상태 표시
    /// </summary>
    public static class AppIcons
    {
        public static readonly Color Brand = Color.FromArgb(3, 199, 90);   // #03C75A
        private static readonly Dictionary<string, Icon> _cache = new Dictionary<string, Icon>();

        public static Color StatusColor(AgentStatus s)
        {
            switch (s)
            {
                case AgentStatus.Connected: return Color.FromArgb(0, 200, 83);
                case AgentStatus.Searching: return Color.FromArgb(41, 121, 255);
                case AgentStatus.Disconnected: return Color.FromArgb(255, 179, 0);
                case AgentStatus.CaptureError: return Color.FromArgb(229, 57, 53);
                default: return Color.FromArgb(158, 158, 158);
            }
        }

        /// <summary>상태 점 없는 기본 아이콘 (창 아이콘용)</summary>
        public static Icon App => Get(null);

        public static Icon ForStatus(AgentStatus s) => Get(s);

        private static Icon Get(AgentStatus? status)
        {
            var key = status?.ToString() ?? "app";
            lock (_cache)
            {
                if (_cache.TryGetValue(key, out var icon)) return icon;
                using (var bmp = Draw(32, status))
                    icon = Icon.FromHandle(bmp.GetHicon());
                _cache[key] = icon;
                return icon;
            }
        }

        public static Bitmap Draw(int size, AgentStatus? status)
        {
            var bmp = new Bitmap(size, size);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                g.Clear(Color.Transparent);

                float r = size * 0.22f;
                using (var path = RoundRect(new RectangleF(0, 0, size - 1, size - 1), r))
                using (var brush = new SolidBrush(Brand))
                    g.FillPath(brush, path);

                using (var font = new Font("Arial", size * 0.62f, FontStyle.Bold, GraphicsUnit.Pixel))
                using (var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                    g.DrawString("N", font, Brushes.White, new RectangleF(0, size * 0.03f, size, size), sf);

                if (status.HasValue)
                {
                    float d = size * 0.42f;
                    var rect = new RectangleF(size - d - 0.5f, size - d - 0.5f, d, d);
                    using (var b = new SolidBrush(StatusColor(status.Value)))
                        g.FillEllipse(b, rect);
                    using (var pen = new Pen(Color.White, Math.Max(1.5f, size / 16f)))
                        g.DrawEllipse(pen, rect);
                }
            }
            return bmp;
        }

        private static GraphicsPath RoundRect(RectangleF rc, float r)
        {
            var p = new GraphicsPath();
            float d = r * 2;
            p.AddArc(rc.X, rc.Y, d, d, 180, 90);
            p.AddArc(rc.Right - d, rc.Y, d, d, 270, 90);
            p.AddArc(rc.Right - d, rc.Bottom - d, d, d, 0, 90);
            p.AddArc(rc.X, rc.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }
    }
}
