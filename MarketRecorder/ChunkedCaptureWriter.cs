using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Parquet;
using Parquet.Data;
using Parquet.Schema;
using TradingPlatform.BusinessLayer;

namespace MarketRecorder
{
    internal sealed class ChunkedCaptureWriter : IDisposable
    {
        private const string Version = "0.1.0";

        private readonly string _root;
        private readonly string _symbolKey;
        private readonly int _levelsPerSide;
        private readonly int _chunkSeconds;
        private readonly int _flushSeconds;
        private readonly int _retentionDays;
        private readonly bool _writeTicks;
        private readonly bool _writeSnapshots;
        private readonly TimeZoneInfo _nyZone;
        private readonly ParquetSchema _tickSchema;
        private readonly ParquetSchema _snapshotSchema;
        private readonly ConcurrentQueue<TickRow> _tickQueue = new();
        private readonly ConcurrentQueue<SnapshotRow> _snapshotQueue = new();
        private readonly Dictionary<ChunkKey, List<TickRow>> _tickChunks = new();
        private readonly Dictionary<ChunkKey, List<SnapshotRow>> _snapshotChunks = new();
        private readonly object _bufferGate = new();
        private readonly object _statusGate = new();
        private readonly JsonSerializerOptions _jsonOptions = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };

        private CancellationTokenSource _cts;
        private Task _writerTask;
        private bool _disposed;

        private long _ticksEnqueued;
        private long _ticksWritten;
        private long _tickFiles;
        private long _snapshotsEnqueued;
        private long _snapshotsWritten;
        private long _snapshotFiles;
        private long _snapshotSkips;
        private long _tickWriteFailures;
        private long _snapshotWriteFailures;
        private int _pendingTickRows;
        private int _pendingSnapshotRows;
        private long _lastTickUs;
        private long _lastSnapshotUs;
        private string _lastTickFile = "";
        private string _lastSnapshotFile = "";
        private string _lastError = "";
        private string _bookState = "starting";
        private DateTime _lastStatusUtc = DateTime.MinValue;

