using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;

namespace KahnRuntime.Replay
{
    internal static class ReplayReport
    {
        private static readonly TimeZoneInfo EasternTimeZone = FindEasternTimeZone();

        public static void Write(string decisionsPath, string reportPath)
        {
            if (string.IsNullOrWhiteSpace(decisionsPath) || decisionsPath == "-")
                throw new ArgumentException("A replay report requires a decisions JSONL file path.");
            if (string.IsNullOrWhiteSpace(reportPath))
                throw new ArgumentException("Report path is empty.");

            ReplayReportModel model = Read(decisionsPath);
            string directory = Path.GetDirectoryName(reportPath);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);
            File.WriteAllText(reportPath, Render(model), new UTF8Encoding(false));
        }

        private static ReplayReportModel Read(string path)
        {
            ReplayReportModel model = new()
            {
                DecisionsPath = path,
            };
            ReportDecision pendingDecision = null;
            string priorActiveRisk = null;
            string priorRootRisk = null;
            int lineNumber = 0;

            foreach (string line in File.ReadLines(path))
            {
                lineNumber++;
                if (string.IsNullOrWhiteSpace(line))
                    continue;

                using JsonDocument document = JsonDocument.Parse(line);
                JsonElement root = document.RootElement;
                string eventType = String(root, "event");
                switch (eventType)
                {
                    case "campaign_loaded":
                        model.CampaignId = String(root, "campaign_id");
                        model.Side = String(root, "side");
                        model.Status = String(root, "status");
                        model.CampaignNotes = String(root, "notes");
                        break;
                    case "evidence_ignored":
                        model.IgnoredEvents++;
                        break;
                    case "policy_decision":
                        pendingDecision = Decision(root, lineNumber);
                        model.Decisions.Add(pendingDecision);
                        break;
                    case "campaign_state":
                        ReportState state = State(root);
                        model.FinalState = state;
                        if (pendingDecision != null
                            && string.Equals(pendingDecision.CampaignId, state.CampaignId,
                                StringComparison.Ordinal))
                        {
                            pendingDecision.PositionAfter = state.Position;
                            pendingDecision.PhaseAfter = state.Phase;
                            pendingDecision.ActiveRiskAfter = state.ActiveRiskAnchor;
                            pendingDecision.RootRiskAfter = state.RootRiskAnchor;

                            if (!string.Equals(priorActiveRisk, state.ActiveRiskAnchor,
                                    StringComparison.Ordinal))
                            {
                                model.StateNotes.Add($"{pendingDecision.TimeEt}: active risk "
                                    + $"{Dash(priorActiveRisk)} -> {Dash(state.ActiveRiskAnchor)}"
                                    + EvidenceSuffix(state.ActiveRiskAnchorEvidenceId));
                                priorActiveRisk = state.ActiveRiskAnchor;
                            }
                            if (!string.Equals(priorRootRisk, state.RootRiskAnchor,
                                    StringComparison.Ordinal))
                            {
                                model.StateNotes.Add($"{pendingDecision.TimeEt}: root risk "
                                    + $"{Dash(priorRootRisk)} -> {Dash(state.RootRiskAnchor)}"
                                    + EvidenceSuffix(state.RootRiskAnchorEvidenceId));
                                priorRootRisk = state.RootRiskAnchor;
                            }
                        }
                        break;
                }
            }

            return model;
        }

