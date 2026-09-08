using System;
using System.Collections.Generic;
using System.Linq;

namespace KahnRuntime.Scaling
{
    internal sealed class RepairEpisodeObserver
    {
        private sealed class Episode
        {
            public string Id;
            public DateTimeOffset StartedAt;
            public DateTimeOffset? ResolvedAt;
            public double Peak;
            public double Adverse;
            public double ObservedFront;
            public bool Breached;
            public RepairStage Stage = RepairStage.RepairActive;
            public string Outcome;
            public HashSet<ClaimKey> Members = new();
            public HashSet<ClaimKey> Attacked = new();
            public HashSet<ClaimKey> Claims = new();
            public IReadOnlyList<TickInterval> ResolutionArea;
            public bool Offered;
        }

        private readonly Dictionary<ClaimKey, ClaimSnapshot> _claims = new();
        private readonly HashSet<ClaimKey> _forming = new();
        private readonly HashSet<ClaimKey> _carried = new();
        private readonly HashSet<ClaimKey> _developmentSeeds = new();
        private readonly HashSet<string> _usedEpochs = new(StringComparer.Ordinal);
        private readonly List<RepairAudit> _audit = new();
        private readonly TimeSpan _maximumSampleGap;
        private Episode _episode;
        private TickInterval _root;
        private DateTimeOffset _boundary;
        private double _peak;
        private long _episodeNumber;
        private long _lastSequence = -1;
        private RepairSample _lastSample;
        private ScaleOpportunity _opportunity;
        private bool _opportunityUsable;
        private bool _attemptActive;

        public CampaignSide Side { get; }
        public string Epoch { get; private set; }
        public long Generation { get; private set; }
        public long Attempt { get; private set; }
        public bool Suspended { get; private set; } = true;
        public string SuspensionReason { get; private set; } = "epoch_not_started";
        public DateTimeOffset LastObservedAt { get; private set; }
        public DateTimeOffset LastCompleteSampleAt { get; private set; }
        public double LastPriceTicks { get; private set; } = double.NaN;
        public ScaleOpportunity Opportunity => _opportunityUsable ? _opportunity : null;
        public RepairEpisodeSnapshot CurrentEpisode => Snapshot(_episode);
        public RepairEpisodeSnapshot LastClosedEpisode { get; private set; }
        public int KnownClaimCount => _claims.Count;
        public RepairStage Stage => Suspended ? RepairStage.Suspended
            : _episode?.Stage ?? (Opportunity == null ? RepairStage.Building
                : LastClosedEpisode?.Id == Opportunity.EpisodeId ? LastClosedEpisode.Stage : RepairStage.Eligible);
        public bool FreshAt(DateTimeOffset at) => !Suspended && LastCompleteSampleAt != default
            && at >= LastObservedAt && at - LastCompleteSampleAt <= _maximumSampleGap;

        public RepairEpisodeObserver(CampaignSide side, TickInterval rootArea, TimeSpan maximumSampleGap)
        {
            if (!rootArea.IsValid || !Enum.IsDefined(side) || maximumSampleGap <= TimeSpan.Zero)
                throw new ArgumentException("Invalid side, root area or sample health limit.");
            Side = side;
            _root = rootArea;
            _maximumSampleGap = maximumSampleGap;
        }

        public IReadOnlyList<RepairAudit> DrainAudit()
        {
            RepairAudit[] result = _audit.ToArray();
            _audit.Clear();
            return Array.AsReadOnly(result);
        }

        public ClaimSnapshot Find(ClaimKey key)
            => !Suspended && key.Epoch == Epoch && _claims.TryGetValue(key, out var claim)
                ? claim : null;

        public void StartEpoch(string epoch, DateTimeOffset at, double priceTicks)
        {
            if (string.IsNullOrWhiteSpace(epoch) || _usedEpochs.Contains(epoch) || !ValidPrice(priceTicks)
                || at == default || at < LastObservedAt)
                throw new ArgumentException("Recovery requires a new epoch and a current finite price.");
            Suspend(at, "epoch_reset");
            Epoch = epoch;
            _usedEpochs.Add(epoch);
            Generation++;
            _claims.Clear();
            _forming.Clear();
            _carried.Clear();
            _developmentSeeds.Clear();
            _lastSample = null;
            _lastSequence = -1;
            LastCompleteSampleAt = default;
            LastObservedAt = _boundary = at;
            LastPriceTicks = priceTicks;
            _peak = Orient(priceTicks);
            Suspended = false;
            SuspensionReason = null;
            Audit(at, "epoch_started");
        }

