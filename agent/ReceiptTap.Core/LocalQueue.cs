using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 로컬 업로드 큐
    /// 업로드 실패 시 파일로 저장, 재시도
    /// </summary>
    public class LocalQueue
    {
        private readonly string _queuePath;
        private readonly TimeSpan _maxAge = TimeSpan.FromHours(48);

        public LocalQueue(string queuePath)
        {
            _queuePath = queuePath;
            Directory.CreateDirectory(_queuePath);
        }

        /// <summary>
        /// 큐에 항목 추가
        /// </summary>
        public void Enqueue(byte[] rawData, DateTime capturedAt, string captureMode)
        {
            var id = Guid.NewGuid().ToString("N");
            var item = new QueueItem
            {
                Id = id,
                CapturedAt = capturedAt,
                CaptureMode = captureMode,
                EnqueuedAt = DateTime.Now
            };

            // 메타데이터 저장
            var metaPath = Path.Combine(_queuePath, $"{id}.json");
            File.WriteAllText(metaPath, JsonConvert.SerializeObject(item));

            // 원본 데이터 저장
            var dataPath = Path.Combine(_queuePath, $"{id}.bin");
            File.WriteAllBytes(dataPath, rawData);
        }

        /// <summary>
        /// 대기 중인 항목 목록
        /// </summary>
        public IEnumerable<QueueItem> GetPendingItems()
        {
            var items = new List<QueueItem>();
            var now = DateTime.Now;

            foreach (var metaFile in Directory.GetFiles(_queuePath, "*.json"))
            {
                try
                {
                    var json = File.ReadAllText(metaFile);
                    var item = JsonConvert.DeserializeObject<QueueItem>(json);

                    // 만료된 항목 삭제
                    if (now - item.EnqueuedAt > _maxAge)
                    {
                        Remove(item.Id);
                        continue;
                    }

                    item.DataPath = Path.Combine(_queuePath, $"{item.Id}.bin");
                    if (File.Exists(item.DataPath))
                    {
                        items.Add(item);
                    }
                }
                catch
                {
                    // 손상된 파일 무시
                }
            }

            return items.OrderBy(i => i.EnqueuedAt);
        }

        /// <summary>
        /// 항목 데이터 로드
        /// </summary>
        public byte[] LoadData(QueueItem item)
        {
            return File.ReadAllBytes(item.DataPath);
        }

        /// <summary>
        /// 항목 삭제 (업로드 성공 시)
        /// </summary>
        public void Remove(string id)
        {
            var metaPath = Path.Combine(_queuePath, $"{id}.json");
            var dataPath = Path.Combine(_queuePath, $"{id}.bin");

            if (File.Exists(metaPath)) File.Delete(metaPath);
            if (File.Exists(dataPath)) File.Delete(dataPath);
        }

        /// <summary>
        /// 큐 길이
        /// </summary>
        public int Count => Directory.GetFiles(_queuePath, "*.json").Length;
    }

    public class QueueItem
    {
        public string Id { get; set; }
        public DateTime CapturedAt { get; set; }
        public string CaptureMode { get; set; }
        public DateTime EnqueuedAt { get; set; }

        [JsonIgnore]
        public string DataPath { get; set; }
    }
}
