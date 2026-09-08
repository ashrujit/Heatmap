using System.Globalization;
using System.Text.Json;
using KahnRuntime;
using Ll = KahnRuntime.LiveEvidence;

internal static class Program
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private static int Main(string[] args)
    {
        try
        {
            if (args[0] == "rails") Rails(args);
            else if (args[0] == "policy") Policy(args);
            else throw new ArgumentException("Expected rails or policy.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex);
            return 1;
        }
    }

    private static DateTime Time(long us) => DateTime.UnixEpoch.AddTicks(us * 10);
    private static void Write(StreamWriter writer, object value)
        => writer.WriteLine(JsonSerializer.Serialize(value, Json));

    private static Ll.DepthLevelSnapshot[] Levels(JsonElement root, string name)
        => root.GetProperty(name).EnumerateArray().Select(level => new Ll.DepthLevelSnapshot
        {
            Price = level[0].GetDouble(),
            Size = level[1].GetDouble(),
        }).ToArray();

    private static void Rails(string[] args)
    {
        var settings = new Ll.EvidenceEngineSettings
        {
            ClusterTicks = int.Parse(args[3], CultureInfo.InvariantCulture),
            FailureConfirmTicks = int.Parse(args[4], CultureInfo.InvariantCulture),
            FailureSeconds = int.Parse(args[5], CultureInfo.InvariantCulture),
        };
        var engine = new Ll.ExecutionEvidenceEngine(0.25, settings);
        long last = 0, epochStart = 0;
        int epoch = 0, sampleCount = 0, ordinal = 0;
        using var writer = new StreamWriter(args[2]);
        using var lineage = args.Length > 6 ? new StreamWriter(args[6]) : null;
        foreach (string line in File.ReadLines(args[1]))
        {
            using JsonDocument doc = JsonDocument.Parse(line);
            JsonElement row = doc.RootElement;
            long us = row.GetProperty("t").GetInt64();
            if (last == 0 || us - last > 5_000_000)
            {
                epoch++;
                epochStart = us;
                sampleCount = 0;
                engine = new Ll.ExecutionEvidenceEngine(0.25, settings);
                Write(writer, new { t = us, epoch, order = ordinal++, kind = "Reset",
                    gap_sec = last == 0 ? 0 : (us - last) / 1_000_000.0 });
            }
            last = us;
            sampleCount++;
            var depth = new Ll.BookDepthSnapshot
            {
                TimeUtc = Time(us), Bids = Levels(row, "bids"), Asks = Levels(row, "asks"),
            };
            foreach (Ll.EvidenceTransition transition in engine.Process(depth))
            {
                if (transition.Band?.Role != Ll.EvidenceRole.Rail) continue;
                var band = transition.Band;
                if (lineage != null && transition.Kind == Ll.EvidenceTransitionKind.RailOwned)
                {
                    Write(lineage, new
                    {
                        t = us, id = $"{epoch}:{band.Id}", side = band.Side.ToString().ToLowerInvariant(),
                        source_side = band.SourceSide.ToString().ToLowerInvariant(), source = band.Source.ToString(),
                        formed_t = (band.FormedUtc.Ticks - DateTime.UnixEpoch.Ticks) / 10,
                        owned_t = (band.OwnedUtc.Ticks - DateTime.UnixEpoch.Ticks) / 10,
                        direction_started_t = transition.Candidate?.DirectionStartedUtc.HasValue == true
                            ? (long?)((transition.Candidate.DirectionStartedUtc.Value.Ticks - DateTime.UnixEpoch.Ticks) / 10)
                            : null,
                        event_count = band.EventCount,
                    });
                }
                Write(writer, new
                {
                    t = us, epoch, order = ordinal++, kind = transition.Kind.ToString(),
                    id = $"{epoch}:{band.Id}", side = band.Side.ToString().ToLowerInvariant(),
                    source = band.Source.ToString(), lo = band.MinTick * .25,
                    hi = band.MaxTick * .25, price = transition.CurrentMidTick * .25,
                    score = band.Score, reason = transition.Reason,
                    ready = sampleCount >= 30 && us - epochStart >= 30_000_000,
                });
            }
        }
    }

    private static PriceRange Range(JsonElement root, string name)
    {
        JsonElement value = root.GetProperty(name);
        return new PriceRange { Lower = value[0].GetDouble(), Upper = value[1].GetDouble() };
    }

    private static object State(CampaignState state) => new
    {
        quantity = state.SimulatedPositionQuantity,
        accepted_adds = state.AcceptedAddCount, average = state.SimulatedAveragePrice,
        root = state.RootRiskAnchor, active = state.ActiveRiskAnchor,
        pending = state.PendingSponsorAnchor, pending_id = state.PendingSponsorEvidenceId,
        candidate = state.ScaleCandidateAnchor, candidate_id = state.ScaleCandidateEvidenceId,
        repair = state.ScaleRepairAnchor, repair_id = state.ScaleRepairEvidenceId,
        candidate_at = state.ScaleCandidateTrackedAt, repair_at = state.ScaleRepairTrackedAt,
        failed = state.ScaleRepairFailed, failed_at = state.ScaleRepairFailedAt,
        suppressed_until = state.SuppressAddsUntil,
        phase = state.Phase.ToString(),
    };

    private static void Policy(string[] args)
    {
        using JsonDocument configDoc = JsonDocument.Parse(File.ReadAllText(args[1]));
        JsonElement cfg = configDoc.RootElement;
        long start = cfg.GetProperty("seed_t").GetInt64();
        int seedOrder = cfg.GetProperty("seed_order").GetInt32();
        long end = cfg.GetProperty("end_t").GetInt64();
        var side = cfg.GetProperty("side").GetString() == "long" ? CampaignSide.Long : CampaignSide.Short;
        var waypoints = new List<CampaignWaypoint>();
        if (cfg.TryGetProperty("no_add", out JsonElement noAdd))
            waypoints.Add(new CampaignWaypoint { Id = "no-add", Role = WaypointRole.NoAdd,
                Range = Range(cfg, "no_add") });
        var plan = new CampaignPlan
        {
            Id = "research-seeded", Status = "active", Side = side,
            Window = new CampaignWindow { NotBefore = Time(start), ExpiresAt = Time(end) },
            Arena = Range(cfg, "arena"),
            Sizing = new CampaignSizing { ProbeQuantity = 2, AddQuantity = 2,
                MaxPositionQuantity = cfg.TryGetProperty("max_quantity", out JsonElement maxQuantity)
                    ? maxQuantity.GetInt32() : 10, ScaleMode = CampaignScaleMode.EvidenceScaled },
            Risk = new CampaignRisk(), Execution = new CampaignExecution(),
            Objective = new CampaignObjective(), Policies = new CampaignPolicyFlags(),
            Waypoints = waypoints,
        };
        using var writer = new StreamWriter(args[3]);
        PolicyScenario(cfg, plan, args[2], writer, "none", null, start, end, seedOrder);
        if (cfg.TryGetProperty("gates", out JsonElement gates))
            foreach (JsonProperty gate in gates.EnumerateObject())
                PolicyScenario(cfg, plan, args[2], writer, gate.Name,
                    gate.Value.EnumerateArray().Select(v => v.GetInt32()).ToHashSet(),
                    start, end, seedOrder);
    }

    private static void PolicyScenario(JsonElement cfg, CampaignPlan plan, string eventsPath,
        StreamWriter writer, string scenario, HashSet<int> allowedOrders,
        long start, long end, int seedOrder)
    {
        var state = CampaignState.ForPlan(plan);
        state.ApplyDecision(new PolicyDecision { Action = PolicyAction.AllowProbe,
            Quantity = 2, RiskAnchor = Range(cfg, "root"), EvidenceId = "research-root" },
            plan, true, Time(start), simulatedFillPrice: cfg.GetProperty("root_price").GetDouble());
        var engine = CampaignPolicyEngine.CreateDefault();
        bool full = cfg.TryGetProperty("full_campaign", out JsonElement fullValue) && fullValue.GetBoolean();
        string variant = cfg.TryGetProperty("state_variant", out JsonElement variantValue)
            ? variantValue.GetString() : "current";
        bool jointVariant = variant is "cycle_joint" or "cycle_joint_zone" or "cycle_joint_range";
        var cycleObserver = jointVariant
            ? new CycleObserver(start, variant == "cycle_joint_zone", variant == "cycle_joint_range") : null;
        foreach (string line in File.ReadLines(eventsPath))
        {
            using JsonDocument eventDoc = JsonDocument.Parse(line);
            JsonElement row = eventDoc.RootElement;
            long t = row.GetProperty("t").GetInt64();
            int order = row.GetProperty("order").GetInt32();
            if (t < start || (t == start && order <= seedOrder)) continue;
            if (t > end) break;
            string kind = row.GetProperty("kind").GetString();
            if (kind == "Reset")
            {
                Write(writer, new { t, order, scenario, action = "Censored", reason = "evidence_gap", emitted = false });
                break;
            }
            if (!row.GetProperty("ready").GetBoolean()) continue;
            var evidence = new CampaignEvidence
            {
                Timestamp = Time(t), EventId = $"research-{order}",
                RailId = row.GetProperty("id").GetString(),
                Kind = Enum.Parse<EvidenceKind>(kind), Source = EvidenceSource.LevelLedger,
                Side = row.GetProperty("side").GetString() == "demand" ? EvidenceSide.Demand : EvidenceSide.Supply,
                Price = row.GetProperty("price").GetDouble(),
                Range = new PriceRange { Lower = row.GetProperty("lo").GetDouble(), Upper = row.GetProperty("hi").GetDouble() },
            };
            object before = State(state);
            var context = new CampaignContext(plan, state, .25, Time(t));
            var pressOffers = new PressPolicy().Evaluate(context, evidence)
                .Select(d => new { action = d.Action.ToString(), reason = d.ReasonCode, priority = d.Priority }).ToArray();
            var decision = engine.Evaluate(context, evidence);
            PolicyDecision joint = cycleObserver?.Observe(context, evidence);
            if (cycleObserver != null)
            {
                if (decision.Action == PolicyAction.AllowAdd)
                    decision = PolicyDecision.None("research_cycle", evidence);
                decision = DecisionResolver.Resolve(new[] { decision, joint }
                    .Where(d => d != null), evidence);
            }
            bool vetoed = decision.Action == PolicyAction.AllowAdd
                && allowedOrders != null && !allowedOrders.Contains(order);
            bool emitted = !vetoed && state.ShouldEmit(decision, Time(t), TimeSpan.FromSeconds(5));
            bool tracking = decision.Action == PolicyAction.TrackScaleCandidate
                && decision.ReasonCode.StartsWith("scale_candidate_tracked", StringComparison.Ordinal);
            PriceRange reference = state.ScaleCandidateAnchor ?? state.PendingSponsorAnchor
                ?? state.ActiveRiskAnchor ?? state.RootRiskAnchor;
            bool advancing = tracking && (reference == null || CampaignSideMath.IsFavorableBeyond(
                plan.Side, decision.ChildRiskAnchor, reference));
            bool preserve = tracking && (variant == "preserve_all" || jointVariant
                || (variant == "preserve_noop" && !advancing));
            // Research intervention only: the production state still performs candidate tracking.
            var applied = preserve ? new PolicyDecision
            {
                Action = decision.Action, Policy = decision.Policy,
                ReasonCode = "research_preserve_repair", Priority = decision.Priority,
                EvidenceId = decision.EvidenceId, WaypointId = decision.WaypointId,
                RiskAnchor = decision.RiskAnchor, RiskAnchorEvidenceId = decision.RiskAnchorEvidenceId,
                ChildRiskAnchor = decision.ChildRiskAnchor,
                ChildRiskAnchorEvidenceId = decision.ChildRiskAnchorEvidenceId,
            } : decision;
            if (emitted) state.ApplyDecision(applied, plan, true, Time(t), simulatedFillPrice: evidence.Price);
            object cycleBeforeConsumption = cycleObserver?.Describe();
            if (emitted && decision.Action == PolicyAction.AllowAdd)
                cycleObserver?.Consume(Time(t));
            Write(writer, new { t, order, scenario, action = decision.Action.ToString(),
                reason = decision.ReasonCode, emitted, vetoed, preserved_repair = preserve,
                press_offers = pressOffers, cycle = cycleBeforeConsumption, before, after = State(state) });
            if (!full && emitted && decision.Action is PolicyAction.AllowAdd or PolicyAction.Flatten or PolicyAction.Retire)
                break;
        }
    }

    private sealed class CycleObserver
    {
        private readonly Dictionary<string, CampaignEvidence> _rails = new();
        private CampaignEvidence _claim;
        private DateTimeOffset _lastAdd;
        private DateTimeOffset? _claimStarted, _failed;
        private CampaignEvidence _chosen;
        private readonly bool _requireClearZone;
        private readonly bool _requireProofThroughClaim;

        public CycleObserver(long seed, bool requireClearZone, bool requireProofThroughClaim)
        {
            _lastAdd = Time(seed);
            _requireClearZone = requireClearZone;
            _requireProofThroughClaim = requireProofThroughClaim;
        }

        public object Describe() => new
        {
            claim_id = _claim?.RailId, claim = _claim?.Range,
            claim_started = _claimStarted, failed_at = _failed,
            chosen_id = _chosen?.RailId, chosen_at = _chosen?.Timestamp,
        };

        public void Consume(DateTimeOffset time)
        {
            _lastAdd = time;
            _claim = null;
            _claimStarted = null;
            _failed = null;
            _chosen = null;
        }

        public PolicyDecision Observe(CampaignContext context, CampaignEvidence e)
        {
            _chosen = null;
            if (e.Kind == EvidenceKind.RailFailed) _rails.Remove(e.RailId);
            else _rails[e.RailId] = e;
            var state = context.State;
            if (!state.HasPosition || state.IsRetired || state.ExecutionPaused) return null;
            bool confirmed = e.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld;
            bool same = CampaignSideMath.IsSameSide(context.Plan.Side, e.Side);
            PriceRange reference = state.PendingSponsorAnchor ?? state.ActiveRiskAnchor ?? state.RootRiskAnchor;
            if (reference == null) return null;
            if (confirmed && !same && CampaignSideMath.IsFavorableBeyond(context.Plan.Side, e.Range, reference))
            {
                if (_claim?.RailId != e.RailId || _failed.HasValue)
                {
                    _claimStarted = e.Timestamp;
                    _failed = null;
                }
                _claim = e;
                return null;
            }
            if (_claim == null) return null;
            bool claimFailure = e.Kind == EvidenceKind.RailFailed && e.RailId == _claim.RailId;
            if (claimFailure) _failed = e.Timestamp;
            bool companionFailure = !same && e.Kind == EvidenceKind.RailFailed
                && e.Range.DistanceTicksTo(_claim.Range, context.TickSize) <= 2;
            if (!_failed.HasValue || !(claimFailure || (same && confirmed) || (_requireClearZone && companionFailure))) return null;
            if (_requireClearZone && _rails.Values.Any(p =>
                CampaignSideMath.IsOppositeSide(context.Plan.Side, p.Side)
                && p.Range.DistanceTicksTo(_claim.Range, context.TickSize) <= 2)) return null;
            if (state.SimulatedPositionQuantity >= context.Plan.Sizing.MaxPositionQuantity) return null;
            bool BeyondPrice(PriceRange r) => context.Plan.Side == CampaignSide.Long
                ? e.Price > r.Upper : e.Price < r.Lower;
            if (!BeyondPrice(_claim.Range)) return null;
            // A live advancing proof may precede the formal counter-claim. TEST suspends it.
            _chosen = _rails.Values.Where(p => p.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld)
                .Where(p => CampaignSideMath.IsSameSide(context.Plan.Side, p.Side)
                    && p.Timestamp > _lastAdd
                    && CampaignSideMath.IsFavorableBeyond(context.Plan.Side, p.Range, reference)
                    && BeyondPrice(p.Range))
                .Where(p => !_requireProofThroughClaim || p.Range.Intersects(_claim.Range)
                    || CampaignSideMath.IsFavorableBeyond(context.Plan.Side, p.Range, _claim.Range))
                .OrderByDescending(p => p.Timestamp).FirstOrDefault();
            if (_chosen == null) return null;
            return new PolicyDecision
            {
                Action = PolicyAction.AllowAdd, Policy = "research_cycle_joint",
                ReasonCode = "typed_repair_failed_with_surviving_advancing_proof",
                Priority = DecisionResolver.PriorityFor(PolicyAction.HoldRoot) + 25,
                Quantity = Math.Min(context.Plan.Sizing.AddQuantity,
                    context.Plan.Sizing.MaxPositionQuantity - state.SimulatedPositionQuantity),
                RiskAnchor = state.ActiveRiskAnchor ?? state.RootRiskAnchor,
                RiskAnchorEvidenceId = state.ActiveRiskAnchorEvidenceId ?? state.RootRiskAnchorEvidenceId,
                ChildRiskAnchor = _chosen.Range, ChildRiskAnchorEvidenceId = _chosen.EventId,
                DelayRiskAnchorPromotionOnAdd = true, EvidenceId = e.EventId,
            };
        }
    }
}