        public void Suspend(DateTimeOffset at, string reason)
        {
            InvalidateOpportunity(at, reason);
            if (_episode != null)
            {
                _episode.Stage = RepairStage.Suspended;
                Close(at, reason);
            }
            Suspended = true;
            SuspensionReason = reason;
            Audit(at, reason);
        }

        public void BeginAttempt(long attempt, TickInterval rootArea,
            DateTimeOffset fillAt, double fillPriceTicks, ClaimKey? rootKey = null,
            bool carryLiveEvidence = true)
        {
            if (Suspended || attempt <= Attempt || !rootArea.IsValid
                || fillAt < LastObservedAt || !ValidPrice(fillPriceTicks))
                throw new ArgumentException("An attempt needs a fresh fill and a ready evidence epoch.");
            InvalidateOpportunity(fillAt, "new_attempt");
            if (_episode != null)
                Close(fillAt, "new_attempt");
            Attempt = attempt;
            _attemptActive = true;
            Generation++;
            _root = rootArea;
            _boundary = fillAt;
            _peak = Orient(fillPriceTicks);
            LastObservedAt = fillAt;
            LastPriceTicks = fillPriceTicks;
            _forming.Clear();
            _carried.Clear();
            _developmentSeeds.Clear();
            foreach (var claim in _claims.Values.Where(x => carryLiveEvidence
                && x.Side == Side && x.Confirmed))
                _forming.Add(claim.Key);
            if (rootKey.HasValue && Find(rootKey.Value) is { Confirmed: true } root && root.Side == Side)
                _carried.Add(root.Key);

            // Carry live challenges only. Completed WATCH failures never grant an add.
            if (carryLiveEvidence)
                foreach (var claim in _claims.Values.Where(x => x.Side != Side
                    && x.FailedAt == null && Relevant(x.Coverage)))
                {
                    Open(fillAt, "inherited_live_claim");
                    _episode.Claims.Add(claim.Key);
                    Audit(fillAt, "inherited_live_claim", claim.Key);
                }
            Audit(fillAt, "attempt_started");
        }

        // Call only after flatness is confirmed; this is not a close-order action.
        public void EndFlatAttempt(DateTimeOffset at, string reason)
        {
            if (at < LastObservedAt)
                throw new ArgumentException("Flat confirmation cannot precede the current observation.", nameof(at));
            InvalidateOpportunity(at, reason);
            if (_episode != null)
                Close(at, reason);
            _attemptActive = false;
            Generation++;
            _forming.Clear();
            _carried.Clear();
            _developmentSeeds.Clear();
            _boundary = LastObservedAt = at;
            Audit(at, "attempt_flat_confirmed");
        }