        public ChunkedCaptureWriter(
            string root,
            string symbol,
            int levelsPerSide,
            int chunkSeconds,
            int flushSeconds,
            int retentionDays,
            bool writeTicks,
            bool writeSnapshots)
        {
            _root = string.IsNullOrWhiteSpace(root)
                ? @"C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures"
                : root;
            _symbolKey = SanitizeForPath(string.IsNullOrWhiteSpace(symbol) ? "UNKNOWN" : symbol);
            _levelsPerSide = Math.Max(30, Math.Min(200, levelsPerSide));
            _chunkSeconds = Math.Max(60, Math.Min(1800, chunkSeconds));
            _flushSeconds = Math.Max(1, Math.Min(60, flushSeconds));
            _retentionDays = Math.Max(1, retentionDays);
            _writeTicks = writeTicks;
            _writeSnapshots = writeSnapshots;
            try { _nyZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch { _nyZone = TimeZoneInfo.Local; }
            _tickSchema = BuildTickSchema();
            _snapshotSchema = BuildSnapshotSchema(_levelsPerSide);
        }

        public int LevelsPerSide => _levelsPerSide;
        public string StatusPath => Path.Combine(SymbolRoot, "status.json");
        private string SymbolRoot => Path.Combine(_root, _symbolKey);

        public void Start()
        {
            Directory.CreateDirectory(SymbolRoot);
            try { CleanupOldDayDirs(); } catch (Exception ex) { RecordError("cleanup", ex); }
            _cts = new CancellationTokenSource();
            _writerTask = Task.Run(() => WriterLoop(_cts.Token));
            WriteStatusFile();
        }

        public void EnqueueTick(DateTime timeUtc, double price, double size, AggressorFlag flag)
        {
            if (!_writeTicks || _disposed) return;
            if (!double.IsFinite(price) || price <= 0) return;
            if (!double.IsFinite(size) || size <= 0) return;

            var utc = timeUtc == default ? DateTime.UtcNow : timeUtc.ToUniversalTime();
            int sign = flag == AggressorFlag.Buy ? 1 : (flag == AggressorFlag.Sell ? -1 : 0);
            long tsUs = ToMicros(utc);
            _tickQueue.Enqueue(new TickRow
            {
                TimestampUs = tsUs,
                Price = price,
                Size = size,
                AggressorSign = sign,
            });
            Interlocked.Increment(ref _ticksEnqueued);
            Interlocked.Exchange(ref _lastTickUs, tsUs);
        }

        public void EnqueueSnapshot(DateTime timeUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            if (!_writeSnapshots || _disposed) return;
            var row = BuildSnapshotRow(timeUtc.ToUniversalTime(), dom, tickSize);
            if (row == null) return;
            _snapshotQueue.Enqueue(row);
            Interlocked.Increment(ref _snapshotsEnqueued);
            Interlocked.Exchange(ref _lastSnapshotUs, row.TimestampUs);
        }

        public void NoteSnapshotSkipped(string reason)
        {
            Interlocked.Increment(ref _snapshotSkips);
            lock (_statusGate)
                _bookState = string.IsNullOrWhiteSpace(reason) ? "snapshot skipped" : reason;
        }

        public void SetBookState(string state)
        {
            lock (_statusGate)
                _bookState = string.IsNullOrWhiteSpace(state) ? "unknown" : state;
        }

        public RecorderStatusSnapshot GetStatus()
        {
            lock (_statusGate)
            {
                return new RecorderStatusSnapshot
                {
                    Version = Version,
                    Symbol = _symbolKey,
                    Root = _root,
                    LevelsPerSide = _levelsPerSide,
                    ChunkSeconds = _chunkSeconds,
                    TicksEnabled = _writeTicks,
                    SnapshotsEnabled = _writeSnapshots,
                    TickRowsEnqueued = Interlocked.Read(ref _ticksEnqueued),
                    TickRowsWritten = Interlocked.Read(ref _ticksWritten),
                    TickFiles = Interlocked.Read(ref _tickFiles),
                    SnapshotRowsEnqueued = Interlocked.Read(ref _snapshotsEnqueued),
                    SnapshotRowsWritten = Interlocked.Read(ref _snapshotsWritten),
                    SnapshotFiles = Interlocked.Read(ref _snapshotFiles),
                    SnapshotSkips = Interlocked.Read(ref _snapshotSkips),
                    TickQueueRows = _tickQueue.Count + _pendingTickRows,
                    SnapshotQueueRows = _snapshotQueue.Count + _pendingSnapshotRows,
                    LastTickUtc = IsoOrEmpty(Interlocked.Read(ref _lastTickUs)),
                    LastSnapshotUtc = IsoOrEmpty(Interlocked.Read(ref _lastSnapshotUs)),
                    LastTickFile = _lastTickFile,
                    LastSnapshotFile = _lastSnapshotFile,
                    TickWriteFailures = Interlocked.Read(ref _tickWriteFailures),
                    SnapshotWriteFailures = Interlocked.Read(ref _snapshotWriteFailures),
                    BookState = _bookState,
                    LastError = _lastError,
                    LastStatusUtc = _lastStatusUtc == DateTime.MinValue ? "" : _lastStatusUtc.ToString("O"),
                };
            }
        }

        public void Dispose()
        {
            _disposed = true;
            try { _cts?.Cancel(); } catch { }
            try { _writerTask?.Wait(TimeSpan.FromSeconds(30)); } catch { }
            try { _cts?.Dispose(); } catch { }
            _cts = null;
            _writerTask = null;
        }

        private async Task WriterLoop(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try { await Task.Delay(TimeSpan.FromSeconds(_flushSeconds), ct); }
                catch (OperationCanceledException) { break; }
                await DrainAndWrite(force: false);
                WriteStatusFile();
            }
            await DrainAndWrite(force: true);
            WriteStatusFile();
        }

