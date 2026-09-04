using System;

namespace KahnRuntime
{
    internal static class RootProbeStop
    {
        public static bool IsTouched(CampaignPlan plan,
            CampaignState state,
            RuntimePosition position,
            ExecutableMarket market,
            double tickSize,
            out double triggerPrice)
        {
            triggerPrice = double.NaN;
            if (!IsEligible(plan, state, position)
                || market?.IsValid != true)
            {
                return false;
            }

            double averagePrice = position.AveragePrice;
            if (!double.IsFinite(averagePrice) || averagePrice <= 0)
                return false;

            double tick = Math.Max(tickSize, 0.0000001);
            int stopTicks = Math.Max(1, plan.Risk?.RootStopTicks ?? 16);
            double offset = stopTicks * tick;
            triggerPrice = plan.Side == CampaignSide.Long
                ? RoundDown(averagePrice - offset, tick)
                : RoundUp(averagePrice + offset, tick);

            return plan.Side == CampaignSide.Long
                ? market.Bid <= triggerPrice
                : market.Ask >= triggerPrice;
        }

        private static bool IsEligible(CampaignPlan plan,
            CampaignState state,
            RuntimePosition position)
            => plan != null
                && state != null
                && !state.IsRetired
                && state.HasPosition
                && state.AcceptedAddCount <= 0
                && position != null
                && !position.IsFlat
                && position.Direction == plan.Side;

        private static double RoundUp(double price, double tickSize)
            => Math.Ceiling((price / tickSize) - 1e-9) * tickSize;

        private static double RoundDown(double price, double tickSize)
            => Math.Floor((price / tickSize) + 1e-9) * tickSize;
    }
}
