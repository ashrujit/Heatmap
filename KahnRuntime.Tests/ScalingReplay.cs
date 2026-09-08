using System.Text.Json;
using System.Text.Json.Serialization;
using KahnRuntime;
using KahnRuntime.Scaling;

internal static class ScalingReplay
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new JsonStringEnumConverter() },
    };

    public static void Run(string input, string output)
    {
        using var lines = File.ReadLines(input).GetEnumerator();
        if (!lines.MoveNext()) throw new ArgumentException("Missing replay header.");
        using var header = JsonDocument.Parse(lines.Current);
        var h = header.RootElement;
        var side = h.GetProperty("side").GetString() == "long" ? CampaignSide.Long : CampaignSide.Short;
        var root = Range(h.GetProperty("root"));
        var observer = new RepairEpisodeObserver(side, root, TimeSpan.FromSeconds(5));
        observer.StartEpoch(h.GetProperty("epoch").GetString(), Time(h.GetProperty("t").GetInt64()), h.GetProperty("price_ticks").GetDouble());
        using var writer = new StreamWriter(output);
        string lastOpportunity = null;
        int offered = 0, operations = 0;
        while (lines.MoveNext())
        {
            using var doc = JsonDocument.Parse(lines.Current);
            var row = doc.RootElement;
            long timestamp = row.GetProperty("t").GetInt64();
            var at = Time(timestamp);
            string operation = row.GetProperty("op").GetString();
            double price = row.TryGetProperty("price_ticks", out var p) ? p.GetDouble() : observer.LastPriceTicks;
            switch (operation)
            {
                case "begin":
                    observer.BeginAttempt(1, root, at, price, Key(row.GetProperty("key")), row.GetProperty("warm").GetBoolean());
                    break;
                case "sample":
                    var transitions = row.GetProperty("events").EnumerateArray().Select(e => new RepairTransition(
                        Key(e), Enum.Parse<EvidenceKind>(e.GetProperty("kind").GetString()),
                        e.GetProperty("side").GetString() == "demand" ? CampaignSide.Long : CampaignSide.Short,
                        Range(e.GetProperty("coverage")), e.TryGetProperty("formed_t", out var formed) && formed.ValueKind != JsonValueKind.Null
                            ? Time(formed.GetInt64()) : null)).ToArray();
                    observer.Observe(new(EvidenceSource.LevelLedger, row.GetProperty("epoch").GetString(),
                        row.GetProperty("sequence").GetInt64(), at, price, transitions, true));
                    break;
                case "price": observer.ObservePrice(at, price); break;
                case "gap": observer.Suspend(at, "recorded_observation_gap"); break;
                default: throw new ArgumentException($"Unknown replay operation {operation}");
            }
            operations++;
            var offer = observer.Opportunity;
            if (offer != null && offer.EpisodeId != lastOpportunity)
            {
                lastOpportunity = offer.EpisodeId;
                offered++;
                Write(writer, new
                {
                    kind = "offer", t = Micros(offer.At), episode = offer.EpisodeId,
                    price = observer.LastPriceTicks * .25,
                    support = offer.Proof.Members.Select(m => $"{m.Key.Epoch}:{m.Key.RailId}"),
                    coverage = offer.Proof.Coverage.Select(r => new[] { r.Lower * .25, r.Upper * .25 }),
                    forms = offer.Proof.Members.Select(m => m.Form.ToString()).Distinct(),
                    claims = offer.OpposingClaims.Select(k => $"{k.Epoch}:{k.RailId}"),
                    repair_resolved_t = Micros(offer.RepairResolvedAt),
                });
            }
            foreach (var audit in observer.DrainAudit())
                Write(writer, new { kind = "audit", t = Micros(audit.At), episode = audit.EpisodeId,
                    reason = audit.Reason, claim = audit.Claim?.ToString(), state = audit.TransitionState });
        }
        Write(writer, new { kind = "summary", offered, operations, suspended = observer.Suspended,
            suspension_reason = observer.SuspensionReason, known_claims = observer.KnownClaimCount });
    }

    private static DateTimeOffset Time(long micros) => DateTimeOffset.UnixEpoch.AddTicks(checked(micros * 10));
    private static long Micros(DateTimeOffset at) => (at.UtcTicks - DateTimeOffset.UnixEpoch.UtcTicks) / 10;
    private static TickInterval Range(JsonElement range) => new(range[0].GetInt64(), range[1].GetInt64());
    private static ClaimKey Key(JsonElement row) => new(EvidenceSource.LevelLedger,
        row.GetProperty("epoch").GetString(), row.GetProperty("rail_id").GetString());
    private static void Write(StreamWriter writer, object row) => writer.WriteLine(JsonSerializer.Serialize(row, Json));
}
