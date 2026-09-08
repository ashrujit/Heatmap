using System.Text.Json;
using System.Text.Json.Serialization;
using KahnRuntime;
using KahnRuntime.Scaling;

internal static class SessionReplay
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new JsonStringEnumConverter() },
    };
    private static DateTimeOffset Time(long micros) => DateTimeOffset.UnixEpoch.AddTicks(checked(micros * 10));
    private static void Write(StreamWriter writer, object row) => writer.WriteLine(JsonSerializer.Serialize(row, Json));

    public static void Run(string input, string output)
    {
        using var lines = File.ReadLines(input).GetEnumerator();
        if (!lines.MoveNext()) throw new ArgumentException("Missing session header");
        using var header = JsonDocument.Parse(lines.Current);
        var h = header.RootElement;
        CampaignSide side = h.GetProperty("side").GetString() == "long" ? CampaignSide.Long : CampaignSide.Short;
        var root = h.GetProperty("root");
        var rootRange = new PriceRange { Lower = root[0].GetDouble() * .25, Upper = root[1].GetDouble() * .25 };
        var start = Time(h.GetProperty("t").GetInt64());
        var plan = new CampaignPlan
        {
            SchemaVersion = 2, Id = "offline", Digest = "offline", Status = "active", Side = side,
            // Fixtures supplied no complete executable plan. This is an explicitly unbounded diagnostic arena, not a target.
            Arena = new() { Lower = 0, Upper = 1000000 },
            Window = new() { NotBefore = start.AddMinutes(-1), ExpiresAt = start.AddDays(1) },
            Sizing = new() { ProbeQuantity = 2, AddQuantity = 2, MaxPositionQuantity = 10, ScaleMode = CampaignScaleMode.EvidenceScaled },
            Policies = new(), Risk = new(), Execution = new(), Objective = new(),
            Waypoints = new[] { new CampaignWaypoint { Id = "root", Role = WaypointRole.TrapProbe, Range = rootRange } },
        };
        var state = CampaignState.ForPlan(plan);
        var session = new CampaignSession(plan, state, "offline", .25, TimeSpan.FromSeconds(5));
        session.Observer.StartEpoch(h.GetProperty("epoch").GetString(), start, h.GetProperty("price_ticks").GetDouble());
        using var writer = new StreamWriter(output);
        int adds = 0, operations = 0, peakQuantity = 0;
        string exit = null;
        bool began = false;
        while (lines.MoveNext())
        {
            using var doc = JsonDocument.Parse(lines.Current);
            var row = doc.RootElement;
            long t = row.GetProperty("t").GetInt64();
            DateTimeOffset at = Time(t);
            string op = row.GetProperty("op").GetString();
            double bid = row.GetProperty("bid_ticks").GetDouble(), ask = row.GetProperty("ask_ticks").GetDouble();
            double executable = side == CampaignSide.Long ? bid : ask;
            double fill = (side == CampaignSide.Long ? ask + 1 : bid - 1) * .25;
            var events = new List<CampaignEvidence>();
            if (op == "begin")
            {
                session.GoLive(new() { SchemaVersion = 2, CampaignId = plan.Id, CampaignDigest = plan.Digest,
                    RuntimeInstanceId = "offline", Attempt = 0, CreatedAt = at }, at);
                var key = row.GetProperty("key");
                var evidence = new CampaignEvidence { EventId = "seed", Timestamp = at, Source = EvidenceSource.LevelLedger,
                    Kind = EvidenceKind.RailOwned, Side = side == CampaignSide.Long ? EvidenceSide.Demand : EvidenceSide.Supply,
                    Range = rootRange, EvidenceEpoch = key.GetProperty("epoch").GetString(), RailId = key.GetProperty("rail_id").GetString() };
                var order = session.Reserve(new() { Action = PolicyAction.AllowProbe, Quantity = 2,
                    RiskAnchor = rootRange, RiskAnchorEvidenceId = "seed", EvidenceId = "seed" }, evidence, null, at);
                order.CarryLiveEvidence = row.GetProperty("warm").GetBoolean();
                session.Submitted(order, "seed", true, false);
                session.Report(order, 2, row.GetProperty("price_ticks").GetDouble() * .25, true, at, executable);
                began = true;
                Write(writer, new { kind = "root_proxy_fill", t, quantity = 2, state.SimulatedAveragePrice });
            }
            else if (op == "sample")
            {
                var transitions = row.GetProperty("events").EnumerateArray().Select(e =>
                {
                    var coverage = e.GetProperty("coverage");
                    var kind = Enum.Parse<EvidenceKind>(e.GetProperty("kind").GetString());
                    var eventSide = e.GetProperty("side").GetString() == "demand" ? CampaignSide.Long : CampaignSide.Short;
                    string rail = e.GetProperty("rail_id").GetString(), epoch = e.GetProperty("epoch").GetString();
                    events.Add(new() { EventId = $"{epoch}:{rail}:{kind}:{t}", Timestamp = at, Source = EvidenceSource.LevelLedger,
                        EvidenceEpoch = epoch, RailId = rail, Kind = kind,
                        Side = eventSide == CampaignSide.Long ? EvidenceSide.Demand : EvidenceSide.Supply,
                        Range = new() { Lower = coverage[0].GetDouble() * .25, Upper = coverage[1].GetDouble() * .25 },
                        Price = executable * .25 });
                    return new RepairTransition(new(EvidenceSource.LevelLedger, epoch, rail), kind, eventSide,
                        new(coverage[0].GetInt64(), coverage[1].GetInt64()));
                }).ToArray();
                session.Observe(new(EvidenceSource.LevelLedger, row.GetProperty("epoch").GetString(),
                    row.GetProperty("sequence").GetInt64(), at, executable, transitions, true));
            }
            else if (op == "price") session.Observer.ObservePrice(at, executable);
            else if (op == "gap") session.Observer.Suspend(at, "recorded_gap");
            else throw new ArgumentException("Unknown operation");
            operations++;
            events.Add(new() { EventId = "quote-" + t, Timestamp = at, Source = EvidenceSource.Price,
                Kind = EvidenceKind.PriceTouch, Price = executable * .25 });
            session.Sponsors?.Observe(session.Observer);
            if (began && state.HasPosition && !state.IsRetired)
            {
                if (state.BreakevenBackstopEligible(plan))
                {
                    double trigger = session.ProtectionPrice(state.SimulatedAveragePrice.Value);
                    bool touched = side == CampaignSide.Long ? bid * .25 <= trigger : ask * .25 >= trigger;
                    if (state.BreakevenBackstopActive && touched)
                    {
                        exit = "breakeven_proxy_exit";
                        state.ApplyDecision(new() { Action = PolicyAction.Retire }, plan, true, at);
                        Write(writer, new { kind = exit, t, trigger });
                    }
                    else if (!touched && (state.BreakevenBackstopActive || state.SimulatedPositionQuantity > plan.Sizing.ProbeQuantity))
                        state.ArmBreakevenBackstop(trigger, at);
                }
                var candidates = session.PolicyCandidates(events, at);
                var selected = candidates.OrderByDescending(x => x.Decision.Priority > 0 ? x.Decision.Priority
                    : DecisionResolver.PriorityFor(x.Decision.Action)).FirstOrDefault();
                bool veto = selected.Decision != null && (selected.Decision.Priority > 525
                    || selected.Decision.Action is PolicyAction.Flatten or PolicyAction.Retire or PolicyAction.Reduce
                        or PolicyAction.SuppressAdd or PolicyAction.PassiveHarvest or PolicyAction.TightenRisk or PolicyAction.Cooldown);
                if (veto && state.HasPosition)
                {
                    state.ApplyDecision(selected.Decision, plan, true, at);
                    Write(writer, new { kind = "policy", t, action = selected.Decision.Action, reason = selected.Decision.ReasonCode,
                        quantity = state.SimulatedPositionQuantity });
                    if (!state.HasPosition) exit = selected.Decision.ReasonCode;
                }
                if (session.Observer.Opportunity is { } opportunity && session.Reservations != null)
                {
                    var context = new ScaleAdmissionContext(at, Time(row.GetProperty("quote_t").GetInt64()),
                        TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(5), bid, ask, (state.SimulatedAveragePrice ?? 0) / .25,
                        state.SimulatedPositionQuantity, 2, 10, 10, state.ExecutionAuthorized, state.HasPosition,
                        !session.HasUnresolvedOrder, !veto && !state.IsRetired && !state.AddsSuppressed(at)
                            && (session.Sponsors.Active == null || session.Sponsors.ActiveHealth == GroupHealth.Live), false);
                    if (session.Reservations.TryReserve(opportunity, context, out var reserved, out var reason))
                    {
                        var order = session.Reserve(new() { Action = PolicyAction.AllowAdd, Policy = "repair_episode",
                            Quantity = reserved.RequestedQuantity, EvidenceId = reserved.Id }, events[^1], reserved, at);
                        session.Submitted(order, reserved.Id, true, false);
                        session.Report(order, order.Quantity, fill, true, at, executable);
                        adds++;
                        Write(writer, new { kind = "add_proxy_fill", t, episode = opportunity.EpisodeId, fill,
                            quantity = state.SimulatedPositionQuantity, average = state.SimulatedAveragePrice,
                            active = session.Sponsors.Active, pending = session.Sponsors.Pending });
                    }
                    else Write(writer, new { kind = "missed", t, episode = opportunity.EpisodeId, reason });
                }
            }
            peakQuantity = Math.Max(peakQuantity, state.SimulatedPositionQuantity);
            session.ConfirmFlat(at);
            foreach (var audit in session.Observer.DrainAudit()) Write(writer, new { kind = "audit", t, audit });
        }
        Write(writer, new { kind = "summary", adds, peak_quantity = peakQuantity,
            final_quantity = state.SimulatedPositionQuantity, exit, operations,
            retired = state.IsRetired, pending_group = session.Sponsors?.Pending, active_group = session.Sponsors?.Active,
            limitation = "counterfactual seeded root; BBO plus one-tick proxy fills; no supplied arena/target, no invented harvest; not broker execution or profitability" });
    }
}
