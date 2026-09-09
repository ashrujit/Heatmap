using System;
using System.Collections.Generic;
using System.Linq;
using KahnRuntime.Scaling;

namespace KahnRuntime
{
    internal enum RootClaimOrigin { Unknown, Lean, Consumed }
    internal enum RootHealth { Live, Tested, Failed, Unknown }

    internal sealed record RootClaim(ClaimKey Key, CampaignSide Side, TickInterval Coverage,
        RootClaimOrigin Origin, DateTimeOffset? FormedAt, DateTimeOffset? OwnedAt,
        DateTimeOffset UpdatedAt, EvidenceKind LastKind, DateTimeOffset? FailedAt)
    {
        public RootHealth Health => FailedAt.HasValue ? RootHealth.Failed
            : !OwnedAt.HasValue ? RootHealth.Unknown
            : LastKind == EvidenceKind.RailTested ? RootHealth.Tested
            : LastKind is EvidenceKind.RailOwned or EvidenceKind.RailHeld ? RootHealth.Live : RootHealth.Unknown;
    }

    internal sealed record RootRiskBinding(RootClaim Owner, string TriggerEventId,
        ClaimKey TriggerKey, DateTimeOffset QualifiedAt, string Association)
    {
        public PriceRange Range(double tickSize)
            => new() { Lower = Owner.Coverage.Lower * tickSize, Upper = Owner.Coverage.Upper * tickSize };

        public double EntryDistanceTicks(double price, double tickSize)
            => Owner.Side == CampaignSide.Long ? price / tickSize - Owner.Coverage.Lower
                : Owner.Coverage.Upper - price / tickSize;

        public bool Matches(CampaignEvidence evidence)
            => evidence != null && Owner.Key == new ClaimKey(evidence.Source, evidence.EvidenceEpoch, evidence.RailId)
                && CampaignSideMath.IsSameSide(Owner.Side, evidence.Side);
    }

    // Separate from forward scale development: a root defense may be behind the entry.
    internal sealed class RootEvidenceLedger
    {
        private readonly Dictionary<ClaimKey, RootClaim> _claims = new();
        private readonly TimeSpan _maximumGap;
        private long _sequence = -1;
        public string Epoch { get; private set; }
        public DateTimeOffset? ObservedAt { get; private set; }
        public bool Available { get; private set; }
        public RootEvidenceLedger(TimeSpan maximumGap) => _maximumGap = maximumGap;
        public RootClaim Find(ClaimKey key) => _claims.GetValueOrDefault(key);
        public void Suspend() => Available = false;

        public void RecordFailure(CampaignEvidence evidence)
        {
            if (evidence.Kind is not (EvidenceKind.RailFailed or EvidenceKind.SponsorFailed)) return;
            var key = new ClaimKey(evidence.Source, evidence.EvidenceEpoch, evidence.RailId);
            RootClaim prior = Find(key);
            if (key.IsValid && key.Epoch == Epoch && prior != null
                && CampaignSideMath.IsSameSide(prior.Side, evidence.Side) && !prior.FailedAt.HasValue)
                _claims[key] = prior with { FailedAt = evidence.Timestamp, UpdatedAt = evidence.Timestamp,
                    LastKind = EvidenceKind.RailFailed };
        }

