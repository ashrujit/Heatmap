using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Parquet;
using Parquet.Data;
using Parquet.Schema;
using TradingPlatform.BusinessLayer;
using TradingPlatform.BusinessLayer.Integration;

namespace MarketRecorder
{
    internal sealed class ChunkedCaptureWriter : IDisposable
    {
        private const string Version = "0.2.3";
        private const int BookEventRowGroupSize = 50000;
        private const int FileRetryCount = 5;
        private const int FileRetryBaseDelayMs = 50;

        private readonly string _root;
        private readonly string _symbolKey;
        private readonly string _instanceId = Guid.NewGuid().ToString("N");
        private readonly int _levelsPerSide;
        private readonly int _chunkSeconds;
        private readonly int _flushSeconds;
        private readonly int _retentionDays;
        private readonly int _queueCap;
        private readonly int _bookEventQueueCap;
        private readonly int _bookEventChunkSeconds;
        private readonly bool _writeTicks;
        private readonly bool _writeSnapshots;
        private readonly bool _writeBookEvents;
        private readonly TimeZoneInfo _nyZone;
        private readonly ParquetSchema _tickSchema;
        private readonly ParquetSchema _snapshotSchema;
        private readonly ParquetSchema _bookEventSchema;
        private readonly ConcurrentQueue<TickRow> _tickQueue = new();
        private readonly ConcurrentQueue<SnapshotRow> _snapshotQueue = new();
        private readonly ConcurrentQueue<BookEventRow> _bookEventQueue = new();
        private readonly Dictionary<ChunkKey, List<TickRow>> _tickChunks = new();
        private readonly Dictionary<ChunkKey, List<SnapshotRow>> _snapshotChunks = new();
        private readonly Dictionary<ChunkKey, List<BookEventRow>> _bookEventChunks = new();
        private readonly object _bufferGate = new();
        private readonly object _statusGate = new();
        private readonly object _bookGapGate = new();
        private readonly JsonSerializerOptions _jsonOptions = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };

        private CancellationTokenSource _cts;
        private Task _writerTask;
        private FileStream _captureLockStream;
        private bool _disposed;

        private long _ticksEnqueued;
        private long _ticksWritten;
        private long _tickFiles;
        private long _snapshotsEnqueued;
        private long _snapshotsWritten;
        private long _snapshotFiles;
        private long _snapshotSkips;
        private long _tickRowsDropped;
        private long _snapshotRowsDropped;
        private long _tickWriteFailures;
        private long _snapshotWriteFailures;
        private long _bookEventRowsEnqueued;
        private long _bookEventRowsWritten;
        private long _bookEventFiles;
        private long _bookEventRowsDropped;
        private long _bookEventWriteFailures;
        private long _bookCallbacksSeen;
        private long _bookCallbacksDropped;
        private long _bookDeltaCallbacks;
        private long _bookResetCallbacks;
        private long _bookSeedsCaptured;
        private long _bookContinuityGaps;
        private long _bookPreResetDeltas;
        private long _bookSequence;
        private long _bookResetEpoch;
        private long _bookEventQueueHighWater;
        private long _telemetryLastCallbacks;
        private long _telemetryLastRows;
        private long _pendingGapStartSequence;
        private long _pendingGapEndSequence;
        private int _pendingTickRows;
        private int _pendingSnapshotRows;
        private int _pendingBookEventRows;
        private int _bookEventRowsWriting;
        private int _bookSeedRequired;
        private long _lastTickUs;
        private long _lastSnapshotUs;
        private long _lastBookEventUs;
        private long _lastBookResetUs;
        private string _lastTickFile = "";
        private string _lastSnapshotFile = "";
        private string _lastBookEventFile = "";
        private string _lastError = "";
        private string _bookState = "starting";
        private DateTime _lastStatusUtc = DateTime.MinValue;
        private DateTime _telemetryLastUtc = DateTime.MinValue;
        private double _bookCallbackRatePerSec;
        private double _bookEventRowRatePerSec;