        public bool Observe(RepairSample sample)
        {
            if (sample == null)
                throw new ArgumentNullException(nameof(sample));
            if (Suspended)
                return false;
            if (sample.Sequence == _lastSequence && SameSample(sample, _lastSample))
                return true;
            string invalid = Validate(sample);
            if (invalid != null)
            {
                Suspend(sample.At, invalid);
                return false;
            }

            _lastSample = sample with { Transitions = Array.AsReadOnly(sample.Transitions.ToArray()) };
            _lastSequence = sample.Sequence;
            LastCompleteSampleAt = sample.At;
            LastObservedAt = sample.At;
            LastPriceTicks = sample.PriceTicks;
            double x = Orient(sample.PriceTicks);
            if (_episode != null)
            {
                _episode.Adverse = Math.Min(_episode.Adverse, x);
                if (_episode.ResolvedAt == null)
                    _episode.ObservedFront = Math.Max(_episode.ObservedFront, x);
            }

            foreach (RepairTransition transition in sample.Transitions)
            {
                ClaimSnapshot prior = _claims.GetValueOrDefault(transition.Key);
                if (prior?.FailedAt != null)
                {
                    if (transition.Kind != EvidenceKind.RailFailed)
                        Audit(sample.At, "failed_identity_not_resurrected", transition.Key);
                    continue;
                }
                ClaimSnapshot claim = Update(transition, prior, sample.At);
                bool same = claim.Side == Side;
                bool confirmation = transition.Kind is EvidenceKind.RailOwned or EvidenceKind.RailHeld;
                bool attack = same ? transition.Kind == EvidenceKind.RailTested : confirmation;

                if (!Relevant(claim.Coverage))
                {
                    Audit(sample.At, "outside_observed_development", claim.Key);
                    continue;
                }
                if (_episode?.ResolvedAt != null && attack)
                {
                    InvalidateOpportunity(sample.At, "new_attack");
                    Close(sample.At, "resolved_then_superseded");
                }
                if (same && confirmation)
                {
                    _forming.Add(claim.Key);
                    if (_episode != null)
                    {
                        bool associated = _episode.Members.Contains(claim.Key)
                            || RepairArea(_episode).Any(r => r.Intersects(claim.Coverage));
                        if (associated)
                        {
                            if (_episode.Members.Add(claim.Key))
                                Audit(sample.At, _episode.ResolvedAt.HasValue
                                    ? "proof_contacts_resolved_area" : "proof_in_repair", claim.Key);
                        }
                        else if (_episode.ResolvedAt.HasValue && transition.Kind == EvidenceKind.RailOwned)
                        {
                            InvalidateOpportunity(sample.At, "unrelated_extension");
                            Close(sample.At, "unrelated_extension");
                            _forming.Add(claim.Key);
                            if (prior?.OwnedAt == null)
                                _developmentSeeds.Add(claim.Key);
                        }
                        else
                            Audit(sample.At, "proof_not_associated", claim.Key);
                    }
                }
                if (same && transition.Kind == EvidenceKind.RailTested)
                {
                    _forming.Add(claim.Key);
                    Open(sample.At, "same_side_test");
                    _episode.Members.Add(claim.Key);
                    _episode.Attacked.Add(claim.Key);
                    Audit(sample.At, "same_side_test", claim.Key);
                }
                if (!same && confirmation)
                {
                    Open(sample.At, "opposing_claim");
                    if (_episode.Claims.Add(claim.Key))
                        Audit(sample.At, "opposing_claim", claim.Key);
                }
                if (_episode != null && same && transition.Kind == EvidenceKind.RailFailed
                    && _episode.Members.Contains(claim.Key))
                    _episode.Attacked.Add(claim.Key);
            }
            Evaluate(sample.At, sample.PriceTicks);
            return true;
        }

        public void ObservePrice(DateTimeOffset at, double priceTicks)
        {
            if (Suspended)
                return;
            if (at < LastObservedAt || !ValidPrice(priceTicks))
            {
                Suspend(at, "invalid_price_observation");
                return;
            }
            if (LastCompleteSampleAt != default && at - LastCompleteSampleAt > _maximumSampleGap)
            {
                Suspend(at, "sample_health_gap");
                return;
            }
            LastObservedAt = at;
            LastPriceTicks = priceTicks;
            Evaluate(at, priceTicks);
        }

        public GroupHealth Health(ProofGroup group)
        {
            if (group == null || Suspended || group.Attempt != Attempt || group.Generation != Generation)
                return GroupHealth.Unknown;
            ClaimSnapshot[] members = group.Members.Select(m => Find(m.Key)).ToArray();
            if (members.Any(x => x?.Confirmed == true))
                return GroupHealth.Live;
            if (members.Any(x => x == null))
                return GroupHealth.Unknown;
            return members.All(x => x.FailedAt.HasValue) ? GroupHealth.Failed : GroupHealth.Challenged;
        }

        public ProofGroup CurrentProof(ProofGroup group, double executableTicks)
        {
            if (group == null || Suspended || group.Attempt != Attempt || group.Generation != Generation
                || !ValidPrice(executableTicks))
                return null;
            ProofMember[] live = group.Members.Where(m => Find(m.Key) is { Confirmed: true }
                && Orient(executableTicks) > Front(m.Coverage)).ToArray();
            return live.Length == 0 ? null : new(group.EpisodeId, group.At, live, group.Attempt, group.Generation);
        }

        public string Revalidate(ScaleOpportunity opportunity, double executableTicks)
        {
            if (Suspended || LastCompleteSampleAt == default)
                return "observation_not_ready";
            if (opportunity == null || !_opportunityUsable || opportunity != _opportunity
                || opportunity.Generation != Generation || opportunity.Attempt != Attempt)
                return "opportunity_not_current";
            if (!ValidPrice(executableTicks)
                || Orient(executableTicks) <= opportunity.RepairFrontTicks)
                return "repair_not_clear";
            if (opportunity.OpposingClaims.Any(k => Find(k)?.FailedAt == null))
                return "live_or_unknown_opposition";
            if (CurrentProof(opportunity.Proof, executableTicks) == null)
                return "support_not_current";
            return null;
        }