        private async Task DrainAndWrite(bool force)
        {
            DrainQueuesIntoBuffers();
            long nowUs = ToMicros(DateTime.UtcNow);
            var tickReady = TakeReady(_tickChunks, nowUs, force);
            var snapshotReady = TakeReady(_snapshotChunks, nowUs, force);

            foreach (var item in tickReady)
            {
                if (!await TryWriteTickChunk(item.Key, item.Value, force))
                    RestoreChunk(_tickChunks, item.Key, item.Value);
            }
            foreach (var item in snapshotReady)
            {
                if (!await TryWriteSnapshotChunk(item.Key, item.Value, force))
                    RestoreChunk(_snapshotChunks, item.Key, item.Value);
            }
            UpdatePendingCounts();
        }

        private void DrainQueuesIntoBuffers()
        {
            var ticks = new List<TickRow>();
            while (_tickQueue.TryDequeue(out var tick))
                ticks.Add(tick);

            var snaps = new List<SnapshotRow>();
            while (_snapshotQueue.TryDequeue(out var snap))
                snaps.Add(snap);

            if (ticks.Count == 0 && snaps.Count == 0) return;

            lock (_bufferGate)
            {
                foreach (var row in ticks)
                    AddToChunk(_tickChunks, ChunkFor(row.TimestampUs), row);
                foreach (var row in snaps)
                    AddToChunk(_snapshotChunks, ChunkFor(row.TimestampUs), row);
                UpdatePendingCountsNoLock();
            }
        }

        private List<KeyValuePair<ChunkKey, List<T>>> TakeReady<T>(
            Dictionary<ChunkKey, List<T>> chunks,
            long nowUs,
            bool force)
        {
            lock (_bufferGate)
            {
                var keys = chunks.Keys
                    .Where(k => force || k.EndUs <= nowUs)
                    .OrderBy(k => k.StartUs)
                    .ToArray();
                var ready = new List<KeyValuePair<ChunkKey, List<T>>>(keys.Length);
                foreach (var key in keys)
                {
                    ready.Add(new KeyValuePair<ChunkKey, List<T>>(key, chunks[key]));
                    chunks.Remove(key);
                }
                UpdatePendingCountsNoLock();
                return ready;
            }
        }

        private void RestoreChunk<T>(Dictionary<ChunkKey, List<T>> chunks, ChunkKey key, List<T> rows)
        {
            lock (_bufferGate)
            {
                if (!chunks.TryGetValue(key, out var existing))
                {
                    chunks[key] = rows;
                }
                else
                {
                    existing.AddRange(rows);
                    existing.Sort((a, b) => TimestampOf(a).CompareTo(TimestampOf(b)));
                }
                UpdatePendingCountsNoLock();
            }
        }

        private async Task<bool> TryWriteTickChunk(ChunkKey key, List<TickRow> rows, bool finalFlush)
        {
            if (rows.Count == 0) return true;
            rows.Sort((a, b) => a.TimestampUs.CompareTo(b.TimestampUs));
            try
            {
                string finalPath = NextChunkPath(key, "ticks", "ticks");
                string tmpPath = finalPath + ".tmp-" + Guid.NewGuid().ToString("N");
                Directory.CreateDirectory(Path.GetDirectoryName(finalPath));
                await WriteTickFile(tmpPath, rows);
                await ValidateParquet(tmpPath, rows.Count);
                File.Move(tmpPath, finalPath, overwrite: false);
                var record = ManifestRecord.ForChunk("ticks", finalPath, key, rows.Count, rows[0].TimestampUs, rows[^1].TimestampUs, _levelsPerSide, finalFlush);
                AppendManifest(key.Day, record);
                Interlocked.Add(ref _ticksWritten, rows.Count);
                Interlocked.Increment(ref _tickFiles);
                lock (_statusGate)
                    _lastTickFile = finalPath;
                return true;
            }
            catch (Exception ex)
            {
                Interlocked.Increment(ref _tickWriteFailures);
                RecordError("write ticks", ex);
                return false;
            }
        }

