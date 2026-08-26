using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace KahnRuntime
{
    internal sealed class ShadowDecisionLog : IDisposable
    {
        private const int QueueCapacity = 100000;

        private readonly ConcurrentQueue<string> _queue = new();
        private readonly AutoResetEvent _signal = new(false);
        private readonly Thread _thread;
        private readonly string _path;
        private readonly Action<string> _errorSink;
        private readonly long _startedTicks = Stopwatch.GetTimestamp();
        private volatile bool _stopping;
        private int _queued;
        private long _dropped;

        public ShadowDecisionLog(string path, Action<string> errorSink = null)
        {
            _path = Environment.ExpandEnvironmentVariables(path ?? string.Empty);
            if (string.IsNullOrWhiteSpace(_path))
                throw new ArgumentException("Decision log path is empty.", nameof(path));
            _errorSink = errorSink;
            _thread = new Thread(WriteLoop)
            {
                IsBackground = true,
                Name = "KahnRuntime.DecisionLog",
            };
            _thread.Start();
        }

        public long DroppedCount => Interlocked.Read(ref _dropped);

        public void Write(string eventType, params (string Key, object Value)[] fields)
        {
            if (_stopping || string.IsNullOrWhiteSpace(eventType))
                return;

            Dictionary<string, object> payload = new(StringComparer.Ordinal)
            {
                ["ts_utc"] = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                ["mono_us"] = ElapsedMicroseconds(),
                ["event"] = eventType,
            };
            if (fields != null)
            {
                foreach ((string key, object value) in fields)
                {
                    if (!string.IsNullOrWhiteSpace(key))
                        payload[JsonNamingPolicy.SnakeCaseLower.ConvertName(key)] = NormalizeValue(value);
                }
            }

            string line;
            try
            {
                line = JsonSerializer.Serialize(payload, SerializerOptions);
            }
            catch (Exception ex)
            {
                _errorSink?.Invoke($"Decision serialization failed: {ex.Message}");
                return;
            }

            if (Interlocked.Increment(ref _queued) > QueueCapacity)
            {
                Interlocked.Decrement(ref _queued);
                Interlocked.Increment(ref _dropped);
                return;
            }
            _queue.Enqueue(line);
            _signal.Set();
        }

        public void Dispose()
        {
            if (_stopping)
                return;
            _stopping = true;
            _signal.Set();
            try { _thread.Join(TimeSpan.FromSeconds(5)); } catch { }
            _signal.Dispose();
        }

        private long ElapsedMicroseconds()
            => (long)((Stopwatch.GetTimestamp() - _startedTicks)
                * 1_000_000.0 / Stopwatch.Frequency);

        private void WriteLoop()
        {
            try
            {
                string directory = Path.GetDirectoryName(_path);
                if (!string.IsNullOrWhiteSpace(directory))
                    Directory.CreateDirectory(directory);
                using FileStream stream = new(
                    _path,
                    FileMode.Append,
                    FileAccess.Write,
                    FileShare.ReadWrite,
                    64 * 1024,
                    FileOptions.SequentialScan);
                using StreamWriter writer = new(stream, new UTF8Encoding(false))
                {
                    AutoFlush = true,
                };

                while (!_stopping || !_queue.IsEmpty)
                {
                    while (_queue.TryDequeue(out string line))
                    {
                        Interlocked.Decrement(ref _queued);
                        writer.WriteLine(line);
                    }
                    if (!_stopping)
                        _signal.WaitOne(1000);
                }
            }
            catch (Exception ex)
            {
                _errorSink?.Invoke($"Decision log writer failed: {ex.Message}");
            }
        }

        private static object NormalizeValue(object value)
            => value switch
            {
                double number when !double.IsFinite(number) => null,
                float number when !float.IsFinite(number) => null,
                Enum item => item.ToString(),
                PriceRange range => new
                {
                    range.Lower,
                    range.Upper,
                },
                _ => value,
            };

        private static readonly JsonSerializerOptions SerializerOptions = new()
        {
            WriteIndented = false,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        };
    }
}