        public ChunkedCaptureWriter(
            string root,
            string symbol,
            int levelsPerSide,
            int chunkSeconds,
            int flushSeconds,
            int retentionDays,
            int queueCap,
            int bookEventQueueCap,
            int bookEventChunkSeconds,
            bool writeTicks,
            bool writeSnapshots,
            bool writeBookEvents)
        {
            _root = string.IsNullOrWhiteSpace(root)
                ? @"C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures"
                : root;
            _symbolKey = SanitizeForPath(string.IsNullOrWhiteSpace(symbol) ? "UNKNOWN" : symbol);
            _levelsPerSide = Math.Max(30, Math.Min(200, levelsPerSide));
            _chunkSeconds = Math.Max(60, Math.Min(1800, chunkSeconds));
            _flushSeconds = Math.Max(1, Math.Min(60, flushSeconds));
            _retentionDays = Math.Max(1, retentionDays);
            _queueCap = Math.Max(1000, queueCap);
            _bookEventQueueCap = Math.Max(10000, bookEventQueueCap);
            _bookEventChunkSeconds = Math.Max(10, Math.Min(300, bookEventChunkSeconds));
            _writeTicks = writeTicks;
            _writeSnapshots = writeSnapshots;
            _writeBookEvents = writeBookEvents;
            _bookSeedRequired = writeBookEvents ? 1 : 0;
            try { _nyZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch { _nyZone = TimeZoneInfo.Local; }
            _tickSchema = BuildTickSchema();
            _snapshotSchema = BuildSnapshotSchema(_levelsPerSide);
            _bookEventSchema = BuildBookEventSchema();
        }

        public int LevelsPerSide => _levelsPerSide;
        public bool NeedsBookSeed => _writeBookEvents
            && Volatile.Read(ref _bookSeedRequired) != 0;
        public string StatusPath => Path.Combine(SymbolRoot, "status.json");
        private string SymbolRoot => Path.Combine(_root, _symbolKey);

        public void Start()
        {
            Directory.CreateDirectory(SymbolRoot);
            AcquireCaptureLock();
            try { CleanupOldDayDirs(); } catch (Exception ex) { RecordError("cleanup", ex); }
            _cts = new CancellationTokenSource();
            _telemetryLastUtc = DateTime.UtcNow;
            _writerTask = Task.Run(() => WriterLoop(_cts.Token));
            WriteStatusFile();
        }

        public void EnqueueTick(
            DateTime timeUtc,
            double price,
            double size,
            AggressorFlag flag,
            string tradeId = null,
            string buyer = null,
            string seller = null)
        {
            if (!_writeTicks || _disposed) return;
            if (!double.IsFinite(price) || price <= 0) return;
            if (!double.IsFinite(size) || size <= 0) return;

            var utc = timeUtc == default ? DateTime.UtcNow : timeUtc.ToUniversalTime();
            int sign = flag == AggressorFlag.Buy ? 1 : (flag == AggressorFlag.Sell ? -1 : 0);
            long tsUs = ToMicros(utc);
            if (_tickQueue.Count + Volatile.Read(ref _pendingTickRows) >= _queueCap)
            {
                Interlocked.Increment(ref _tickRowsDropped);
                return;
            }
            _tickQueue.Enqueue(new TickRow
            {
                TimestampUs = tsUs,
                Price = price,
                Size = size,
                AggressorSign = sign,
                TradeId = NormalizeText(tradeId),
                Buyer = NormalizeText(buyer),
                Seller = NormalizeText(seller),
            });
            Interlocked.Increment(ref _ticksEnqueued);
            Interlocked.Exchange(ref _lastTickUs, tsUs);
        }

        public void EnqueueSnapshot(DateTime timeUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            if (!_writeSnapshots || _disposed) return;
            var row = BuildSnapshotRow(timeUtc.ToUniversalTime(), dom, tickSize);
            if (row == null) return;
            if (_snapshotQueue.Count + Volatile.Read(ref _pendingSnapshotRows) >= _queueCap)
            {
                Interlocked.Increment(ref _snapshotRowsDropped);
                return;
            }
            _snapshotQueue.Enqueue(row);
            Interlocked.Increment(ref _snapshotsEnqueued);
            Interlocked.Exchange(ref _lastSnapshotUs, row.TimestampUs);
        }

        public void EnqueueBookUpdate(
            DateTime receiptUtc,
            Level2Quote level2,
            DOMQuote dom,
            double tickSize)
            => EnqueueBookUpdateCore(receiptUtc, level2, dom, tickSize, isExplicitSeed: false);

        public void EnqueueBookSeed(DateTime receiptUtc, DOMQuote dom, double tickSize)
            => EnqueueBookUpdateCore(receiptUtc, null, dom, tickSize, isExplicitSeed: true);

        private void EnqueueBookUpdateCore(
            DateTime receiptUtc,
            Level2Quote level2,
            DOMQuote dom,
            double tickSize,
            bool isExplicitSeed)
        {
            if (!_writeBookEvents || _disposed || level2 == null && dom == null)
                return;

            long sequence = Interlocked.Increment(ref _bookSequence);
            if (!isExplicitSeed)
                Interlocked.Increment(ref _bookCallbacksSeen);
            DateTime received = receiptUtc == default ? DateTime.UtcNow : receiptUtc.ToUniversalTime();
            long receiptUs = ToMicros(received);
            double ts = tickSize > 0 ? tickSize : 0.25;

            if (level2 != null)
            {
                Interlocked.Increment(ref _bookDeltaCallbacks);
                long epoch = Interlocked.Read(ref _bookResetEpoch);
                int required = PendingGapRowCount() + 1;
                if (!HasBookEventCapacity(required))
                {
                    NoteBookDrop(sequence, 1);
                    return;
                }
                EmitPendingGap(receiptUs, epoch);
                EnqueueBookEvent(BuildQuoteEvent(
                    BookEventKind.Delta,
                    sequence,
                    subsequence: 0,
                    epoch,
                    receiptUs,
                    level2.Time,
                    level2,
                    ts,
                    resetItemCount: 0));
                if (epoch <= 0)
                    Interlocked.Increment(ref _bookPreResetDeltas);
                Interlocked.Exchange(ref _lastBookEventUs, receiptUs);
                return;
            }

            if (!isExplicitSeed)
                Interlocked.Increment(ref _bookResetCallbacks);
            int askCount = dom.Asks?.Count(quote => quote != null) ?? 0;
            int bidCount = dom.Bids?.Count(quote => quote != null) ?? 0;
            int itemCount = askCount + bidCount;
            int resetRows = itemCount + 2;
            if (itemCount <= 0)
            {
                NoteBookDrop(sequence, resetRows, callbackDropped: !isExplicitSeed);
                return;
            }
            int needed = PendingGapRowCount() + resetRows;
            if (!HasBookEventCapacity(needed))
            {
                NoteBookDrop(sequence, resetRows, callbackDropped: !isExplicitSeed);
                return;
            }

            long resetEpoch = Interlocked.Increment(ref _bookResetEpoch);
            EmitPendingGap(receiptUs, resetEpoch);
            EnqueueBookEvent(BookEventRow.Marker(
                BookEventKind.ResetBegin,
                sequence,
                subsequence: 0,
                resetEpoch,
                receiptUs,
                ExchangeMicros(dom.Time, received),
                itemCount));

            int subsequence = 1;
            if (dom.Bids != null)
            {
                foreach (Level2Quote quote in dom.Bids)
                {
                    if (quote == null) continue;
                    EnqueueBookEvent(BuildQuoteEvent(
                        BookEventKind.ResetItem,
                        sequence,
                        subsequence++,
                        resetEpoch,
                        receiptUs,
                        quote.Time == default ? dom.Time : quote.Time,
                        quote,
                        ts,
                        itemCount));
                }
            }
            if (dom.Asks != null)
            {
                foreach (Level2Quote quote in dom.Asks)
                {
                    if (quote == null) continue;
                    EnqueueBookEvent(BuildQuoteEvent(
                        BookEventKind.ResetItem,
                        sequence,
                        subsequence++,
                        resetEpoch,
                        receiptUs,
                        quote.Time == default ? dom.Time : quote.Time,
                        quote,
                        ts,
                        itemCount));
                }
            }
            EnqueueBookEvent(BookEventRow.Marker(
                BookEventKind.ResetEnd,
                sequence,
                subsequence,
                resetEpoch,
                receiptUs,
                ExchangeMicros(dom.Time, received),
                itemCount));
            Interlocked.Exchange(ref _lastBookEventUs, receiptUs);
            Interlocked.Exchange(ref _lastBookResetUs, receiptUs);
            if (isExplicitSeed)
                Interlocked.Increment(ref _bookSeedsCaptured);
            Volatile.Write(ref _bookSeedRequired, 0);
        }

        private BookEventRow BuildQuoteEvent(
            BookEventKind kind,
            long sequence,
            int subsequence,
            long epoch,
            long receiptUs,
            DateTime exchangeTime,
            Level2Quote quote,
            double tickSize,
            int resetItemCount)
        {
            if (string.IsNullOrEmpty(quote.Id))
                throw new InvalidDataException("real L2 quote has no id");
            if (!quote.Closed
                && (!double.IsFinite(quote.Price) || quote.Price <= 0
                    || !double.IsFinite(quote.Size) || quote.Size < 0))
                throw new InvalidDataException("live L2 quote has invalid price or size");

            long priceTick = double.IsFinite(quote.Price) && quote.Price > 0
                ? (long)Math.Round(quote.Price / tickSize)
                : long.MinValue;
            return new BookEventRow
            {
                ReceiptTimestampUs = receiptUs,
                ExchangeTimestampUs = ExchangeMicros(exchangeTime, UtcFromMicros(receiptUs)),
                Sequence = sequence,
                Subsequence = subsequence,
                ResetEpoch = epoch,
                EventKind = (int)kind,
                Side = quote.PriceType == QuotePriceType.Bid ? 1 : -1,
                PriceTick = priceTick,
                Size = quote.Size,
                Closed = quote.Closed,
                QuoteIdHash = StableQuoteIdHash(quote.Id),
                ImpliedSize = quote.ImpliedSize,
                Priority = quote.Priority,
                NumberOrders = quote.NumberOrders,
                ResetItemCount = resetItemCount,
            };
        }

        private bool HasBookEventCapacity(int requiredRows)
            => _bookEventQueue.Count + Volatile.Read(ref _pendingBookEventRows)
                + Volatile.Read(ref _bookEventRowsWriting) + requiredRows
                <= _bookEventQueueCap;

        private int PendingGapRowCount()
        {
            lock (_bookGapGate)
                return _pendingGapStartSequence > 0 ? 1 : 0;
        }

        private void NoteBookDrop(long sequence, int rows, bool callbackDropped = true)
        {
            Volatile.Write(ref _bookSeedRequired, 1);
            if (callbackDropped)
                Interlocked.Increment(ref _bookCallbacksDropped);
            Interlocked.Add(ref _bookEventRowsDropped, Math.Max(1, rows));
            lock (_bookGapGate)
            {
                if (_pendingGapStartSequence <= 0)
                    _pendingGapStartSequence = sequence;
                _pendingGapEndSequence = sequence;
            }
        }

        private void EmitPendingGap(long receiptUs, long epoch)
        {
            long start;
            long end;
            lock (_bookGapGate)
            {
                start = _pendingGapStartSequence;
                end = _pendingGapEndSequence;
                _pendingGapStartSequence = 0;
                _pendingGapEndSequence = 0;
            }
            if (start <= 0) return;
            EnqueueBookEvent(BookEventRow.Gap(receiptUs, end, epoch, start, end));
            Interlocked.Increment(ref _bookContinuityGaps);
        }

        private void EnqueueBookEvent(BookEventRow row)
        {
            _bookEventQueue.Enqueue(row);
            Interlocked.Increment(ref _bookEventRowsEnqueued);
            ObserveBookEventHighWater();
        }

        private void ObserveBookEventHighWater()
        {
            long current = _bookEventQueue.Count + Volatile.Read(ref _pendingBookEventRows)
                + Volatile.Read(ref _bookEventRowsWriting);
            long observed = Interlocked.Read(ref _bookEventQueueHighWater);
            while (current > observed)
            {
                long prior = Interlocked.CompareExchange(
                    ref _bookEventQueueHighWater,
                    current,
                    observed);
                if (prior == observed) break;
                observed = prior;
            }
        }

        public void NoteSnapshotSkipped(string reason)
        {
            Interlocked.Increment(ref _snapshotSkips);
            lock (_statusGate)
                _bookState = string.IsNullOrWhiteSpace(reason) ? "snapshot skipped" : reason;
        }

        public void NoteBookEventCaptureFailure(string message)
        {
            long sequence = Math.Max(1, Interlocked.Read(ref _bookSequence));
            NoteBookDrop(sequence, 1);
            lock (_statusGate)
                _lastError = "capture book event: "
                    + (string.IsNullOrWhiteSpace(message) ? "unknown error" : message);
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
                    BookEventChunkSeconds = _bookEventChunkSeconds,
                    TicksEnabled = _writeTicks,
                    SnapshotsEnabled = _writeSnapshots,
                    BookEventsEnabled = _writeBookEvents,
                    TickRowsEnqueued = Interlocked.Read(ref _ticksEnqueued),
                    TickRowsWritten = Interlocked.Read(ref _ticksWritten),
                    TickFiles = Interlocked.Read(ref _tickFiles),
                    SnapshotRowsEnqueued = Interlocked.Read(ref _snapshotsEnqueued),
                    SnapshotRowsWritten = Interlocked.Read(ref _snapshotsWritten),
                    SnapshotFiles = Interlocked.Read(ref _snapshotFiles),
                    SnapshotSkips = Interlocked.Read(ref _snapshotSkips),
                    TickQueueRows = _tickQueue.Count + _pendingTickRows,
                    SnapshotQueueRows = _snapshotQueue.Count + _pendingSnapshotRows,
                    BookEventQueueRows = _bookEventQueue.Count + _pendingBookEventRows
                        + Volatile.Read(ref _bookEventRowsWriting),
                    BookEventRowsWriting = Volatile.Read(ref _bookEventRowsWriting),
                    TickRowsDropped = Interlocked.Read(ref _tickRowsDropped),
                    SnapshotRowsDropped = Interlocked.Read(ref _snapshotRowsDropped),
                    QueueCapRows = _queueCap,
                    BookEventQueueCapRows = _bookEventQueueCap,
                    BookEventQueueHighWaterRows = Interlocked.Read(ref _bookEventQueueHighWater),
                    BookCallbackRatePerSec = _bookCallbackRatePerSec,
                    BookEventRowRatePerSec = _bookEventRowRatePerSec,
                    LastTickUtc = IsoOrEmpty(Interlocked.Read(ref _lastTickUs)),
                    LastSnapshotUtc = IsoOrEmpty(Interlocked.Read(ref _lastSnapshotUs)),
                    LastBookEventUtc = IsoOrEmpty(Interlocked.Read(ref _lastBookEventUs)),
                    LastBookResetUtc = IsoOrEmpty(Interlocked.Read(ref _lastBookResetUs)),
                    LastTickFile = _lastTickFile,
                    LastSnapshotFile = _lastSnapshotFile,
                    LastBookEventFile = _lastBookEventFile,
                    TickWriteFailures = Interlocked.Read(ref _tickWriteFailures),
                    SnapshotWriteFailures = Interlocked.Read(ref _snapshotWriteFailures),
                    BookEventRowsEnqueued = Interlocked.Read(ref _bookEventRowsEnqueued),
                    BookEventRowsWritten = Interlocked.Read(ref _bookEventRowsWritten),
                    BookEventFiles = Interlocked.Read(ref _bookEventFiles),
                    BookEventRowsDropped = Interlocked.Read(ref _bookEventRowsDropped),
                    BookEventWriteFailures = Interlocked.Read(ref _bookEventWriteFailures),
                    BookCallbacksSeen = Interlocked.Read(ref _bookCallbacksSeen),
                    BookCallbacksDropped = Interlocked.Read(ref _bookCallbacksDropped),
                    BookDeltaCallbacks = Interlocked.Read(ref _bookDeltaCallbacks),
                    BookResetCallbacks = Interlocked.Read(ref _bookResetCallbacks),
                    BookSeedsCaptured = Interlocked.Read(ref _bookSeedsCaptured),
                    BookContinuityGaps = Interlocked.Read(ref _bookContinuityGaps),
                    BookPreResetDeltas = Interlocked.Read(ref _bookPreResetDeltas),
                    BookSequence = Interlocked.Read(ref _bookSequence),
                    BookResetEpoch = Interlocked.Read(ref _bookResetEpoch),
                    BookSeedRequired = NeedsBookSeed,
                    BookGapPending = PendingGapRowCount() > 0,
                    BookState = _bookState,
                    LastError = _lastError,
                    LastStatusUtc = _lastStatusUtc == DateTime.MinValue ? "" : _lastStatusUtc.ToString("O"),
                };
            }
        }

        public void Dispose()
        {
            if (_writeBookEvents && PendingGapRowCount() > 0)
                EmitPendingGap(ToMicros(DateTime.UtcNow), Interlocked.Read(ref _bookResetEpoch));
            _disposed = true;
            try { _cts?.Cancel(); } catch { }
            try { _writerTask?.Wait(TimeSpan.FromSeconds(30)); } catch { }
            try { _cts?.Dispose(); } catch { }
            try { _captureLockStream?.Dispose(); } catch { }
            _cts = null;
            _writerTask = null;
            _captureLockStream = null;
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
            var bookEventReady = TakeReady(_bookEventChunks, nowUs, force);
            Interlocked.Add(
                ref _bookEventRowsWriting,
                bookEventReady.Sum(item => item.Value.Count));

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
            foreach (var item in bookEventReady)
            {
                try
                {
                    if (!await TryWriteBookEventChunk(item.Key, item.Value, force))
                        RestoreChunk(_bookEventChunks, item.Key, item.Value);
                }
                finally
                {
                    Interlocked.Add(ref _bookEventRowsWriting, -item.Value.Count);
                }
            }
            UpdatePendingCounts();
        }

        private void DrainQueuesIntoBuffers()
        {
            if (_tickQueue.IsEmpty && _snapshotQueue.IsEmpty && _bookEventQueue.IsEmpty)
                return;

            lock (_bufferGate)
            {
                while (_tickQueue.TryDequeue(out var tick))
                    AddToChunk(_tickChunks, ChunkFor(tick.TimestampUs, _chunkSeconds), tick);
                while (_snapshotQueue.TryDequeue(out var snap))
                    AddToChunk(_snapshotChunks, ChunkFor(snap.TimestampUs, _chunkSeconds), snap);
                while (_bookEventQueue.TryDequeue(out var bookEvent))
                    AddToChunk(
                        _bookEventChunks,
                        ChunkFor(bookEvent.ReceiptTimestampUs, _bookEventChunkSeconds),
                        bookEvent);
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
                await ValidateParquet(tmpPath, rows.Count, "timestamp_us");
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
                await ValidateParquet(tmpPath, rows.Count, "timestamp_us");
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
            var tradeIds = new string[n];
            var buyers = new string[n];
            var sellers = new string[n];
            for (int i = 0; i < n; i++)
            {
                ts[i] = rows[i].TimestampUs;
                px[i] = rows[i].Price;
                sz[i] = rows[i].Size;
                ag[i] = rows[i].AggressorSign;
                tradeIds[i] = rows[i].TradeId ?? "";
                buyers[i] = rows[i].Buyer ?? "";
                sellers[i] = rows[i].Seller ?? "";
            }
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[0], ts));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[1], px));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[2], sz));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[3], ag));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[4], tradeIds));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[5], buyers));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[6], sellers));
        }

        private async Task<bool> TryWriteBookEventChunk(
            ChunkKey key,
            List<BookEventRow> rows,
            bool finalFlush)
        {
            if (rows.Count == 0) return true;
            rows.Sort((left, right) =>
            {
                int sequence = left.Sequence.CompareTo(right.Sequence);
                return sequence != 0 ? sequence : left.Subsequence.CompareTo(right.Subsequence);
            });
            try
            {
                string finalPath = NextChunkPath(key, "book_events", "book-events");
                string tmpPath = finalPath + ".tmp-" + Guid.NewGuid().ToString("N");
                Directory.CreateDirectory(Path.GetDirectoryName(finalPath));
                await WriteBookEventFile(tmpPath, rows);
                await ValidateParquet(tmpPath, rows.Count, "receipt_timestamp_us");
                File.Move(tmpPath, finalPath, overwrite: false);
                var record = ManifestRecord.ForChunk(
                    "book_events",
                    finalPath,
                    key,
                    rows.Count,
                    rows[0].ReceiptTimestampUs,
                    rows[^1].ReceiptTimestampUs,
                    _levelsPerSide,
                    finalFlush);
                AppendManifest(key.Day, record);
                Interlocked.Add(ref _bookEventRowsWritten, rows.Count);
                Interlocked.Increment(ref _bookEventFiles);
                lock (_statusGate)
                    _lastBookEventFile = finalPath;
                return true;
            }
            catch (Exception ex)
            {
                Interlocked.Increment(ref _bookEventWriteFailures);
                RecordError("write book events", ex);
                return false;
            }
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

        private async Task WriteBookEventFile(string path, List<BookEventRow> rows)
        {
            using var fs = new FileStream(path, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.Read);
            using var writer = await ParquetWriter.CreateAsync(_bookEventSchema, fs, append: false);
            writer.CompressionMethod = CompressionMethod.Snappy;
            for (int start = 0; start < rows.Count; start += BookEventRowGroupSize)
            {
                int count = Math.Min(BookEventRowGroupSize, rows.Count - start);
                using var rg = writer.CreateRowGroup();
                var receipt = new long[count];
                var exchange = new long[count];
                var sequence = new long[count];
                var subsequence = new int[count];
                var epoch = new long[count];
                var kind = new int[count];
                var side = new int[count];
                var priceTick = new long[count];
                var size = new double[count];
                var closed = new bool[count];
                var idHash = new long[count];
                var implied = new double[count];
                var priority = new long[count];
                var orders = new int[count];
                var resetItems = new int[count];
                var gapStart = new long[count];
                var gapEnd = new long[count];
                for (int offset = 0; offset < count; offset++)
                {
                    BookEventRow row = rows[start + offset];
                    receipt[offset] = row.ReceiptTimestampUs;
                    exchange[offset] = row.ExchangeTimestampUs;
                    sequence[offset] = row.Sequence;
                    subsequence[offset] = row.Subsequence;
                    epoch[offset] = row.ResetEpoch;
                    kind[offset] = row.EventKind;
                    side[offset] = row.Side;
                    priceTick[offset] = row.PriceTick;
                    size[offset] = row.Size;
                    closed[offset] = row.Closed;
                    idHash[offset] = row.QuoteIdHash;
                    implied[offset] = row.ImpliedSize;
                    priority[offset] = row.Priority;
                    orders[offset] = row.NumberOrders;
                    resetItems[offset] = row.ResetItemCount;
                    gapStart[offset] = row.GapStartSequence;
                    gapEnd[offset] = row.GapEndSequence;
                }
                int field = 0;
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], receipt));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], exchange));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], sequence));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], subsequence));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], epoch));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], kind));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], side));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], priceTick));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], size));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], closed));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], idHash));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], implied));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], priority));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], orders));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], resetItems));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], gapStart));
                await rg.WriteColumnAsync(new DataColumn(_bookEventSchema.DataFields[field++], gapEnd));
            }
        }

        private async Task ValidateParquet(string path, int expectedRows, string timestampField)
        {
            using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            using var reader = await ParquetReader.CreateAsync(fs);
            if (reader.RowGroupCount <= 0)
                throw new InvalidDataException("no row groups");
            var field = reader.Schema.DataFields.First(f => f.Name == timestampField);
            int actualRows = 0;
            for (int index = 0; index < reader.RowGroupCount; index++)
            {
                using var rg = reader.OpenRowGroupReader(index);
                var col = await rg.ReadColumnAsync(field);
                actualRows += col.Data?.Length ?? 0;
            }
            if (actualRows != expectedRows)
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
            string line = JsonSerializer.Serialize(record, _jsonOptions) + Environment.NewLine;
            WithFileRetry(() =>
            {
                using var fs = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
                using var writer = new StreamWriter(fs, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
                writer.Write(line);
            });
        }

        private void WriteStatusFile()
        {
            string tmp = null;
            try
            {
                UpdateBookTelemetry(DateTime.UtcNow);
                var status = GetStatus();
                status.NowUtc = DateTime.UtcNow.ToString("O");
                string json = JsonSerializer.Serialize(status, _jsonOptions);
                string path = StatusPath;
                tmp = path + ".tmp-" + _instanceId;
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                WithFileRetry(() => File.WriteAllText(tmp, json));
                WithFileRetry(() => File.Move(tmp, path, overwrite: true));
                tmp = null;
                lock (_statusGate)
                    _lastStatusUtc = DateTime.UtcNow;
            }
            catch (Exception ex)
            {
                if (!string.IsNullOrEmpty(tmp))
                {
                    try { File.Delete(tmp); } catch { }
                }
                RecordError("write status", ex);
            }
        }

        private void AcquireCaptureLock()
        {
            string path = Path.Combine(SymbolRoot, "capture.lock");
            try
            {
                _captureLockStream = new FileStream(
                    path,
                    FileMode.OpenOrCreate,
                    FileAccess.ReadWrite,
                    FileShare.Read);
                _captureLockStream.SetLength(0);
                string content =
                    $"symbol={_symbolKey}{Environment.NewLine}"
                    + $"pid={Environment.ProcessId}{Environment.NewLine}"
                    + $"startedUtc={DateTime.UtcNow:O}{Environment.NewLine}"
                    + $"version={Version}{Environment.NewLine}";
                byte[] bytes = Encoding.UTF8.GetBytes(content);
                _captureLockStream.Write(bytes, 0, bytes.Length);
                _captureLockStream.Flush(flushToDisk: true);
                _captureLockStream.Position = 0;
            }
            catch (IOException ex)
            {
                throw new InvalidOperationException(
                    $"another MarketRecorder instance is already writing {_symbolKey} under {SymbolRoot}",
                    ex);
            }
            catch (UnauthorizedAccessException ex)
            {
                throw new InvalidOperationException(
                    $"cannot acquire MarketRecorder capture lock for {_symbolKey} under {SymbolRoot}",
                    ex);
            }
        }

        private static void WithFileRetry(Action action)
        {
            for (int attempt = 1; ; attempt++)
            {
                try
                {
                    action();
                    return;
                }
                catch (IOException) when (attempt < FileRetryCount)
                {
                    Thread.Sleep(FileRetryBaseDelayMs * attempt);
                }
                catch (UnauthorizedAccessException) when (attempt < FileRetryCount)
                {
                    Thread.Sleep(FileRetryBaseDelayMs * attempt);
                }
            }
        }

        private void UpdateBookTelemetry(DateTime nowUtc)
        {
            lock (_statusGate)
            {
                if (_telemetryLastUtc == DateTime.MinValue)
                {
                    _telemetryLastUtc = nowUtc;
                    _telemetryLastCallbacks = Interlocked.Read(ref _bookCallbacksSeen);
                    _telemetryLastRows = Interlocked.Read(ref _bookEventRowsEnqueued);
                    return;
                }
                double elapsed = (nowUtc - _telemetryLastUtc).TotalSeconds;
                if (elapsed <= 0) return;
                long callbacks = Interlocked.Read(ref _bookCallbacksSeen);
                long rows = Interlocked.Read(ref _bookEventRowsEnqueued);
                _bookCallbackRatePerSec = Math.Max(0, callbacks - _telemetryLastCallbacks) / elapsed;
                _bookEventRowRatePerSec = Math.Max(0, rows - _telemetryLastRows) / elapsed;
                _telemetryLastCallbacks = callbacks;
                _telemetryLastRows = rows;
                _telemetryLastUtc = nowUtc;
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

        private ChunkKey ChunkFor(long tsUs, int chunkSeconds)
        {
            DateTime local = TimeZoneInfo.ConvertTimeFromUtc(UtcFromMicros(tsUs), _nyZone);
            var localMidnight = new DateTime(local.Year, local.Month, local.Day, 0, 0, 0, DateTimeKind.Unspecified);
            int secondOfDay = local.Hour * 3600 + local.Minute * 60 + local.Second;
            int seconds = Math.Max(10, Math.Min(1800, chunkSeconds));
            int startSecond = (secondOfDay / seconds) * seconds;
            DateTime startLocal = localMidnight.AddSeconds(startSecond);
            DateTime endExclusiveLocal = startLocal.AddSeconds(seconds);
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
            _pendingBookEventRows = _bookEventChunks.Values.Sum(x => x.Count);
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
            if (row is BookEventRow bookEvent) return bookEvent.ReceiptTimestampUs;
            return 0;
        }

        private static ParquetSchema BuildTickSchema()
            => new(
                new DataField<long>("timestamp_us"),
                new DataField<double>("price"),
                new DataField<double>("size"),
                new DataField<int>("aggressor_sign"),
                new DataField<string>("trade_id"),
                new DataField<string>("buyer"),
                new DataField<string>("seller"));

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

        private static ParquetSchema BuildBookEventSchema()
            => new(
                new DataField<long>("receipt_timestamp_us"),
                new DataField<long>("exchange_timestamp_us"),
                new DataField<long>("sequence"),
                new DataField<int>("subsequence"),
                new DataField<long>("reset_epoch"),
                new DataField<int>("event_kind"),
                new DataField<int>("side"),
                new DataField<long>("price_tick"),
                new DataField<double>("size"),
                new DataField<bool>("closed"),
                new DataField<long>("quote_id_hash"),
                new DataField<double>("implied_size"),
                new DataField<long>("priority"),
                new DataField<int>("number_orders"),
                new DataField<int>("reset_item_count"),
                new DataField<long>("gap_start_sequence"),
                new DataField<long>("gap_end_sequence"));

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

        private static long ExchangeMicros(DateTime exchangeTime, DateTime fallbackUtc)
            => ToMicros(exchangeTime == default ? fallbackUtc : exchangeTime.ToUniversalTime());

        private static long StableQuoteIdHash(string value)
        {
            if (string.IsNullOrEmpty(value)) return 0;
            unchecked
            {
                ulong hash = 14695981039346656037UL;
                foreach (char ch in value)
                {
                    hash ^= ch;
                    hash *= 1099511628211UL;
                }
                return (long)hash;
            }
        }

        private static DateTime UtcFromMicros(long us)
            => DateTime.UnixEpoch.AddTicks(us * 10);

        private static string IsoOrEmpty(long us)
            => us <= 0 ? "" : UtcFromMicros(us).ToString("O");

        private static string NormalizeText(string value)
            => string.IsNullOrWhiteSpace(value) ? "" : value.Trim();

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
            public string TradeId;
            public string Buyer;
            public string Seller;
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

        private enum BookEventKind
        {
            Delta = 1,
            ResetBegin = 2,
            ResetItem = 3,
            ResetEnd = 4,
            Gap = 5,
        }

        private sealed class BookEventRow
        {
            public long ReceiptTimestampUs;
            public long ExchangeTimestampUs;
            public long Sequence;
            public int Subsequence;
            public long ResetEpoch;
            public int EventKind;
            public int Side;
            public long PriceTick;
            public double Size;
            public bool Closed;
            public long QuoteIdHash;
            public double ImpliedSize;
            public long Priority;
            public int NumberOrders;
            public int ResetItemCount;
            public long GapStartSequence;
            public long GapEndSequence;

            public static BookEventRow Marker(
                BookEventKind kind,
                long sequence,
                int subsequence,
                long epoch,
                long receiptUs,
                long exchangeUs,
                int resetItemCount)
                => new()
                {
                    ReceiptTimestampUs = receiptUs,
                    ExchangeTimestampUs = exchangeUs,
                    Sequence = sequence,
                    Subsequence = subsequence,
                    ResetEpoch = epoch,
                    EventKind = (int)kind,
                    Side = 0,
                    PriceTick = long.MinValue,
                    Size = double.NaN,
                    ResetItemCount = resetItemCount,
                };

            public static BookEventRow Gap(
                long receiptUs,
                long sequence,
                long epoch,
                long gapStart,
                long gapEnd)
                => new()
                {
                    ReceiptTimestampUs = receiptUs,
                    ExchangeTimestampUs = receiptUs,
                    Sequence = sequence,
                    Subsequence = int.MaxValue,
                    ResetEpoch = epoch,
                    EventKind = (int)BookEventKind.Gap,
                    Side = 0,
                    PriceTick = long.MinValue,
                    Size = double.NaN,
                    GapStartSequence = gapStart,
                    GapEndSequence = gapEnd,
                };
        }

        private sealed class ManifestRecord
        {
            public int SchemaVersion { get; set; }
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
                    SchemaVersion = stream == "ticks" ? 2 : 1,
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
        public int BookEventChunkSeconds { get; set; }
        public bool TicksEnabled { get; set; }
        public bool SnapshotsEnabled { get; set; }
        public bool BookEventsEnabled { get; set; }
        public long TickRowsEnqueued { get; set; }
        public long TickRowsWritten { get; set; }
        public long TickFiles { get; set; }
        public long SnapshotRowsEnqueued { get; set; }
        public long SnapshotRowsWritten { get; set; }
        public long SnapshotFiles { get; set; }
        public long SnapshotSkips { get; set; }
        public int TickQueueRows { get; set; }
        public int SnapshotQueueRows { get; set; }
        public int BookEventQueueRows { get; set; }
        public int BookEventRowsWriting { get; set; }
        public long TickRowsDropped { get; set; }
        public long SnapshotRowsDropped { get; set; }
        public int QueueCapRows { get; set; }
        public int BookEventQueueCapRows { get; set; }
        public long BookEventQueueHighWaterRows { get; set; }
        public double BookCallbackRatePerSec { get; set; }
        public double BookEventRowRatePerSec { get; set; }
        public string LastTickUtc { get; set; }
        public string LastSnapshotUtc { get; set; }
        public string LastBookEventUtc { get; set; }
        public string LastBookResetUtc { get; set; }
        public string LastTickFile { get; set; }
        public string LastSnapshotFile { get; set; }
        public string LastBookEventFile { get; set; }
        public long TickWriteFailures { get; set; }
        public long SnapshotWriteFailures { get; set; }
        public long BookEventRowsEnqueued { get; set; }
        public long BookEventRowsWritten { get; set; }
        public long BookEventFiles { get; set; }
        public long BookEventRowsDropped { get; set; }
        public long BookEventWriteFailures { get; set; }
        public long BookCallbacksSeen { get; set; }
        public long BookCallbacksDropped { get; set; }
        public long BookDeltaCallbacks { get; set; }
        public long BookResetCallbacks { get; set; }
        public long BookSeedsCaptured { get; set; }
        public long BookContinuityGaps { get; set; }
        public long BookPreResetDeltas { get; set; }
        public long BookSequence { get; set; }
        public long BookResetEpoch { get; set; }
        public bool BookSeedRequired { get; set; }
        public bool BookGapPending { get; set; }
        public string BookState { get; set; }
        public string LastError { get; set; }
    }
}
