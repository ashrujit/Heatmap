using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace ExecAssistantRuntime
{
    internal sealed class RuntimeCheckpointData
    {
        public int Version { get; set; } = 1;
        public string UpdatedUtc { get; set; }
        public string RuntimeState { get; set; }
        public string LastDirectiveId { get; set; }
        public string LastDirectiveDigest { get; set; }
        public string LastDirectiveJson { get; set; }
        public List<string> ProcessedControlIds { get; set; } = new();
        public bool? TradingEnabled { get; set; }
        public bool? BrokerTradingAllowed { get; set; }
        public bool StartupRecoveryComplete { get; set; }
        public string ExecutionSymbol { get; set; }
        public string ExecutionSymbolId { get; set; }
        public string ExecutionConnectionId { get; set; }
        public string MarketDataSymbol { get; set; }
        public string MarketDataSymbolId { get; set; }
        public string MarketDataConnectionId { get; set; }
        public int? InstanceMaxQuantity { get; set; }
        public int? WorkerPollMs { get; set; }
        public string EvidenceState { get; set; }
        public string EvidenceEpochReason { get; set; }
        public string EvidenceEpochStartedUtc { get; set; }
        public int EvidenceSampleCount { get; set; }
        public int EvidenceWarmupSeconds { get; set; }
        public int EvidenceWarmupRequiredSamples { get; set; }
        public double EvidenceWarmupRemainingSeconds { get; set; }
        public bool RecoveryActionRequired { get; set; }
        public int BoundWorkingOrderCount { get; set; }
        public int UnresolvedEntryCount { get; set; }
        public string PositionId { get; set; }
        public string PositionDirection { get; set; }
        public double PositionQuantity { get; set; }
        public double PositionAveragePrice { get; set; }
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

        public RuntimeCheckpointData Load()
        {
            if (!File.Exists(_path))
                return null;
            string json = File.ReadAllText(_path);
            RuntimeCheckpointData data = JsonSerializer.Deserialize<RuntimeCheckpointData>(
                json,
                SerializerOptions);
            if (data == null || data.Version != 1)
                throw new InvalidDataException("Unsupported or empty runtime checkpoint.");
            data.ProcessedControlIds ??= new List<string>();
            return data;
        }

        public void Save(RuntimeCheckpointData data)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            data.Version = 1;
            data.UpdatedUtc = DateTime.UtcNow.ToString("O");
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

        private static readonly JsonSerializerOptions SerializerOptions = new()
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        };
    }
}
