using System;
using System.Collections.Generic;
using System.Linq;

namespace KahnRuntime.Scaling
{
    internal readonly record struct ClaimKey(EvidenceSource Source, string Epoch, string RailId)
    {
        public bool IsValid => Source == EvidenceSource.LevelLedger
            && !string.IsNullOrWhiteSpace(Epoch) && !string.IsNullOrWhiteSpace(RailId);
        public override string ToString() => $"{Source}:{Epoch}:{RailId}";
    }

    internal readonly record struct TickInterval(long Lower, long Upper)
    {
        public const long MaximumExactTick = 1L << 52;
        public bool IsValid => Lower <= Upper && Lower >= -MaximumExactTick && Upper <= MaximumExactTick;
        public bool Intersects(TickInterval other)
            => Lower <= other.Upper && Upper >= other.Lower;

        public static IReadOnlyList<TickInterval> Union(IEnumerable<TickInterval> intervals)
        {
            List<TickInterval> result = new();
            foreach (TickInterval next in intervals.OrderBy(x => x.Lower).ThenBy(x => x.Upper))
            {
                if (!next.IsValid)
                    throw new ArgumentException("Invalid tick interval.", nameof(intervals));
                if (result.Count > 0 && (next.Lower <= result[^1].Upper
                    || (result[^1].Upper < long.MaxValue && next.Lower == result[^1].Upper + 1)))
                    result[^1] = new(result[^1].Lower, Math.Max(result[^1].Upper, next.Upper));
                else
                    result.Add(next);
            }
            return result.AsReadOnly();
        }
    }

    internal sealed record RepairTransition(
        ClaimKey Key,
        EvidenceKind Kind,
        CampaignSide Side,
        TickInterval Coverage,
        DateTimeOffset? FormedAt = null);

    // The adapter attests an actual source sample, not merely equal timestamps.
    // PriceTicks is side-correct executable BBO. Midpoint is only a replay diagnostic.
    internal sealed record RepairSample(
        EvidenceSource Source,
        string Epoch,
        long Sequence,
        DateTimeOffset At,
        double PriceTicks,
        IReadOnlyList<RepairTransition> Transitions,
        bool Complete);

    internal enum RepairStage
    {
        Building, RepairActive, ResolvedAwaitingProof, Eligible,
        Reserved, Consumed, Invalidated, Suspended,
    }

    internal enum ProofForm { Defended, Renewed, Rebuilt }
    internal enum GroupHealth { Live, Challenged, Failed, Unknown }

    internal sealed record ClaimSnapshot(
        ClaimKey Key, CampaignSide Side, TickInterval Coverage,
        DateTimeOffset FirstObservedAt, DateTimeOffset? FormedAt,
        DateTimeOffset? OwnedAt, DateTimeOffset? TestedAt,
        DateTimeOffset? HeldAt, DateTimeOffset? FailedAt, EvidenceKind LastKind)
    {
        public bool Confirmed => FailedAt == null
            && LastKind is EvidenceKind.RailOwned or EvidenceKind.RailHeld;
    }

    internal sealed record ProofMember(ClaimKey Key, TickInterval Coverage, ProofForm Form);

    internal sealed class ProofGroup
    {
        public string EpisodeId { get; }
        public DateTimeOffset At { get; }
        public IReadOnlyList<ProofMember> Members { get; }
        public IReadOnlyList<TickInterval> Coverage { get; }
        public long Attempt { get; }
        public long Generation { get; }

        public ProofGroup(string episodeId, DateTimeOffset at, IEnumerable<ProofMember> members,
            long attempt, long generation)
        {
            EpisodeId = episodeId;
            At = at;
            Attempt = attempt;
            Generation = generation;
            Members = Array.AsReadOnly(members.ToArray());
            if (Members.Count == 0 || Members.Select(x => x.Key).Distinct().Count() != Members.Count)
                throw new ArgumentException("Proof needs distinct qualifying members.", nameof(members));
            Coverage = TickInterval.Union(Members.Select(x => x.Coverage));
        }
    }

    internal sealed record ScaleOpportunity(
        string EpisodeId, long Attempt, long Generation, DateTimeOffset At,
        DateTimeOffset RepairResolvedAt, ProofGroup Proof,
        IReadOnlyList<ClaimKey> OpposingClaims, double RepairFrontTicks);

    internal sealed record RepairAudit(
        DateTimeOffset At, string EpisodeId, string Reason, ClaimKey? Claim = null,
        ClaimSnapshot TransitionState = null);

    internal sealed record RepairEpisodeSnapshot(
        string Id, RepairStage Stage, DateTimeOffset StartedAt,
        DateTimeOffset? ResolvedAt, double PreAttackExtremeTicks,
        double AdverseExtremeTicks, bool Breached,
        IReadOnlyList<ClaimKey> Members, IReadOnlyList<ClaimKey> Attacked,
        IReadOnlyList<ClaimKey> OpposingClaims, IReadOnlyList<ClaimKey> LiveOpposition,
        IReadOnlyList<TickInterval> MemberCoverage,
        IReadOnlyList<TickInterval> RepairCoverage, string Outcome);
}