        private static ReportDecision Decision(JsonElement root, int lineNumber)
        {
            string time = TimeEt(String(root, "evidence_ts_utc"));
            return new ReportDecision
            {
                LineNumber = lineNumber,
                CampaignId = String(root, "campaign_id"),
                TimeEt = time,
                PhaseBefore = String(root, "phase_before"),
                Action = String(root, "action"),
                Policy = String(root, "policy"),
                ReasonCode = String(root, "reason_code"),
                Detail = String(root, "detail"),
                Quantity = NullableString(root, "quantity"),
                PositionBefore = NullableString(root, "simulated_position_before"),
                WaypointId = String(root, "waypoint_id"),
                RiskAnchor = Range(root, "risk_anchor"),
                RiskAnchorEvidenceId = String(root, "risk_anchor_evidence_id"),
                EvidenceId = String(root, "evidence_id"),
                EvidenceSource = String(root, "evidence_source"),
                EvidenceKind = String(root, "evidence_kind"),
                EvidenceSide = String(root, "evidence_side"),
                EvidenceRange = Range(root, "evidence_range"),
                EvidenceDelta = NullableString(root, "evidence_delta"),
                EvidenceVolume = NullableString(root, "evidence_volume"),
                EvidenceScore = NullableString(root, "evidence_score"),
            };
        }

        private static ReportState State(JsonElement root)
            => new()
            {
                CampaignId = String(root, "campaign_id"),
                Phase = String(root, "phase"),
                Position = NullableString(root, "simulated_position_quantity"),
                ActiveRiskAnchor = Range(root, "active_risk_anchor"),
                ActiveRiskAnchorEvidenceId = String(root, "active_risk_anchor_evidence_id"),
                RootRiskAnchor = Range(root, "root_risk_anchor"),
                RootRiskAnchorEvidenceId = String(root, "root_risk_anchor_evidence_id"),
                SuppressAddsUntilEt = TimeEt(String(root, "suppress_adds_until")),
                ExecutionAttemptCount = NullableString(root, "execution_attempt_count"),
                MaxRetry = NullableString(root, "max_retry"),
                RetriesRemaining = NullableString(root, "retries_remaining"),
                ExecutionPauseReason = String(root, "execution_pause_reason"),
                ExecutionPausedAtEt = TimeEt(String(root, "execution_paused_at")),
            };

        private static string Render(ReplayReportModel model)
        {
            StringBuilder builder = new();
            builder.AppendLine("# Kahn Replay Report");
            builder.AppendLine();
            builder.AppendLine($"Campaign: `{Escape(model.CampaignId)}`");
            builder.AppendLine($"Side: `{Escape(model.Side)}`");
            builder.AppendLine($"Status: `{Escape(model.Status)}`");
            builder.AppendLine($"Decisions: `{model.Decisions.Count}`");
            builder.AppendLine($"Ignored events: `{model.IgnoredEvents}`");
            if (!string.IsNullOrWhiteSpace(model.CampaignNotes))
                builder.AppendLine($"Notes: {Escape(model.CampaignNotes)}");
            builder.AppendLine();

            builder.AppendLine("## Decisions");
            builder.AppendLine();
            builder.AppendLine("| ET | Phase | Action | Pos | Reason | Waypoint | Risk | Evidence |");
            builder.AppendLine("|---|---|---:|---:|---|---|---|---|");
            foreach (ReportDecision decision in model.Decisions)
            {
                builder.Append("| ");
                builder.Append(Escape(decision.TimeEt));
                builder.Append(" | ");
                builder.Append(Escape(Phase(decision)));
                builder.Append(" | ");
                builder.Append(Escape(decision.Action));
                builder.Append(" | ");
                builder.Append(Escape(Position(decision)));
                builder.Append(" | ");
                builder.Append(Escape($"{decision.Policy}/{decision.ReasonCode}"));
                builder.Append(" | ");
                builder.Append(Escape(Dash(decision.WaypointId)));
                builder.Append(" | ");
                builder.Append(Escape(Risk(decision)));
                builder.Append(" | ");
                builder.Append(Escape(Evidence(decision)));
                builder.AppendLine(" |");
            }

            if (model.StateNotes.Count > 0)
            {
                builder.AppendLine();
                builder.AppendLine("## Risk Notes");
                builder.AppendLine();
                foreach (string note in model.StateNotes)
                    builder.AppendLine("- " + Escape(note));
            }

            if (model.FinalState != null)
            {
                builder.AppendLine();
                builder.AppendLine("## Final State");
                builder.AppendLine();
                builder.AppendLine($"- Phase: `{Escape(model.FinalState.Phase)}`");
                builder.AppendLine($"- Position: `{Escape(model.FinalState.Position)}`");
                builder.AppendLine($"- Retries: `{Escape(RetryState(model.FinalState))}`");
                if (!string.IsNullOrWhiteSpace(model.FinalState.ExecutionPauseReason))
                    builder.AppendLine($"- Pause: `{Escape(model.FinalState.ExecutionPauseReason)}` at `{Escape(Dash(model.FinalState.ExecutionPausedAtEt))}`");
                builder.AppendLine($"- Active risk: `{Escape(Dash(model.FinalState.ActiveRiskAnchor))}`"
                    + EvidenceSuffix(model.FinalState.ActiveRiskAnchorEvidenceId));
                builder.AppendLine($"- Root risk: `{Escape(Dash(model.FinalState.RootRiskAnchor))}`"
                    + EvidenceSuffix(model.FinalState.RootRiskAnchorEvidenceId));
                builder.AppendLine($"- Suppress adds until: `{Escape(Dash(model.FinalState.SuppressAddsUntilEt))}`");
            }

            return builder.ToString();
        }

