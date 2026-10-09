using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace ReceiptTap.App
{
    public class StoreChoice
    {
        public int id { get; set; }
        public string name { get; set; }
        public string state { get; set; }
        public string pc { get; set; }

        public override string ToString()
        {
            var st = state == "active" ? "" : state == "grace" ? "  (유예 중)" : state == "pending" ? "  (승인·결제 대기)" : "  (사용 불가)";
            var pcText = string.IsNullOrEmpty(pc) ? "" : $"  · PC: {pc}";
            return name + st + pcText;
        }
    }

    /// <summary>계정에 매장이 여러 개일 때 이 포스에서 쓸 매장 고르기</summary>
    public static class StorePicker
    {
        public static int? Pick(IWin32Window owner, List<StoreChoice> stores)
        {
            using (var f = new Form
            {
                Text = "매장 선택",
                Size = new Size(420, 340),
                FormBorderStyle = FormBorderStyle.FixedDialog,
                StartPosition = FormStartPosition.CenterParent,
                MaximizeBox = false,
                MinimizeBox = false,
                BackColor = Color.White
            })
            {
                var label = new Label
                {
                    Text = "이 포스 PC에서 사용할 매장을 선택하세요.\n매장 하나당 포스 PC 1대에서 사용할 수 있어요.",
                    Location = new Point(16, 14),
                    Size = new Size(380, 40),
                    Font = new Font("맑은 고딕", 9)
                };
                var list = new ListBox
                {
                    Location = new Point(16, 60),
                    Size = new Size(372, 180),
                    Font = new Font("맑은 고딕", 11)
                };
                foreach (var s in stores) list.Items.Add(s);
                list.SelectedIndex = 0;
                var ok = new Button
                {
                    Text = "선택",
                    Location = new Point(16, 250),
                    Size = new Size(372, 38),
                    BackColor = Color.FromArgb(3, 199, 90),
                    ForeColor = Color.White,
                    FlatStyle = FlatStyle.Flat,
                    Font = new Font("맑은 고딕", 10, FontStyle.Bold),
                    DialogResult = DialogResult.OK
                };
                ok.FlatAppearance.BorderSize = 0;
                list.DoubleClick += (s, e) => { f.DialogResult = DialogResult.OK; f.Close(); };
                f.Controls.Add(label);
                f.Controls.Add(list);
                f.Controls.Add(ok);
                f.AcceptButton = ok;
                if (f.ShowDialog(owner) == DialogResult.OK && list.SelectedItem is StoreChoice c) return c.id;
                return null;
            }
        }
    }
}