        public void MarkReserved(ScaleOpportunity opportunity, DateTimeOffset at)
        {
            if (opportunity != Opportunity)
                throw new InvalidOperationException("Only a current opportunity can be reserved.");
            SetEpisodeStage(opportunity.EpisodeId, RepairStage.Reserved);
            _audit.Add(new(at, opportunity.EpisodeId, "order_reserved"));
        }

        public void MarkConsumed(ScaleOpportunity opportunity, DateTimeOffset at)
        {
            if (opportunity == _opportunity)
            {
                _opportunityUsable = false;
            }
            SetEpisodeStage(opportunity.EpisodeId, RepairStage.Consumed);
            _audit.Add(new(at, opportunity.EpisodeId, "first_fill_consumed"));
        }

        public void Miss(ScaleOpportunity opportunity, DateTimeOffset at, string reason)
        {
            if (opportunity == _opportunity)
                InvalidateOpportunity(at, reason);
        }

        private void Evaluate(DateTimeOffset at, double priceTicks)
        {
            double x = Orient(priceTicks);
            if (_opportunityUsable && Revalidate(_opportunity, priceTicks) != null)
                InvalidateOpportunity(at, "current_support_or_clearance_lost");
            Episode ep = _episode;
            if (ep == null)
            {
                _peak = Math.Max(_peak, x);
                return;
            }
            ep.Adverse = Math.Min(ep.Adverse, x);
            if (ep.ResolvedAt == null)
                ep.ObservedFront = Math.Max(ep.ObservedFront, x);
            bool liveOpposition = ep.Claims.Any(k => _claims[k].FailedAt == null);
            double front = ep.Claims.Select(k => Front(_claims[k].Coverage)).DefaultIfEmpty(double.PositiveInfinity).Max();
            bool cleared = ep.Claims.Count > 0 && !liveOpposition && x > front;
            if (cleared && ep.ResolvedAt == null)
            {
                ep.ResolutionArea = RepairArea(ep);
                ep.ResolvedAt = at;
                ep.Stage = RepairStage.ResolvedAwaitingProof;
                Audit(at, "typed_repair_cleared");
            }
            ProofMember[] defended = ep.Members.Select(k => _claims[k])
                .Where(r => r.Confirmed && x > Front(r.Coverage) && ep.Attacked.Contains(r.Key)
                    && r.TestedAt >= ep.StartedAt && r.HeldAt >= r.TestedAt)
                .Select(r => new ProofMember(r.Key, r.Coverage, ProofForm.Defended)).ToArray();
            ProofMember[] fresh = ep.Members.Select(k => _claims[k])
                .Where(r => r.Confirmed && x > Front(r.Coverage) && FreshDevelopment(r))
                .Select(r => new ProofMember(r.Key, r.Coverage,
                    ep.Breached ? ProofForm.Rebuilt : ProofForm.Renewed)).ToArray();
            ProofMember[] support = defended.Length > 0 ? defended : fresh;
            if (cleared && support.Length > 0 && !ep.Offered)
            {
                ep.Offered = true;
                if (_attemptActive)
                {
                    ep.Stage = RepairStage.Eligible;
                    _opportunity = new(ep.Id, Attempt, Generation, at, ep.ResolvedAt.Value,
                        new ProofGroup(ep.Id, at, support, Attempt, Generation),
                        Array.AsReadOnly(ep.Claims.OrderBy(k => k.ToString(), StringComparer.Ordinal).ToArray()), front);
                    _opportunityUsable = true;
                    Audit(at, "repaired_continuation_eligible");
                }
                else
                    Audit(at, "watch_completion_not_admissible");
            }
            bool allAttackedFailed = ep.Attacked.Count > 0 && ep.Attacked.All(k => _claims[k].FailedAt != null);
            bool replacement = fresh.Any(m => _claims[m.Key].OwnedAt >= ep.StartedAt);
            if (allAttackedFailed && !replacement && defended.Length == 0)
            {
                if (liveOpposition)
                {
                    if (!ep.Breached)
                        Audit(at, "attacked_group_breached_rebuild_pending");
                    ep.Breached = true;
                }
                else
                {
                    InvalidateOpportunity(at, "attacked_structure_failed");
                    Close(at, "attacked_structure_failed");
                }
            }
            else if (!liveOpposition && x > ep.Peak + 1 && (support.Length > 0 || ep.Claims.Count == 0))
                Close(at, "extension_resumed");
            _peak = Math.Max(_peak, x);
        }