        private static string Phase(ReportDecision decision)
            => string.IsNullOrWhiteSpace(decision.PhaseAfter)
                ? Dash(decision.PhaseBefore)
                : $"{Dash(decision.PhaseBefore)}->{decision.PhaseAfter}";

        private static string Position(ReportDecision decision)
            => string.IsNullOrWhiteSpace(decision.PositionAfter)
                ? Dash(decision.PositionBefore)
                : $"{Dash(decision.PositionBefore)}->{decision.PositionAfter}";

        private static string RetryState(ReportState state)
        {
            if (state == null || string.IsNullOrWhiteSpace(state.ExecutionAttemptCount))
                return "-";
            string maxRetry = string.IsNullOrWhiteSpace(state.MaxRetry) ? "?" : state.MaxRetry;
            string remaining = string.IsNullOrWhiteSpace(state.RetriesRemaining)
                ? "?"
                : state.RetriesRemaining;
            return state.ExecutionAttemptCount + "/" + maxRetry + " remaining=" + remaining;
        }

        private static string Risk(ReportDecision decision)
            => string.IsNullOrWhiteSpace(decision.RiskAnchor)
                ? "-"
                : $"{decision.RiskAnchor}{EvidenceSuffix(decision.RiskAnchorEvidenceId)}";

        private static string Evidence(ReportDecision decision)
        {
            List<string> parts = new()
            {
                Dash(decision.EvidenceSource),
                Dash(decision.EvidenceKind),
                Dash(decision.EvidenceSide),
            };
            if (!string.IsNullOrWhiteSpace(decision.EvidenceRange))
                parts.Add(decision.EvidenceRange);
            if (!string.IsNullOrWhiteSpace(decision.EvidenceDelta))
                parts.Add("d=" + decision.EvidenceDelta);
            if (!string.IsNullOrWhiteSpace(decision.EvidenceVolume))
                parts.Add("v=" + decision.EvidenceVolume);
            if (!string.IsNullOrWhiteSpace(decision.EvidenceScore))
                parts.Add("s=" + decision.EvidenceScore);
            return string.Join(" ", parts);
        }

        private static string EvidenceSuffix(string evidenceId)
            => string.IsNullOrWhiteSpace(evidenceId) ? string.Empty : $" ({evidenceId})";

        private static string TimeEt(string text)
        {
            if (string.IsNullOrWhiteSpace(text))
                return null;
            if (!DateTimeOffset.TryParse(text,
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.AssumeUniversal,
                    out DateTimeOffset timestamp))
            {
                return text;
            }
            DateTimeOffset eastern = TimeZoneInfo.ConvertTime(timestamp, EasternTimeZone);
            return eastern.ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        }

