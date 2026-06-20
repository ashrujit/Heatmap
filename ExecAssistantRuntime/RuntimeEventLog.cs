using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace ExecAssistantRuntime
{
    internal sealed class RuntimeEventLog : IDisposable
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

        public RuntimeEventLog(string path, Action<string> errorSink = null)
        {
            _path = Environment.ExpandEnvironmentVariables(path ?? string.Empty);
            if (string.IsNullOrWhiteSpace(_path))
                throw new ArgumentException("Event log path is empty.", nameof(path));
            _errorSink = errorSink;
            string directory = Path.GetDirectoryName(_path);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);
            _thread = new Thread(WriteLoop)
            {
                IsBackground = true,
                Name = "ExecAssistantRuntime.EventLog",
            };
            _thread.Start();
        }

        public long DroppedCount => Interlocked.Read(ref _dropped);

        public void Write(string eventType, params (string Key, object Value)[] fields)
        {
            if (_stopping || string.IsNullOrWhiteSpace(eventType))
                return;

            var payload = new Dictionary<string, object>(StringComparer.Ordinal)
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
                        payload[key] = value;
                }
            }

            string line;
            try
            {
                line = JsonSerializer.Serialize(payload, SerializerOptions);
            }
            catch (Exception ex)
            {
                _errorSink?.Invoke($"Event serialization failed: {ex.Message}");
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
                using var stream = new FileStream(
                    _path,
                    FileMode.Append,
                    FileAccess.Write,
                    FileShare.ReadWrite,
                    64 * 1024,
                    FileOptions.SequentialScan);
                using var writer = new StreamWriter(stream, new UTF8Encoding(false))
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
                _errorSink?.Invoke($"Event log writer failed: {ex.Message}");
            }
        }

        private static readonly JsonSerializerOptions SerializerOptions = new()
        {
            WriteIndented = false,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        };
    }
}
