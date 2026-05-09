using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Parquet;
using Parquet.Data;
using Parquet.Schema;
using TradingPlatform.BusinessLayer;

namespace L2_Heatmap
{
    // Opt-in writer for L2 snapshots and trade ticks. Lives alongside the
    // heatmap so the depth and tape timelines are guaranteed aligned (single
    // capture point, single clock).
    //
    // Two parquet files per session day:
    //   captures/<SYMBOL>/snapshots-YYYY-MM-DD.parquet
    //   captures/<SYMBOL>/ticks-YYYY-MM-DD.parquet
    //
    // Snapshots are top-200 levels each side, flat-column schema (800 cols
    // total + ts + ref_tick). On NQ (tick=0.25), 200 levels = 50 price points
    // each side — sized for the depth-σ research surface, not just the
    // visible book. Bumped from 50→200 on 2026-05-09; captures from
    // 2026-05-04 → 2026-05-08 are early experimental data and not preserved
    // for combined reads under the new schema. Offsets are signed ticks from
    // ref_tick: bids negative, asks positive. Empty levels store offset=0,
    // size=0 (decoder skips zero-size). Compressed Snappy.
    //
    // Writer task batches every ~10s on a background thread to keep IO out of
    // the L2 drain loop on the UI thread.
    internal sealed class L2Capture : IDisposable
    {
        public const int LevelsPerSide = 200;
        private const int FlushPeriodSec = 10;

        private readonly string _captureRoot;
        private readonly string _symbolKey;
        private readonly int _retentionDays;

        private readonly ConcurrentQueue<SnapshotRow> _snapQueue = new();
        private readonly ConcurrentQueue<TickRow> _tickQueue = new();
        private CancellationTokenSource _cts;
        private Task _writerTask;
        private readonly ParquetSchema _snapSchema;
        private readonly ParquetSchema _tickSchema;

        public L2Capture(string captureRoot, string symbolKey, int retentionDays)
        {
            _captureRoot = captureRoot;
            _symbolKey = SanitizeForPath(symbolKey);
            _retentionDays = retentionDays;
            _snapSchema = BuildSnapshotSchema();
            _tickSchema = BuildTickSchema();
        }

        public void Start()
        {
            try { CleanupOldFiles(); } catch { /* non-fatal */ }
            try { Directory.CreateDirectory(Path.Combine(_captureRoot, _symbolKey)); }
            catch (Exception ex) { Log("create capture dir", ex); }
            _cts = new CancellationTokenSource();
            _writerTask = Task.Run(() => WriterLoop(_cts.Token));
        }

        public void EnqueueSnapshot(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            var row = BuildSnapshotRow(nowUtc, dom, tickSize);
            if (row != null) _snapQueue.Enqueue(row);
        }

        public void EnqueueTick(DateTime timeUtc, double price, double size, AggressorFlag flag)
        {
            int sign = flag == AggressorFlag.Buy ? 1 : (flag == AggressorFlag.Sell ? -1 : 0);
            _tickQueue.Enqueue(new TickRow
            {
                TimestampUs = ToMicros(timeUtc),
                Price = price,
                Size = size,
                AggressorSign = sign,
            });
        }

        public void Dispose()
        {
            try { _cts?.Cancel(); } catch { }
            try { _writerTask?.Wait(TimeSpan.FromSeconds(20)); } catch { }
            try { _cts?.Dispose(); } catch { }
            _writerTask = null;
            _cts = null;
        }

        // ---- writer loop ---------------------------------------------------

        private async Task WriterLoop(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try { await Task.Delay(TimeSpan.FromSeconds(FlushPeriodSec), ct); }
                catch (OperationCanceledException) { break; }
                try { await FlushSnapshots(); } catch (Exception ex) { Log("flush snapshots", ex); }
                try { await FlushTicks(); }     catch (Exception ex) { Log("flush ticks", ex); }
            }
            // Final drain on shutdown.
            try { await FlushSnapshots(); } catch (Exception ex) { Log("final flush snapshots", ex); }
            try { await FlushTicks(); }     catch (Exception ex) { Log("final flush ticks", ex); }
        }

        private bool _firstSnapFlushLogged;
        private bool _firstTickFlushLogged;

