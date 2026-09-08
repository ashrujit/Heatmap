using System;
using System.Linq;

namespace KahnRuntime.Scaling
{
    internal sealed class GroupSponsorState
    {
        public CampaignSide Side { get; }
        public TickInterval RootAnchor { get; }
        public ProofGroup Pending { get; private set; }
        public ProofGroup Active { get; private set; }
        public GroupHealth ActiveHealth { get; private set; } = GroupHealth.Unknown;
        public int FilledAddCount { get; private set; }
        public string LastChange { get; private set; }

        public GroupSponsorState(CampaignSide side, TickInterval rootAnchor)
        {
            if (!rootAnchor.IsValid)
                throw new ArgumentException("Invalid root anchor.", nameof(rootAnchor));
            Side = side;
            RootAnchor = rootAnchor;
        }

        public void Observe(RepairEpisodeObserver observer)
        {
            if (Pending != null && observer.Health(Pending) == GroupHealth.Failed)
            {
                Pending = null;
                LastChange = "failed_pending_discarded";
            }
            ActiveHealth = observer.Health(Active);
        }

        public void FirstFill(ProofGroup child, RepairEpisodeObserver observer, double currentPriceTicks)
        {
            if (child == null || observer.Side != Side)
                throw new ArgumentException("Sponsor fill needs campaign-side proof.");
            Observe(observer);
            FilledAddCount++;
            ProofGroup currentChild = observer.CurrentProof(child, currentPriceTicks);
            ProofGroup currentPending = observer.CurrentProof(Pending, currentPriceTicks);
            if (currentChild != null && currentPending != null
                && (Active == null || ActiveHealth == GroupHealth.Live)
                && Beyond(currentChild, currentPending)
                && (Active == null ? BeyondRoot(currentPending) : Beyond(currentPending, Active)))
            {
                Active = currentPending;
                LastChange = "prior_live_pending_promoted";
            }
            else
                LastChange = "active_anchor_preserved";

            // Every filled episode has its own pending lineage, even at the same area.
            // A late physical fill with failed/unknown proof cannot sponsor new risk.
            Pending = currentChild;
            ActiveHealth = observer.Health(Active);
        }

        private bool BeyondRoot(ProofGroup group)
            => Side == CampaignSide.Long
                ? group.Coverage.Min(r => r.Lower) > RootAnchor.Upper
                : group.Coverage.Max(r => r.Upper) < RootAnchor.Lower;

        private bool Beyond(ProofGroup child, ProofGroup reference)
            => Side == CampaignSide.Long
                ? child.Coverage.Min(r => r.Lower) > reference.Coverage.Max(r => r.Upper)
                : child.Coverage.Max(r => r.Upper) < reference.Coverage.Min(r => r.Lower);
    }
}