        public void Observe(RepairSample sample, IReadOnlyList<RootClaim> snapshot = null)
        {
            if (!sample.Complete || sample.At == default || sample.Source != EvidenceSource.LevelLedger || string.IsNullOrWhiteSpace(sample.Epoch)
                || sample.At < ObservedAt || (Epoch == sample.Epoch && sample.Sequence <= _sequence))
            {
                Suspend();
                return;
            }
            if (Epoch != sample.Epoch)
            {
                _claims.Clear();
                Epoch = sample.Epoch;
            }
            _sequence = sample.Sequence;
            ObservedAt = sample.At;
            Available = true;
            if (snapshot != null)
            {
                if (snapshot.Any(c => !c.Key.IsValid || c.Key.Epoch != Epoch || !c.Coverage.IsValid
                    || c.UpdatedAt > sample.At || c.OwnedAt > sample.At || c.FormedAt > c.OwnedAt
                    || (Find(c.Key) is { } prior && (prior.Side != c.Side || prior.Coverage != c.Coverage)))
                    || snapshot.Select(c => c.Key).Distinct().Count() != snapshot.Count)
                {
                    Suspend();
                    return;
                }
                // Complete engine state hydrates old ownership without replaying permission events.
                var previous = _claims.ToDictionary(x => x.Key, x => x.Value);
                _claims.Clear();
                foreach (RootClaim claim in snapshot)
                    _claims[claim.Key] = previous.GetValueOrDefault(claim.Key)?.FailedAt.HasValue == true
                        ? previous[claim.Key] : claim;
                foreach (RootClaim failed in previous.Values.Where(c => c.FailedAt.HasValue))
                    _claims.TryAdd(failed.Key, failed);
            }
            foreach (RepairTransition transition in sample.Transitions)
            {
                if (!transition.Key.IsValid || transition.Key.Epoch != Epoch || !transition.Coverage.IsValid)
                {
                    Suspend();
                    continue;
                }
                RootClaim prior = Find(transition.Key);
                if (prior != null && (prior.Side != transition.Side || prior.Coverage != transition.Coverage))
                {
                    Suspend();
                    continue;
                }
                if (prior?.FailedAt.HasValue == true) continue;
                if (transition.Kind is not (EvidenceKind.RailOwned or EvidenceKind.RailHeld
                    or EvidenceKind.RailTested or EvidenceKind.RailFailed)) continue;
                _claims[transition.Key] = new(transition.Key, transition.Side, transition.Coverage,
                    transition.Origin == RootClaimOrigin.Unknown ? prior?.Origin ?? RootClaimOrigin.Unknown : transition.Origin,
                    prior?.FormedAt ?? transition.FormedAt,
                    prior?.OwnedAt ?? (transition.Kind == EvidenceKind.RailOwned ? sample.At : null),
                    sample.At, transition.Kind, transition.Kind == EvidenceKind.RailFailed ? sample.At : null);
            }
        }

        public bool FreshAt(DateTimeOffset now)
            => Available && ObservedAt.HasValue && now >= ObservedAt && now - ObservedAt <= _maximumGap;

        public RootHealth Health(RootRiskBinding binding, DateTimeOffset now)
        {
            if (binding == null || binding.Owner.Key.Epoch != Epoch) return RootHealth.Unknown;
            RootClaim current = Find(binding.Owner.Key);
            if (current == null || current.Side != binding.Owner.Side || current.Coverage != binding.Owner.Coverage)
                return RootHealth.Unknown;
            if (current?.FailedAt.HasValue == true) return RootHealth.Failed;
            return FreshAt(now) ? current.Health : RootHealth.Unknown;
        }

        public RootRiskBinding Resolve(CampaignEvidence trigger, CampaignSide side, DateTimeOffset now, out string reason)
        {
            reason = "root_owner_unavailable";
            if (!FreshAt(now) || trigger.Source != EvidenceSource.LevelLedger || trigger.EvidenceEpoch != Epoch)
                return null;
            var key = new ClaimKey(trigger.Source, trigger.EvidenceEpoch, trigger.RailId);
            RootClaim claim = Find(key);
            if (trigger.Kind == EvidenceKind.RailFailed && CampaignSideMath.IsOppositeSide(side, trigger.Side))
            {
                // LL currently exports no causal parent relation. Location is not a substitute.
                reason = _claims.Values.Any(c => c.Side == side && c.Health is RootHealth.Live or RootHealth.Tested)
                    ? "root_pair_unresolved" : "root_owner_missing";
                return null;
            }
            if (!key.IsValid || trigger.Kind is not (EvidenceKind.RailOwned or EvidenceKind.RailHeld)
                || !CampaignSideMath.IsSameSide(side, trigger.Side) || claim?.Side != side
                || claim.Health != RootHealth.Live || claim.OwnedAt > trigger.Timestamp)
                return null;
            reason = "direct_owned_claim";
            return new(claim, trigger.EventId, key, now, reason);
        }

        public string Revalidate(RootRiskBinding binding, DateTimeOffset now, double price, double tickSize, int? maximumDistance)
        {
            if (binding == null) return "root_owner_unbound";
            RootHealth health = Health(binding, now);
            if (health is RootHealth.Failed or RootHealth.Unknown) return "root_owner_" + health.ToString().ToLowerInvariant();
            if (!double.IsFinite(price) || price <= 0 || !double.IsFinite(tickSize) || tickSize <= 0)
                return "root_entry_quote_invalid";
            double distance = binding.EntryDistanceTicks(price, tickSize);
            if (distance < 0) return "root_entry_beyond_owner";
            return maximumDistance.HasValue && distance > maximumDistance.Value + 1e-8
                ? "root_entry_distance_exceeded" : null;
        }
    }
}