        private static string String(JsonElement element, string property)
            => element.TryGetProperty(property, out JsonElement value)
                && value.ValueKind == JsonValueKind.String
                    ? value.GetString()
                    : null;

        private static string NullableString(JsonElement element, string property)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return null;
            }
            return value.ValueKind == JsonValueKind.String
                ? value.GetString()
                : value.GetRawText();
        }

        private static string Range(JsonElement element, string property)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return null;
            }
            if (value.ValueKind != JsonValueKind.Object
                || !value.TryGetProperty("lower", out JsonElement lower)
                || !value.TryGetProperty("upper", out JsonElement upper)
                || !lower.TryGetDouble(out double lowerValue)
                || !upper.TryGetDouble(out double upperValue))
            {
                return null;
            }
            return FormatNumber(lowerValue) + "-" + FormatNumber(upperValue);
        }

        private static string FormatNumber(double value)
            => value.ToString("0.########", CultureInfo.InvariantCulture);

        private static string Dash(string text)
            => string.IsNullOrWhiteSpace(text) ? "-" : text;

        private static string Escape(string text)
            => (text ?? string.Empty)
                .Replace("|", "\\|", StringComparison.Ordinal)
                .Replace("\r", " ", StringComparison.Ordinal)
                .Replace("\n", " ", StringComparison.Ordinal);

        private static TimeZoneInfo FindEasternTimeZone()
        {
            try
            {
                return TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
            }
            catch
            {
                try
                {
                    return TimeZoneInfo.FindSystemTimeZoneById("America/New_York");
                }
                catch
                {
                    return TimeZoneInfo.Local;
                }
            }
        }
    }

    internal sealed class ReplayReportModel
    {
        public string DecisionsPath { get; init; }
        public string CampaignId { get; set; }
        public string Side { get; set; }
        public string Status { get; set; }
        public string CampaignNotes { get; set; }
        public int IgnoredEvents { get; set; }
        public List<ReportDecision> Decisions { get; } = new();
        public List<string> StateNotes { get; } = new();
        public ReportState FinalState { get; set; }
    }

    internal sealed class ReportDecision
    {
        public int LineNumber { get; init; }
        public string CampaignId { get; init; }
        public string TimeEt { get; init; }
        public string PhaseBefore { get; init; }
        public string PhaseAfter { get; set; }
        public string Action { get; init; }
        public string Policy { get; init; }
        public string ReasonCode { get; init; }
        public string Detail { get; init; }
        public string Quantity { get; init; }
        public string PositionBefore { get; init; }
        public string PositionAfter { get; set; }
        public string WaypointId { get; init; }
        public string RiskAnchor { get; init; }
        public string RiskAnchorEvidenceId { get; init; }
        public string EvidenceId { get; init; }
        public string EvidenceSource { get; init; }
        public string EvidenceKind { get; init; }
        public string EvidenceSide { get; init; }
        public string EvidenceRange { get; init; }
        public string EvidenceDelta { get; init; }
        public string EvidenceVolume { get; init; }
        public string EvidenceScore { get; init; }
        public string ActiveRiskAfter { get; set; }
        public string RootRiskAfter { get; set; }
    }

    internal sealed class ReportState
    {
        public string CampaignId { get; init; }
        public string Phase { get; init; }
        public string Position { get; init; }
        public string ActiveRiskAnchor { get; init; }
        public string ActiveRiskAnchorEvidenceId { get; init; }
        public string RootRiskAnchor { get; init; }
        public string RootRiskAnchorEvidenceId { get; init; }
        public string SuppressAddsUntilEt { get; init; }
        public string ExecutionAttemptCount { get; init; }
        public string MaxRetry { get; init; }
        public string RetriesRemaining { get; init; }
        public string ExecutionPauseReason { get; init; }
        public string ExecutionPausedAtEt { get; init; }
    }
}