        private bool Relevant(TickInterval range)
        {
            // Retain the earlier observer's broad root-relative screening. A typed
            // opposing claim can already exist ahead of the current quote; excluding
            // it would forget live WATCH opposition at root fill. Local proof
            // association is checked separately, never inferred from this screen.
            return Front(range) >= Back(_root) - 2;
        }

        private IReadOnlyList<TickInterval> RepairArea(Episode ep)
        {
            if (ep.ResolutionArea != null)
                return ep.ResolutionArea;
            IEnumerable<TickInterval> observed = ep.Attacked.Concat(ep.Claims)
                .Concat(ep.Members.Where(k => FreshDevelopment(_claims[k])))
                .Distinct().Select(k => _claims[k].Coverage);
            double lo = Math.Min(ep.Adverse, ep.ObservedFront), hi = Math.Max(ep.Adverse, ep.ObservedFront);
            TickInterval path = Side == CampaignSide.Long
                ? new((long)Math.Floor(lo), (long)Math.Ceiling(hi))
                : new((long)Math.Floor(-hi), (long)Math.Ceiling(-lo));
            return TickInterval.Union(observed.Append(path));
        }

        private void Open(DateTimeOffset at, string reason)
        {
            if (_episode != null)
                return;
            InvalidateOpportunity(at, "new_episode");
            _episode = new Episode
            {
                Id = $"{Generation}:{++_episodeNumber}", StartedAt = at,
                Peak = _peak, Adverse = Orient(LastPriceTicks),
                ObservedFront = Math.Max(_peak, Orient(LastPriceTicks)),
                Members = _forming.Concat(_carried).Where(k => _claims[k].FailedAt == null).ToHashSet(),
            };
            Audit(at, reason);
        }

        private void Close(DateTimeOffset at, string reason)
        {
            Episode ep = _episode;
            if (ep == null)
                return;
            ep.Outcome = reason;
            if (ep.Stage is RepairStage.RepairActive or RepairStage.ResolvedAwaitingProof)
                ep.Stage = RepairStage.Invalidated;
            Audit(at, reason);
            LastClosedEpisode = Snapshot(ep);
            _carried.Clear();
            foreach (ClaimKey key in ep.Members.Where(k => _claims[k].Confirmed
                && (ep.Attacked.Contains(k) && _claims[k].HeldAt >= _claims[k].TestedAt
                    || FreshDevelopment(_claims[k]))))
                _carried.Add(key);
            _episode = null;
            _forming.Clear();
            _developmentSeeds.Clear();
            _boundary = at;
            _peak = Orient(LastPriceTicks);
        }

        private void InvalidateOpportunity(DateTimeOffset at, string reason)
        {
            if (!_opportunityUsable)
                return;
            _opportunityUsable = false;
            SetEpisodeStage(_opportunity.EpisodeId, RepairStage.Invalidated);
            _audit.Add(new(at, _opportunity.EpisodeId, reason));
        }

        private void SetEpisodeStage(string episodeId, RepairStage stage)
        {
            if (_episode?.Id == episodeId)
                _episode.Stage = stage;
            if (LastClosedEpisode?.Id == episodeId)
                LastClosedEpisode = LastClosedEpisode with { Stage = stage };
        }

        private ClaimSnapshot Update(RepairTransition transition, ClaimSnapshot prior, DateTimeOffset at)
        {
            ClaimSnapshot current = new(transition.Key, transition.Side, transition.Coverage,
                prior?.FirstObservedAt ?? at, prior?.FormedAt ?? transition.FormedAt,
                prior?.OwnedAt ?? (transition.Kind == EvidenceKind.RailOwned ? at : null),
                transition.Kind == EvidenceKind.RailTested ? at : prior?.TestedAt,
                transition.Kind == EvidenceKind.RailHeld ? at : prior?.HeldAt,
                transition.Kind == EvidenceKind.RailFailed ? at : null, transition.Kind);
            _claims[transition.Key] = current;
            _audit.Add(new(at, _episode?.Id, "claim_transition", current.Key, current));
            return current;
        }

