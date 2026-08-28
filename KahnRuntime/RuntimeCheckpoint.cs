using System;
using System.IO;
using System.Text.Json;

namespace KahnRuntime
{
    internal sealed class RuntimeCheckpointData
    {
        public int Version { get; set; } = 1;
        public string UpdatedUtc { get; set; }
        public string RuntimeState { get; set; }
        public string CampaignId { get; set; }
        public string CampaignDigest { get; set; }
        public string CampaignStatus { get; set; }
        public string CampaignPath { get; set; }
        public string ControlPath { get; set; }
        public string EvidencePath { get; set; }
        public string DecisionLogPath { get; set; }
        public string CheckpointPath { get; set; }
        public string LastControlId { get; set; }
        public string LastControlAction { get; set; }
        public string LastControlStatus { get; set; }
        public string Symbol { get; set; }
        public string SymbolId { get; set; }
        public string ConnectionId { get; set; }
        public string ExecutionSymbol { get; set; }
        public string ExecutionSymbolId { get; set; }
        public string ExecutionConnectionId { get; set; }
        public string MarketDataSymbol { get; set; }
        public string MarketDataSymbolId { get; set; }
        public string MarketDataConnectionId { get; set; }
        public string Account { get; set; }
        public string AccountId { get; set; }
        public bool? TradingEnabled { get; set; }
        public bool? ShadowFillSimulation { get; set; }
        public int? CampaignProbeQuantity { get; set; }
        public int? CampaignAddQuantity { get; set; }
        public int? CampaignMaxPositionQuantity { get; set; }
        public int? CampaignMaxRetry { get; set; }
        public bool? PassiveHarvestEnabled { get; set; }
        public PriceRange PassiveHarvestRange { get; set; }
        public int? PassiveHarvestInitialClipQuantity { get; set; }
        public int? PassiveHarvestFollowClipQuantity { get; set; }
        public int? PassiveHarvestMaxWorkingQuantity { get; set; }
        public int? PassiveHarvestFloorFailureTicks { get; set; }
        public int? ExecutionAttemptCount { get; set; }
        public int? ExecutionRetriesRemaining { get; set; }
        public string ExecutionPauseReason { get; set; }
        public string ExecutionPausedAtUtc { get; set; }
        public int? InstanceMaxQuantity { get; set; }
        public int? WorkerPollMs { get; set; }
        public int? BookSampleMs { get; set; }
        public int? BookFreshnessSec { get; set; }
        public int? QuoteFreshnessMs { get; set; }
        public int? LlBookLookbackSeconds { get; set; }
        public double? LlEventZThreshold { get; set; }
        public int? LlClusterMinEvents { get; set; }
        public int? LlClusterTicks { get; set; }
        public int? LlClusterSeconds { get; set; }
        public int? LlConfirmMoveTicks { get; set; }
        public int? LlConfirmSeconds { get; set; }
        public int? LlFailureBufferTicks { get; set; }
        public int? LlFailureConfirmTicks { get; set; }
        public int? LlFailureSeconds { get; set; }
        public double TickSize { get; set; }
        public string Phase { get; set; }
        public int SimulatedPositionQuantity { get; set; }
        public string ArmedWaypointId { get; set; }
        public PriceRange ActiveRiskAnchor { get; set; }
        public string ActiveRiskAnchorEvidenceId { get; set; }
        public PriceRange RootRiskAnchor { get; set; }
        public string RootRiskAnchorEvidenceId { get; set; }
        public string SuppressAddsUntilUtc { get; set; }
        public string LastDecisionUtc { get; set; }
        public double? LatestBid { get; set; }
        public double? LatestAsk { get; set; }
        public string LastQuoteUtc { get; set; }
        public string LastL2Utc { get; set; }
        public string EvidenceState { get; set; }
        public string EvidenceEpochReason { get; set; }
        public string EvidenceEpochStartedUtc { get; set; }
        public int EvidenceSampleCount { get; set; }
        public int EvidenceWarmupSeconds { get; set; }
        public int EvidenceWarmupRequiredSamples { get; set; }
        public double EvidenceWarmupRemainingSeconds { get; set; }
        public int BoundWorkingOrderCount { get; set; }
        public int PassiveHarvestWorkingOrderCount { get; set; }
        public double PassiveHarvestWorkingQuantity { get; set; }
        public string PositionId { get; set; }
        public string PositionDirection { get; set; }
        public double PositionQuantity { get; set; }
        public double PositionAveragePrice { get; set; }
        public bool? PassiveHarvestActive { get; set; }
        public string PassiveHarvestStartedAtUtc { get; set; }
        public string LastPassiveHarvestAtUtc { get; set; }
        public int? PassiveHarvestSignalCount { get; set; }
        public long DroppedDecisionLogEvents { get; set; }
    }

    internal sealed class RuntimeCheckpointStore
    {
        private readonly string _path;

        public RuntimeCheckpointStore(string path)
        {
            _path = Environment.ExpandEnvironmentVariables(path ?? string.Empty);
            if (string.IsNullOrWhiteSpace(_path))
                throw new ArgumentException("Checkpoint path is empty.", nameof(path));
        }

        public void Save(RuntimeCheckpointData data)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            data.Version = 1;
            data.UpdatedUtc = DateTime.UtcNow.ToString("O");
            Sanitize(data);
            string json = JsonSerializer.Serialize(data, SerializerOptions);
            string temporary = _path + ".tmp";
            string directory = Path.GetDirectoryName(_path);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);
            if (File.Exists(temporary))
                File.Delete(temporary);
            File.WriteAllText(temporary, json);
            File.Move(temporary, _path, overwrite: true);
        }

        private static void Sanitize(RuntimeCheckpointData data)
        {
            data.TickSize = FiniteOrZero(data.TickSize);
            data.LatestBid = NullableFinite(data.LatestBid);
            data.LatestAsk = NullableFinite(data.LatestAsk);
            data.EvidenceWarmupRemainingSeconds = FiniteOrZero(data.EvidenceWarmupRemainingSeconds);
            data.PositionQuantity = FiniteOrZero(data.PositionQuantity);
            data.PositionAveragePrice = FiniteOrZero(data.PositionAveragePrice);
            data.PassiveHarvestWorkingQuantity = FiniteOrZero(data.PassiveHarvestWorkingQuantity);
        }

        private static double? NullableFinite(double? value)
            => value.HasValue && double.IsFinite(value.Value) ? value.Value : null;

        private static double FiniteOrZero(double value)
            => double.IsFinite(value) ? value : 0.0;

        private static readonly JsonSerializerOptions SerializerOptions = new()
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        };
    }
}
