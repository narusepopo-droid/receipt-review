using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace ReceiptTap.Core
{
    /// <summary>
    /// 영수증 서버 업로더
    /// </summary>
    public class ReceiptUploader
    {
        private readonly string _serverUrl;
        private readonly string _agentKey;

        public ReceiptUploader(string serverUrl, string agentKey)
        {
            _serverUrl = serverUrl.TrimEnd('/');
            _agentKey = agentKey;

            // TLS 1.2 강제
            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;
        }

        /// <summary>
        /// 영수증 업로드
        /// </summary>
        public async Task<UploadResult> UploadAsync(byte[] rawData, DateTime capturedAt, string captureMode, string version)
        {
            try
            {
                var url = $"{_serverUrl}/agent/v1/receipts";
                var request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = "POST";
                request.Headers.Add("X-Agent-Key", _agentKey);

                var boundary = "----" + Guid.NewGuid().ToString("N");
                request.ContentType = "multipart/form-data; boundary=" + boundary;

                using (var stream = await request.GetRequestStreamAsync())
                {
                    // raw_data 파일
                    WriteMultipartFile(stream, boundary, "raw_data", "receipt.bin", "application/octet-stream", rawData);

                    // captured_at
                    WriteMultipartField(stream, boundary, "captured_at", capturedAt.ToString("o"));

                    // capture_mode
                    WriteMultipartField(stream, boundary, "capture_mode", captureMode);

                    // version
                    WriteMultipartField(stream, boundary, "version", version);

                    // 종료
                    var ending = Encoding.UTF8.GetBytes($"\r\n--{boundary}--\r\n");
                    stream.Write(ending, 0, ending.Length);
                }

                using (var response = (HttpWebResponse)await request.GetResponseAsync())
                {
                    using (var reader = new StreamReader(response.GetResponseStream()))
                    {
                        var body = await reader.ReadToEndAsync();
                        return new UploadResult
                        {
                            Success = response.StatusCode == HttpStatusCode.OK || response.StatusCode == HttpStatusCode.Created,
                            StatusCode = (int)response.StatusCode,
                            Response = body
                        };
                    }
                }
            }
            catch (WebException ex)
            {
                var response = ex.Response as HttpWebResponse;
                return new UploadResult
                {
                    Success = false,
                    StatusCode = response != null ? (int)response.StatusCode : 0,
                    Error = ex.Message
                };
            }
            catch (Exception ex)
            {
                return new UploadResult
                {
                    Success = false,
                    Error = ex.Message
                };
            }
        }

        /// <summary>
        /// 하트비트 전송
        /// </summary>
        public async Task<bool> SendHeartbeatAsync(string version, string captureMode, DateTime? lastCaptureAt, int queueLength)
        {
            try
            {
                var url = $"{_serverUrl}/agent/v1/heartbeat";
                var request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = "POST";
                request.Headers.Add("X-Agent-Key", _agentKey);
                request.ContentType = "application/json";

                var payload = JsonConvert.SerializeObject(new
                {
                    version,
                    capture_mode = captureMode,
                    last_capture_at = lastCaptureAt?.ToString("o"),
                    queue_length = queueLength
                });

                var data = Encoding.UTF8.GetBytes(payload);
                using (var stream = await request.GetRequestStreamAsync())
                {
                    stream.Write(data, 0, data.Length);
                }

                using (var response = (HttpWebResponse)await request.GetResponseAsync())
                {
                    return response.StatusCode == HttpStatusCode.OK;
                }
            }
            catch
            {
                return false;
            }
        }

        private void WriteMultipartField(Stream stream, string boundary, string name, string value)
        {
            var header = $"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}";
            var data = Encoding.UTF8.GetBytes(header);
            stream.Write(data, 0, data.Length);
        }

        private void WriteMultipartFile(Stream stream, string boundary, string name, string filename, string contentType, byte[] fileData)
        {
            var header = $"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {contentType}\r\n\r\n";
            var headerBytes = Encoding.UTF8.GetBytes(header);
            stream.Write(headerBytes, 0, headerBytes.Length);
            stream.Write(fileData, 0, fileData.Length);
        }
    }

    public class UploadResult
    {
        public bool Success { get; set; }
        public int StatusCode { get; set; }
        public string Response { get; set; }
        public string Error { get; set; }
    }
}
