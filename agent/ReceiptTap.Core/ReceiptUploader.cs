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
        private volatile string _authToken;

        /// <summary>현재 토큰 (하트비트로 새 토큰을 받으면 바뀜)</summary>
        public string AuthToken
        {
            get => _authToken;
            set => _authToken = value;
        }

        public ReceiptUploader(string serverUrl, string authToken)
        {
            _serverUrl = serverUrl.TrimEnd('/');
            _authToken = authToken;

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
                request.Headers.Add("Authorization", $"Bearer {_authToken}");

                var boundary = "----" + Guid.NewGuid().ToString("N");
                request.ContentType = "multipart/form-data; boundary=" + boundary;

                using (var stream = await request.GetRequestStreamAsync())
                {
                    // 서버 필드 이름: file, captured_at, capture_mode, agent_version
                    WriteMultipartFile(stream, boundary, "file", "receipt.bin", "application/octet-stream", rawData);

                    // captured_at
                    WriteMultipartField(stream, boundary, "captured_at", capturedAt.ToString("o"));

                    // capture_mode
                    WriteMultipartField(stream, boundary, "capture_mode", captureMode);

                    WriteMultipartField(stream, boundary, "agent_version", version);

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
                string body = null;
                try
                {
                    if (response != null)
                        using (var r = new StreamReader(response.GetResponseStream())) body = r.ReadToEnd();
                }
                catch { }
                return new UploadResult
                {
                    Success = false,
                    StatusCode = response != null ? (int)response.StatusCode : 0,
                    Error = ex.Message + (string.IsNullOrEmpty(body) ? "" : " " + body)
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
        /// 하트비트 전송. 서버가 새 토큰을 주면 AuthToken 이 바뀌고 NewToken 에 담김
        /// </summary>
        public async Task<HeartbeatResult> SendHeartbeatAsync(string version, string captureMode, DateTime? lastCaptureAt, int queueLength)
        {
            try
            {
                var url = $"{_serverUrl}/agent/v1/heartbeat";
                var request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = "POST";
                request.Headers.Add("Authorization", $"Bearer {_authToken}");
                request.ContentType = "application/json";

                var payload = JsonConvert.SerializeObject(new
                {
                    version,
                    capture_mode = captureMode,
                    last_capture_at = lastCaptureAt?.ToUniversalTime().ToString("o"),
                    queue_length = queueLength
                });

                var data = Encoding.UTF8.GetBytes(payload);
                using (var stream = await request.GetRequestStreamAsync())
                {
                    stream.Write(data, 0, data.Length);
                }

                using (var response = (HttpWebResponse)await request.GetResponseAsync())
                using (var reader = new StreamReader(response.GetResponseStream()))
                {
                    var body = await reader.ReadToEndAsync();
                    var result = new HeartbeatResult { Success = response.StatusCode == HttpStatusCode.OK, StatusCode = (int)response.StatusCode };
                    try
                    {
                        var json = Newtonsoft.Json.Linq.JObject.Parse(body);
                        if (json["license_ok"] != null) result.LicenseOk = (bool)json["license_ok"];
                        result.LicenseMessage = (string)json["license_message"];
                        var token = (string)json["new_token"];
                        if (!string.IsNullOrEmpty(token))
                        {
                            _authToken = token;
                            result.NewToken = token;
                        }
                    }
                    catch { }
                    return result;
                }
            }
            catch (WebException ex)
            {
                var response = ex.Response as HttpWebResponse;
                return new HeartbeatResult { Success = false, StatusCode = response != null ? (int)response.StatusCode : 0 };
            }
            catch
            {
                return new HeartbeatResult { Success = false };
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

    public class HeartbeatResult
    {
        public bool Success { get; set; }
        public int StatusCode { get; set; }
        public string NewToken { get; set; }
        /// <summary>이용권 상태 (만료·정지면 false). 캡처·업로드는 계속함</summary>
        public bool LicenseOk { get; set; } = true;
        public string LicenseMessage { get; set; }
        /// <summary>토큰이 거부됨 → 다시 로그인 필요</summary>
        public bool Unauthorized => StatusCode == 401;
    }

    public class UploadResult
    {
        public bool Success { get; set; }
        public int StatusCode { get; set; }
        public string Response { get; set; }
        public string Error { get; set; }
    }
}