        private async Task<bool> TryWriteSnapshotChunk(ChunkKey key, List<SnapshotRow> rows, bool finalFlush)
        {
            if (rows.Count == 0) return true;
            rows.Sort((a, b) => a.TimestampUs.CompareTo(b.TimestampUs));
            try
            {
                string finalPath = NextChunkPath(key, "snapshots", "snapshots");
                string tmpPath = finalPath + ".tmp-" + Guid.NewGuid().ToString("N");
                Directory.CreateDirectory(Path.GetDirectoryName(finalPath));
                await WriteSnapshotFile(tmpPath, rows);
                await ValidateParquet(tmpPath, rows.Count);
                File.Move(tmpPath, finalPath, overwrite: false);
                var record = ManifestRecord.ForChunk("snapshots", finalPath, key, rows.Count, rows[0].TimestampUs, rows[^1].TimestampUs, _levelsPerSide, finalFlush);
                AppendManifest(key.Day, record);
                Interlocked.Add(ref _snapshotsWritten, rows.Count);
                Interlocked.Increment(ref _snapshotFiles);
                lock (_statusGate)
                    _lastSnapshotFile = finalPath;
                return true;
            }
            catch (Exception ex)
            {
                Interlocked.Increment(ref _snapshotWriteFailures);
                RecordError("write snapshots", ex);
                return false;
            }
        }

