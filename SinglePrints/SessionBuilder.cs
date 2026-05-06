using System;
using System.Collections;
using System.Collections.Generic;

namespace SinglePrints
{
    // Pure logic — no Quantower types. Given bars in a single RTH session,
    // returns the single-print zones for that session.
    //
    // "Single print" = a tick price covered by exactly one bracket of the
    // session. Standard TPO / Market Profile concept. Contiguous tick prices
    // with that property are grouped into a Zone.
    internal static class SessionBuilder
    {
        public readonly struct Bar
        {
            public DateTime TimeUtc { get; }
            public double High { get; }
            public double Low { get; }
            public Bar(DateTime t, double h, double l) { TimeUtc = t; High = h; Low = l; }
        }

        // Computes zones for one RTH session.
        //   sessionStartUtc / sessionEndUtc: window the bars must fall inside.
        //   bracketSizeMin: TPO bracket length. 30 standard.
        //   tickSize: from Symbol.TickSize.
        //   minZoneTicks: filter — drop zones thinner than this. 1-tick singles
        //                 are usually noise from a single fast wick.
        //   excludeExtremes: if true, zones touching session high/low are dropped
        //                    (they represent "where the day stopped", not actionable
        //                    unfinished business in standard market-profile reading).
        //
        // Each zone's FormedAtUtc is set to the END of the latest bracket among
        // the zone's tick-brackets — i.e., the moment the zone became fully
        // structurally confirmed. A zone whose ticks were only touched in
        // bracket A has FormedAtUtc = end of A, regardless of how late in the
        // day the computation runs. This matters for the trader's read of how
        // price subsequently interacted with the zone (e.g., A's single prints
        // tested by a B-period retrace).
        //
        // sessionMinPrice / sessionMaxPrice are populated from the bars walked,
        // for caller's use (cross-session "filled" check).
        public static List<Zone> ComputeZones(
            IEnumerable<Bar> sessionBars,
            DateTime sessionStartUtc,
            DateTime sessionEndUtc,
            DateTime sessionDateNy,
            int bracketSizeMin,
            double tickSize,
            int minZoneTicks,
            bool excludeExtremes,
            out double sessionLow,
            out double sessionHigh)
        {
            sessionLow = double.PositiveInfinity;
            sessionHigh = double.NegativeInfinity;

            int totalBrackets = Math.Max(1, (int)Math.Ceiling(
                (sessionEndUtc - sessionStartUtc).TotalMinutes / bracketSizeMin));

            var coverage = new Dictionary<long, BitArray>();
            long sessionMinTick = long.MaxValue, sessionMaxTick = long.MinValue;

            foreach (var bar in sessionBars)
            {
                if (bar.TimeUtc < sessionStartUtc || bar.TimeUtc >= sessionEndUtc) continue;
                int bracketIdx = (int)((bar.TimeUtc - sessionStartUtc).TotalMinutes / bracketSizeMin);
                if (bracketIdx < 0 || bracketIdx >= totalBrackets) continue;
                if (double.IsNaN(bar.High) || double.IsNaN(bar.Low)) continue;

                long lowTick = (long)Math.Round(bar.Low / tickSize);
                long highTick = (long)Math.Round(bar.High / tickSize);
                if (lowTick > highTick) continue;

                if (lowTick < sessionMinTick) sessionMinTick = lowTick;
                if (highTick > sessionMaxTick) sessionMaxTick = highTick;

                for (long t = lowTick; t <= highTick; t++)
                {
                    if (!coverage.TryGetValue(t, out var ba))
                    {
                        ba = new BitArray(totalBrackets);
                        coverage[t] = ba;
                    }
                    ba.Set(bracketIdx, true);
                }
            }

            if (sessionMinTick == long.MaxValue) return new List<Zone>();

            sessionLow = sessionMinTick * tickSize;
            sessionHigh = sessionMaxTick * tickSize;

            // Single prints: tickKeys with exactly one bracket touched.
            var singlePrints = new List<long>();
            foreach (var kv in coverage)
            {
                int count = 0;
                var ba = kv.Value;
                for (int i = 0; i < ba.Count; i++) if (ba[i]) { count++; if (count > 1) break; }
                if (count == 1) singlePrints.Add(kv.Key);
            }
            singlePrints.Sort();

            // Group contiguous tickKeys into zones.
            var zones = new List<Zone>();
            if (singlePrints.Count == 0) return zones;

            // Local emit closes over coverage / sessionStartUtc / bracketSizeMin
            // so it can compute per-zone FormedAtUtc from the zone's latest
            // tick-bracket. Avoids a longer parameter list at the call site.
            void Emit(long bottomTick, long topTick)
            {
                int height = (int)(topTick - bottomTick + 1);
                if (height < minZoneTicks) return;
                // Extreme exclusion: a zone whose bottom equals the session low
                // or whose top equals the session high is "where the day stopped"
                // — not unfinished business in TPO terms, just a turn point.
                if (excludeExtremes && (bottomTick <= sessionMinTick || topTick >= sessionMaxTick))
                    return;

                // Find latest bracket idx among the zone's ticks. Each tick is
                // single-print so it has exactly one bit set in its BitArray.
                int maxBracketIdx = -1;
                for (long t = bottomTick; t <= topTick; t++)
                {
                    if (!coverage.TryGetValue(t, out var ba)) continue;
                    for (int b = ba.Count - 1; b >= 0; b--)
                    {
                        if (ba[b]) { if (b > maxBracketIdx) maxBracketIdx = b; break; }
                    }
                }
                DateTime formedAt = maxBracketIdx >= 0
                    ? sessionStartUtc.AddMinutes((maxBracketIdx + 1) * bracketSizeMin)
                    : sessionEndUtc;

                zones.Add(new Zone
                {
                    TopTick = topTick,
                    BottomTick = bottomTick,
                    SessionDateNy = sessionDateNy,
                    FormedAtUtc = formedAt,
                    TopPrice = topTick * tickSize,
                    BottomPrice = bottomTick * tickSize,
                });
            }

            long zoneBottom = singlePrints[0];
            long zoneTop = singlePrints[0];
            for (int i = 1; i < singlePrints.Count; i++)
            {
                long t = singlePrints[i];
                if (t == zoneTop + 1) zoneTop = t;
                else { Emit(zoneBottom, zoneTop); zoneBottom = t; zoneTop = t; }
            }
            Emit(zoneBottom, zoneTop);

            return zones;
        }
    }

    internal sealed class Zone
    {
        public long TopTick;
        public long BottomTick;
        public DateTime SessionDateNy;     // NY-local session date the zone was formed in
        public DateTime FormedAtUtc;        // when it became visible (session end, or last recompute for active session)
        public double TopPrice;
        public double BottomPrice;
        public bool Filled;                  // dropped from rendering when true
    }
}