        private string Validate(RepairSample sample)
        {
            if (!sample.Complete || sample.Source != EvidenceSource.LevelLedger || sample.Epoch != Epoch)
                return "incomplete_or_wrong_epoch_sample";
            if (sample.Sequence < 0 || (_lastSequence >= 0 && sample.Sequence != _lastSequence + 1)
                || sample.At == default || sample.At < LastObservedAt || !ValidPrice(sample.PriceTicks)
                || sample.Transitions == null)
                return "sample_order_or_price_invalid";
            if (LastCompleteSampleAt != default && sample.At - LastCompleteSampleAt > _maximumSampleGap)
                return "sample_health_gap";
            Dictionary<ClaimKey, RepairTransition> seen = new();
            foreach (RepairTransition transition in sample.Transitions)
            {
                if (transition == null || !transition.Key.IsValid || transition.Key.Epoch != Epoch
                    || transition.Key.Source != sample.Source || !transition.Coverage.IsValid || !Enum.IsDefined(transition.Side)
                    || transition.Kind is not (EvidenceKind.RailOwned or EvidenceKind.RailHeld
                        or EvidenceKind.RailTested or EvidenceKind.RailFailed)
                    || transition.FormedAt > sample.At)
                    return "claim_provenance_invalid";
                ClaimSnapshot prior = _claims.GetValueOrDefault(transition.Key);
                if (prior != null && transition.FormedAt > prior.FirstObservedAt)
                    return "formation_after_first_observation";
                if (prior != null && (prior.Side != transition.Side || prior.Coverage != transition.Coverage
                    || (prior.FormedAt.HasValue && transition.FormedAt.HasValue && prior.FormedAt != transition.FormedAt)))
                    return "claim_identity_changed";
                if (seen.TryGetValue(transition.Key, out var earlier)
                    && (earlier.Side != transition.Side || earlier.Coverage != transition.Coverage
                        || (earlier.FormedAt.HasValue && transition.FormedAt.HasValue && earlier.FormedAt != transition.FormedAt)))
                    return "intra_sample_identity_changed";
                seen[transition.Key] = transition with { FormedAt = earlier?.FormedAt ?? transition.FormedAt };
            }
            return null;
        }

        private static bool SameSample(RepairSample a, RepairSample b)
            => b != null && a.Source == b.Source && a.Epoch == b.Epoch && a.Sequence == b.Sequence
                && a.At == b.At && a.PriceTicks == b.PriceTicks && a.Complete == b.Complete
                && a.Transitions != null && a.Transitions.SequenceEqual(b.Transitions);

        private RepairEpisodeSnapshot Snapshot(Episode ep)
            => ep == null ? null : new(ep.Id, ep.Stage, ep.StartedAt, ep.ResolvedAt,
                Unorient(ep.Peak), Unorient(ep.Adverse), ep.Breached,
                Keys(ep.Members), Keys(ep.Attacked), Keys(ep.Claims),
                Keys(ep.Claims.Where(k => _claims[k].FailedAt == null)),
                TickInterval.Union(ep.Members.Select(k => _claims[k].Coverage)),
                RepairArea(ep), ep.Outcome);

        private static IReadOnlyList<ClaimKey> Keys(IEnumerable<ClaimKey> keys)
            => Array.AsReadOnly(keys.OrderBy(k => k.ToString(), StringComparer.Ordinal).ToArray());
        private void Audit(DateTimeOffset at, string reason, ClaimKey? key = null)
            => _audit.Add(new(at, _episode?.Id, reason, key));
        private double Orient(double ticks) => Side == CampaignSide.Long ? ticks : -ticks;
        private double Unorient(double ticks) => Orient(ticks);
        private double Front(TickInterval range) => Side == CampaignSide.Long ? range.Upper : -(double)range.Lower;
        private double Back(TickInterval range) => Side == CampaignSide.Long ? range.Lower : -(double)range.Upper;
        private bool FreshDevelopment(ClaimSnapshot claim) => claim.OwnedAt > _boundary || _developmentSeeds.Contains(claim.Key);
        private static bool ValidPrice(double price) => double.IsFinite(price) && Math.Abs(price) <= TickInterval.MaximumExactTick;
    }
}