        private async Task FlushSnapshots()
        {
            var batch = DrainQueue(_snapQueue);
            if (batch.Count == 0) return;
            if (!_firstSnapFlushLogged)
            {
                _firstSnapFlushLogged = true;
                LogInfo($"first snapshot flush: {batch.Count} rows");
            }
            // Group by session day so a flush spanning a session boundary writes
            // each day's rows to its own file. Realistically this only matters
            // around the daily reset.
            foreach (var grp in batch.GroupBy(r => SessionDayKey(r.TimestampUs)))
            {
                var path = SnapshotPath(grp.Key);
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                bool exists = File.Exists(path);
                // FileShare.Read lets analysis tools (Polars / pandas) read the
                // file while live capture is still appending. Writer needs
                // ReadWrite for its own append flow.
                using var fs = new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.Read);
                fs.Seek(0, SeekOrigin.End);
                using var writer = await ParquetWriter.CreateAsync(_snapSchema, fs, append: exists);
                writer.CompressionMethod = CompressionMethod.Snappy;
                using var rg = writer.CreateRowGroup();
                await WriteSnapshotRowGroup(rg, grp.ToList());
            }
        }

        private async Task FlushTicks()
        {
            var batch = DrainQueue(_tickQueue);
            if (batch.Count == 0) return;
            if (!_firstTickFlushLogged)
            {
                _firstTickFlushLogged = true;
                LogInfo($"first tick flush: {batch.Count} rows");
            }
            foreach (var grp in batch.GroupBy(r => SessionDayKey(r.TimestampUs)))
            {
                var path = TickPath(grp.Key);
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                bool exists = File.Exists(path);
                // FileShare.Read lets analysis tools (Polars / pandas) read the
                // file while live capture is still appending. Writer needs
                // ReadWrite for its own append flow.
                using var fs = new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.Read);
                fs.Seek(0, SeekOrigin.End);
                using var writer = await ParquetWriter.CreateAsync(_tickSchema, fs, append: exists);
                writer.CompressionMethod = CompressionMethod.Snappy;
                using var rg = writer.CreateRowGroup();
                await WriteTickRowGroup(rg, grp.ToList());
            }
        }

        private static List<T> DrainQueue<T>(ConcurrentQueue<T> q)
        {
            var list = new List<T>(q.Count);
            while (q.TryDequeue(out var item)) list.Add(item);
            return list;
        }

        // ---- snapshot row ------------------------------------------------

        private SnapshotRow BuildSnapshotRow(DateTime nowUtc, DepthOfMarketAggregatedCollections dom, double tickSize)
        {
            if (dom == null) return null;
            var bids = dom.Bids ?? Array.Empty<Level2Item>();
            var asks = dom.Asks ?? Array.Empty<Level2Item>();
            if (bids.Length == 0 && asks.Length == 0) return null;

            long PriceToTicks(double p) => (long)Math.Round(p / tickSize);

            // Pick best-of-side from the first finite-price, size>0 level.
            // QT's DOM is normally clean, but this guards ref_tick against
            // any leak of NaN/zero levels (the synthesized L1-as-L2 class).
            double bbPrice = FirstValidPrice(bids);
            double baPrice = FirstValidPrice(asks);
            if (double.IsNaN(bbPrice) && double.IsNaN(baPrice)) return null;

            long refTick;
            if (!double.IsNaN(bbPrice) && !double.IsNaN(baPrice))
                refTick = (PriceToTicks(bbPrice) + PriceToTicks(baPrice)) / 2;
            else if (!double.IsNaN(bbPrice)) refTick = PriceToTicks(bbPrice);
            else refTick = PriceToTicks(baPrice);

            var row = new SnapshotRow
            {
                TimestampUs = ToMicros(nowUtc),
                RefTick = refTick,
                BidOffsets = new int[LevelsPerSide],
                BidSizes   = new double[LevelsPerSide],
                AskOffsets = new int[LevelsPerSide],
                AskSizes   = new double[LevelsPerSide],
            };

            // Pack valid levels front-to-back; invalid entries are skipped so
            // index 0 in the parquet output is always the real best.
            int outIdx = 0;
            for (int i = 0; i < bids.Length && outIdx < LevelsPerSide; i++)
            {
                double p = bids[i].Price;
                double s = bids[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(s) || s <= 0) continue;
                row.BidOffsets[outIdx] = (int)(PriceToTicks(p) - refTick); // negative
                row.BidSizes[outIdx]   = s;
                outIdx++;
            }
            outIdx = 0;
            for (int i = 0; i < asks.Length && outIdx < LevelsPerSide; i++)
            {
                double p = asks[i].Price;
                double s = asks[i].Size;
                if (!double.IsFinite(p) || p <= 0 || !double.IsFinite(s) || s <= 0) continue;
                row.AskOffsets[outIdx] = (int)(PriceToTicks(p) - refTick); // positive
                row.AskSizes[outIdx]   = s;
                outIdx++;
            }
            return row;
        }

        private static double FirstValidPrice(Level2Item[] arr)
        {
            if (arr == null) return double.NaN;
            for (int i = 0; i < arr.Length; i++)
            {
                double p = arr[i].Price;
                double s = arr[i].Size;
                if (double.IsFinite(p) && p > 0 && double.IsFinite(s) && s > 0) return p;
            }
            return double.NaN;
        }

        // ---- schema definitions ------------------------------------------

        private static ParquetSchema BuildSnapshotSchema()
        {
            var fields = new List<Field>
            {
                new DataField<long>("timestamp_us"),
                new DataField<long>("ref_tick"),
            };
            for (int i = 0; i < LevelsPerSide; i++)
            {
                fields.Add(new DataField<int>($"bid_offset_{i}"));
                fields.Add(new DataField<double>($"bid_size_{i}"));
            }
            for (int i = 0; i < LevelsPerSide; i++)
            {
                fields.Add(new DataField<int>($"ask_offset_{i}"));
                fields.Add(new DataField<double>($"ask_size_{i}"));
            }
            return new ParquetSchema(fields);
        }

        private static ParquetSchema BuildTickSchema()
        {
            return new ParquetSchema(
                new DataField<long>("timestamp_us"),
                new DataField<double>("price"),
                new DataField<double>("size"),
                new DataField<int>("aggressor_sign"));
        }

        // ---- row group writers -------------------------------------------

        private async Task WriteSnapshotRowGroup(ParquetRowGroupWriter rg, List<SnapshotRow> rows)
        {
            int n = rows.Count;
            var ts = new long[n];
            var rt = new long[n];
            for (int i = 0; i < n; i++) { ts[i] = rows[i].TimestampUs; rt[i] = rows[i].RefTick; }
            int idx = 0;
            await rg.WriteColumnAsync(new DataColumn(_snapSchema.DataFields[idx++], ts));
            await rg.WriteColumnAsync(new DataColumn(_snapSchema.DataFields[idx++], rt));
            // Bids
            for (int lvl = 0; lvl < LevelsPerSide; lvl++)
            {
                var off = new int[n]; var sz = new double[n];
                for (int i = 0; i < n; i++) { off[i] = rows[i].BidOffsets[lvl]; sz[i] = rows[i].BidSizes[lvl]; }
                await rg.WriteColumnAsync(new DataColumn(_snapSchema.DataFields[idx++], off));
                await rg.WriteColumnAsync(new DataColumn(_snapSchema.DataFields[idx++], sz));
            }
            // Asks
            for (int lvl = 0; lvl < LevelsPerSide; lvl++)
            {
                var off = new int[n]; var sz = new double[n];
                for (int i = 0; i < n; i++) { off[i] = rows[i].AskOffsets[lvl]; sz[i] = rows[i].AskSizes[lvl]; }
                await rg.WriteColumnAsync(new DataColumn(_snapSchema.DataFields[idx++], off));
                await rg.WriteColumnAsync(new DataColumn(_snapSchema.DataFields[idx++], sz));
            }
        }

        private async Task WriteTickRowGroup(ParquetRowGroupWriter rg, List<TickRow> rows)
        {
            int n = rows.Count;
            var ts = new long[n]; var px = new double[n]; var sz = new double[n]; var ag = new int[n];
            for (int i = 0; i < n; i++)
            {
                ts[i] = rows[i].TimestampUs; px[i] = rows[i].Price;
                sz[i] = rows[i].Size; ag[i] = rows[i].AggressorSign;
            }
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[0], ts));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[1], px));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[2], sz));
            await rg.WriteColumnAsync(new DataColumn(_tickSchema.DataFields[3], ag));
        }

        // ---- paths & cleanup --------------------------------------------

        private string SnapshotPath(string sessionDay)
            => Path.Combine(_captureRoot, _symbolKey, $"snapshots-{sessionDay}.parquet");

        private string TickPath(string sessionDay)
            => Path.Combine(_captureRoot, _symbolKey, $"ticks-{sessionDay}.parquet");

        private void CleanupOldFiles()
        {
            var dir = Path.Combine(_captureRoot, _symbolKey);
            if (!Directory.Exists(dir)) return;
            var cutoff = DateTime.UtcNow.AddDays(-_retentionDays);
            foreach (var f in Directory.EnumerateFiles(dir, "*.parquet"))
            {
                try
                {
                    if (File.GetLastWriteTimeUtc(f) < cutoff) File.Delete(f);
                }
                catch { /* skip locked / racy files */ }
            }
        }

        // ---- helpers -----------------------------------------------------

        private static string SessionDayKey(long tsUs)
        {
            var t = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddTicks(tsUs * 10);
            return t.ToString("yyyy-MM-dd");
        }

        private static long ToMicros(DateTime t)
            => (t.ToUniversalTime() - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).Ticks / 10;

        private static string SanitizeForPath(string s)
        {
            if (string.IsNullOrEmpty(s)) return "UNKNOWN";
            foreach (var ch in Path.GetInvalidFileNameChars()) s = s.Replace(ch, '_');
            return s;
        }

        private static void Log(string what, Exception ex)
        {
            try
            {
                Core.Instance.Loggers.Log($"[L2Capture] {what}: {ex.Message}", LoggingLevel.Error);
            }
            catch { }
        }

        private static void LogInfo(string msg)
        {
            try
            {
                Core.Instance.Loggers.Log($"[L2Capture] {msg}", LoggingLevel.System);
            }
            catch { }
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

        private struct TickRow
        {
            public long TimestampUs;
            public double Price;
            public double Size;
            public int AggressorSign;
        }
    }
}