        private async Task WriteTickFile(string path, List<TickRow> rows)
        {
            using var fs = new FileStream(path, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.Read);
            using var writer = await ParquetWriter.CreateAsync(_tickSchema, fs, append: false);
            writer.CompressionMethod = CompressionMethod.Snappy;
            using var rg = writer.CreateRowGroup();
            int n = rows.Count;
            var ts = new long[n];
            var px = new double[n];
            var sz = new double[n];
            var ag = new int[n];
            for (int i = 0; i < n; i++)
            {
                ts[i] = rows[i].TimestampUs;
                px[i] = rows[i].Price;
                sz[i] = rows[i].Size;
                ag[i] = rows[i].AggressorSign;
            }
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[0], ts));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[1], px));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[2], sz));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[3], ag));
        }

        private async Task WriteSnapshotFile(string path, List<SnapshotRow> rows)
        {
            using var fs = new FileStream(path, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.Read);
            using var writer = await ParquetWriter.CreateAsync(_snapshotSchema, fs, append: false);
            writer.CompressionMethod = CompressionMethod.Snappy;
            using var rg = writer.CreateRowGroup();
            int n = rows.Count;
            var ts = new long[n];
            var rt = new long[n];
            for (int i = 0; i < n; i++)
            {
                ts[i] = rows[i].TimestampUs;
                rt[i] = rows[i].RefTick;
            }
            int idx = 0;
            await rg.WriteColumnAsync(new DataColumn(_snapshotSchema.DataFields[idx++], ts));
            await rg.WriteColumnAsync(new DataColumn(_snapshotSchema.DataFields[idx++], rt));

            for (int level = 0; level < _levelsPerSide; level++)
            {
                var off = new int[n];
                var size = new double[n];
                for (int i = 0; i < n; i++)
                {
                    off[i] = rows[i].BidOffsets[level];
                    size[i] = rows[i].BidSizes[level];
                }
                await rg.WriteColumnAsync(new DataColumn(_snapshotSchema.DataFields[idx++], off));
                await rg.WriteColumnAsync(new DataColumn(_snapshotSchema.DataFields[idx++], size));
            }
            for (int level = 0; level < _levelsPerSide; level++)
            {
                var off = new int[n];
                var size = new double[n];
                for (int i = 0; i < n; i++)
                {
                    off[i] = rows[i].AskOffsets[level];
                    size[i] = rows[i].AskSizes[level];
                }
                await rg.WriteColumnAsync(new DataColumn(_snapshotSchema.DataFields[idx++], off));
                await rg.WriteColumnAsync(new DataColumn(_snapshotSchema.DataFields[idx++], size));
            }
        }

        private async Task ValidateParquet(string path, int expectedRows)
        {
            using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            using var reader = await ParquetReader.CreateAsync(fs);
            if (reader.RowGroupCount <= 0)
                throw new InvalidDataException("no row groups");
            var field = reader.Schema.DataFields.First(f => f.Name == "timestamp_us");
            using var rg = reader.OpenRowGroupReader(0);
            var col = await rg.ReadColumnAsync(field);
            if (col.Data == null || col.Data.Length != expectedRows)
                throw new InvalidDataException($"timestamp row count mismatch, expected {expectedRows}");
        }

        private SnapshotRow BuildSnapshotRow(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            if (dom == null) return null;
            var bids = dom.Bids ?? Array.Empty<Level2Item>();
            var asks = dom.Asks ?? Array.Empty<Level2Item>();
            if (bids.Length == 0 && asks.Length == 0) return null;
            double ts = tickSize > 0 ? tickSize : 0.25;
            long PriceToTicks(double p) => (long)Math.Round(p / ts);

            double bidPrice = FirstValidPrice(bids);
            double askPrice = FirstValidPrice(asks);
            if (double.IsNaN(bidPrice) && double.IsNaN(askPrice)) return null;

            long refTick;
            if (!double.IsNaN(bidPrice) && !double.IsNaN(askPrice))
                refTick = (PriceToTicks(bidPrice) + PriceToTicks(askPrice)) / 2;
            else if (!double.IsNaN(bidPrice))
                refTick = PriceToTicks(bidPrice);
            else
                refTick = PriceToTicks(askPrice);

            var row = new SnapshotRow
            {
                TimestampUs = ToMicros(nowUtc),
                RefTick = refTick,
                BidOffsets = new int[_levelsPerSide],
                BidSizes = new double[_levelsPerSide],
                AskOffsets = new int[_levelsPerSide],
                AskSizes = new double[_levelsPerSide],
            };

            int outIdx = 0;
            for (int i = 0; i < bids.Length && outIdx < _levelsPerSide; i++)
            {
                double p = bids[i].Price;
                double s = bids[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(s) || s <= 0) continue;
                row.BidOffsets[outIdx] = (int)(PriceToTicks(p) - refTick);
                row.BidSizes[outIdx] = s;
                outIdx++;
            }
            outIdx = 0;
            for (int i = 0; i < asks.Length && outIdx < _levelsPerSide; i++)
            {
                double p = asks[i].Price;
                double s = asks[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(s) || s <= 0) continue;
                row.AskOffsets[outIdx] = (int)(PriceToTicks(p) - refTick);
                row.AskSizes[outIdx] = s;
                outIdx++;
            }
            return row;
        }

        private string NextChunkPath(ChunkKey key, string streamDir, string prefix)
        {
            string dir = Path.Combine(SymbolRoot, key.Day, streamDir);
            string basePath = Path.Combine(dir, $"{prefix}-{key.StartLabel}-{key.EndLabel}.parquet");
            if (!File.Exists(basePath)) return basePath;
            for (int i = 2; i < 1000; i++)
            {
                string p = Path.Combine(dir, $"{prefix}-{key.StartLabel}-{key.EndLabel}-p{i}.parquet");
                if (!File.Exists(p)) return p;
            }
            throw new IOException("could not allocate unique chunk path");
        }

        private void AppendManifest(string day, ManifestRecord record)
        {
            string path = Path.Combine(SymbolRoot, day, "manifest.jsonl");
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.AppendAllText(path, JsonSerializer.Serialize(record, _jsonOptions) + Environment.NewLine);
        }

        private void WriteStatusFile()
        {
            try
            {
                var status = GetStatus();
                status.NowUtc = DateTime.UtcNow.ToString("O");
                string json = JsonSerializer.Serialize(status, _jsonOptions);
                string path = StatusPath;
                string tmp = path + ".tmp";
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.WriteAllText(tmp, json);
                File.Move(tmp, path, overwrite: true);
                lock (_statusGate)
                    _lastStatusUtc = DateTime.UtcNow;
            }
            catch (Exception ex)
            {
                RecordError("write status", ex);
            }
        }

        private void RecordError(string action, Exception ex)
        {
            string message = $"{action}: {ex.Message}";
            lock (_statusGate)
                _lastError = message;
            try { Core.Instance.Loggers.Log($"[MarketRecorder] {message}", LoggingLevel.Error); }
            catch { }
        }

        private void CleanupOldDayDirs()
        {
            var root = SymbolRoot;
            if (!Directory.Exists(root)) return;
            var cutoff = DateTime.Today.AddDays(-_retentionDays);
            foreach (var dir in Directory.EnumerateDirectories(root))
            {
                var name = Path.GetFileName(dir);
                if (!DateTime.TryParse(name, out var day)) continue;
                if (day.Date < cutoff)
                    Directory.Delete(dir, recursive: true);
            }
        }

        private ChunkKey ChunkFor(long tsUs)
        {
            DateTime local = TimeZoneInfo.ConvertTimeFromUtc(UtcFromMicros(tsUs), _nyZone);
            var localMidnight = new DateTime(local.Year, local.Month, local.Day, 0, 0, 0, DateTimeKind.Unspecified);
            int secondOfDay = local.Hour * 3600 + local.Minute * 60 + local.Second;
            int startSecond = (secondOfDay / _chunkSeconds) * _chunkSeconds;
            DateTime startLocal = localMidnight.AddSeconds(startSecond);
            DateTime endExclusiveLocal = startLocal.AddSeconds(_chunkSeconds);
            DateTime endLabelLocal = endExclusiveLocal.AddSeconds(-1);
            DateTime startUtc = TimeZoneInfo.ConvertTimeToUtc(startLocal, _nyZone);
            DateTime endUtc = TimeZoneInfo.ConvertTimeToUtc(endExclusiveLocal, _nyZone);
            return new ChunkKey(
                local.ToString("yyyy-MM-dd"),
                ToMicros(startUtc),
                ToMicros(endUtc),
                startLocal.ToString("HHmmss"),
                endLabelLocal.ToString("HHmmss"));
        }

        private void UpdatePendingCounts()
        {
            lock (_bufferGate)
                UpdatePendingCountsNoLock();
        }

        private void UpdatePendingCountsNoLock()
        {
            _pendingTickRows = _tickChunks.Values.Sum(x => x.Count);
            _pendingSnapshotRows = _snapshotChunks.Values.Sum(x => x.Count);
        }

        private static void AddToChunk<T>(Dictionary<ChunkKey, List<T>> chunks, ChunkKey key, T row)
        {
            if (!chunks.TryGetValue(key, out var list))
            {
                list = new List<T>();
                chunks[key] = list;
            }
            list.Add(row);
        }

        private static long TimestampOf<T>(T row)
        {
            if (row is TickRow tick) return tick.TimestampUs;
            if (row is SnapshotRow snap) return snap.TimestampUs;
            return 0;
        }

        private static ParquetSchema BuildTickSchema()
            => new(
                new DataField<long>("timestamp_us"),
                new DataField<double>("price"),
                new DataField<double>("size"),
                new DataField<int>("aggressor_sign"));

        private static ParquetSchema BuildSnapshotSchema(int levelsPerSide)
        {
            var fields = new List<Field>
            {
                new DataField<long>("timestamp_us"),
                new DataField<long>("ref_tick"),
            };
            for (int i = 0; i < levelsPerSide; i++)
            {
                fields.Add(new DataField<int>($"bid_offset_{i}"));
                fields.Add(new DataField<double>($"bid_size_{i}"));
            }
            for (int i = 0; i < levelsPerSide; i++)
            {
                fields.Add(new DataField<int>($"ask_offset_{i}"));
                fields.Add(new DataField<double>($"ask_size_{i}"));
            }
            return new ParquetSchema(fields);
        }

        private static double FirstValidPrice(Level2Item[] arr)
        {
            if (arr == null) return double.NaN;
            for (int i = 0; i < arr.Length; i++)
            {
                double p = arr[i].Price;
                double s = arr[i].Size;
                if (double.IsFinite(p) && p > 0 && double.IsFinite(s) && s > 0)
                    return p;
            }
            return double.NaN;
        }

        private static long ToMicros(DateTime utc)
            => (utc.ToUniversalTime() - DateTime.UnixEpoch).Ticks / 10;

        private static DateTime UtcFromMicros(long us)
            => DateTime.UnixEpoch.AddTicks(us * 10);

        private static string IsoOrEmpty(long us)
            => us <= 0 ? "" : UtcFromMicros(us).ToString("O");

        private static string SanitizeForPath(string s)
        {
            foreach (char ch in Path.GetInvalidFileNameChars())
                s = s.Replace(ch, '_');
            return string.IsNullOrWhiteSpace(s) ? "UNKNOWN" : s;
        }

        private readonly struct ChunkKey : IEquatable<ChunkKey>
        {
            public readonly string Day;
            public readonly long StartUs;
            public readonly long EndUs;
            public readonly string StartLabel;
            public readonly string EndLabel;

            public ChunkKey(string day, long startUs, long endUs, string startLabel, string endLabel)
            {
                Day = day;
                StartUs = startUs;
                EndUs = endUs;
                StartLabel = startLabel;
                EndLabel = endLabel;
            }

            public bool Equals(ChunkKey other)
                => Day == other.Day && StartUs == other.StartUs && EndUs == other.EndUs;

            public override bool Equals(object obj)
                => obj is ChunkKey other && Equals(other);

            public override int GetHashCode()
                => HashCode.Combine(Day, StartUs, EndUs);
        }

        private sealed class TickRow
        {
            public long TimestampUs;
            public double Price;
            public double Size;
            public int AggressorSign;
        }

        private sealed class SnapshotRow
        {
            public long TimestampUs;
            public long RefTick;
            public int[] BidOffsets;
            public double[] BidSizes;
            public int[] AskOffsets;
            public double[] AskSizes;
        }

        private sealed class ManifestRecord
        {
            public string Stream { get; set; }
            public string File { get; set; }
            public string Day { get; set; }
            public string ChunkStartUtc { get; set; }
            public string ChunkEndUtc { get; set; }
            public string FirstUtc { get; set; }
            public string LastUtc { get; set; }
            public int Rows { get; set; }
            public int LevelsPerSide { get; set; }
            public bool Validated { get; set; }
            public bool FinalFlush { get; set; }
            public string WrittenUtc { get; set; }

            public static ManifestRecord ForChunk(
                string stream,
                string file,
                ChunkKey key,
                int rows,
                long firstUs,
                long lastUs,
                int levelsPerSide,
                bool finalFlush)
            {
                return new ManifestRecord
                {
                    Stream = stream,
                    File = file,
                    Day = key.Day,
                    ChunkStartUtc = IsoOrEmpty(key.StartUs),
                    ChunkEndUtc = IsoOrEmpty(key.EndUs),
                    FirstUtc = IsoOrEmpty(firstUs),
                    LastUtc = IsoOrEmpty(lastUs),
                    Rows = rows,
                    LevelsPerSide = stream == "snapshots" ? levelsPerSide : 0,
                    Validated = true,
                    FinalFlush = finalFlush,
                    WrittenUtc = DateTime.UtcNow.ToString("O"),
                };
            }
        }
    }

    internal sealed class RecorderStatusSnapshot
    {
        public string Version { get; set; }
        public string NowUtc { get; set; }
        public string LastStatusUtc { get; set; }
        public string Symbol { get; set; }
        public string Root { get; set; }
        public int LevelsPerSide { get; set; }
        public int ChunkSeconds { get; set; }
        public bool TicksEnabled { get; set; }
        public bool SnapshotsEnabled { get; set; }
        public long TickRowsEnqueued { get; set; }
        public long TickRowsWritten { get; set; }
        public long TickFiles { get; set; }
        public long SnapshotRowsEnqueued { get; set; }
        public long SnapshotRowsWritten { get; set; }
        public long SnapshotFiles { get; set; }
        public long SnapshotSkips { get; set; }
        public int TickQueueRows { get; set; }
        public int SnapshotQueueRows { get; set; }
        public string LastTickUtc { get; set; }
        public string LastSnapshotUtc { get; set; }
        public string LastTickFile { get; set; }
        public string LastSnapshotFile { get; set; }
        public long TickWriteFailures { get; set; }
        public long SnapshotWriteFailures { get; set; }
        public string BookState { get; set; }
        public string LastError { get; set; }
    }
}
