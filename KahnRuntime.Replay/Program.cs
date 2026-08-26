using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using KahnRuntime;

namespace KahnRuntime.Replay
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            try
            {
                ReplayOptions options = ReplayOptions.Parse(args);
                if (options.ShowHelp)
                {
                    Console.WriteLine(ReplayOptions.Usage);
                    return 0;
                }

                RuntimeSelfTests.RunAll();
                ReplaySummary summary = Run(options);
                Console.WriteLine(
                    $"campaign={summary.CampaignId} events={summary.EventsRead} "
                    + $"decisions={summary.DecisionsWritten} ignored={summary.EventsIgnored} "
                    + $"final_phase={summary.FinalPhase} simulated_position={summary.FinalPosition}"
                    + (string.IsNullOrWhiteSpace(summary.ReportPath)
                        ? string.Empty
                        : $" report={summary.ReportPath}"));
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(ex.Message);
                Console.Error.WriteLine();
                Console.Error.WriteLine(ReplayOptions.Usage);
                return 1;
            }
        }

        private static ReplaySummary Run(ReplayOptions options)
        {
            string campaignJson = File.ReadAllText(options.CampaignPath);
            CampaignPlan plan = CampaignPlanParser.Parse(campaignJson, Digest(campaignJson));
            CampaignState state = CampaignState.ForPlan(plan);
            CampaignPolicyEngine engine = CampaignPolicyEngine.CreateDefault();
            List<CampaignEvidence> evidenceEvents = ReadEvidence(options.EvidencePath);
            if (options.SortByTimestamp)
                evidenceEvents = evidenceEvents.OrderBy(item => item.Timestamp).ToList();

            string directory = Path.GetDirectoryName(options.OutputPath);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);

            int ignored = 0;
            int written = 0;
            using Stream outputStream = options.OutputPath == "-"
                ? Console.OpenStandardOutput()
                : new FileStream(options.OutputPath, FileMode.Create, FileAccess.Write, FileShare.Read);
            using StreamWriter writer = new(outputStream, new UTF8Encoding(false))
            {
                AutoFlush = true,
            };

            WriteJsonLine(writer, new Dictionary<string, object>
            {
                ["event"] = "campaign_loaded",
                ["campaign_id"] = plan.Id,
                ["campaign_digest"] = plan.Digest,
                ["status"] = plan.Status,
                ["side"] = plan.Side,
                ["waypoint_count"] = plan.Waypoints.Count,
                ["notes"] = plan.Notes,
            });

            foreach (CampaignEvidence evidence in evidenceEvents)
            {
                DateTimeOffset now = evidence.Timestamp;
                if (!plan.IsActiveAt(now))
                {
                    ignored++;
                    if (options.IncludeIgnored || options.ReportRequested)
                    {
                        WriteJsonLine(writer, new Dictionary<string, object>
                        {
                            ["event"] = "evidence_ignored",
                            ["campaign_id"] = plan.Id,
                            ["reason_code"] = "outside_campaign_window",
                            ["evidence_id"] = evidence.EventId,
                            ["evidence_ts_utc"] = evidence.Timestamp,
                            ["evidence_kind"] = evidence.Kind,
                            ["evidence_source"] = evidence.Source,
                        });
                    }
                    continue;
                }

                CampaignContext context = new(plan, state, options.TickSize, now);
                PolicyDecision decision = engine.Evaluate(context, evidence);
                if (!state.ShouldEmit(decision, now, options.DedupeInterval))
                    continue;

                WriteJsonLine(writer, DecisionPayload(plan, state, decision, evidence));
                written++;
                state.ApplyDecision(decision, plan, options.SimulateAcceptedDecisions, now);
                WriteJsonLine(writer, StatePayload(plan, state));
            }

            if (options.ReportRequested)
            {
                writer.Dispose();
                outputStream.Dispose();
                ReplayReport.Write(options.OutputPath, options.ReportPath);
            }

            return new ReplaySummary
            {
                CampaignId = plan.Id,
                EventsRead = evidenceEvents.Count,
                EventsIgnored = ignored,
                DecisionsWritten = written,
                FinalPhase = state.Phase.ToString(),
                FinalPosition = state.SimulatedPositionQuantity,
                ReportPath = options.ReportPath,
            };
        }

        private static List<CampaignEvidence> ReadEvidence(string path)
        {
            List<CampaignEvidence> result = new();
            int lineNumber = 0;
            foreach (string line in File.ReadLines(path))
            {
                lineNumber++;
                if (string.IsNullOrWhiteSpace(line))
                    continue;
                try
                {
                    result.Add(CampaignEvidenceParser.Parse(line));
                }
                catch (Exception ex)
                {
                    throw new InvalidDataException(
                        $"Evidence parse failed at {path}:{lineNumber}: {ex.Message}",
                        ex);
                }
            }
            return result;
        }

        private static Dictionary<string, object> DecisionPayload(CampaignPlan plan,
            CampaignState state,
            PolicyDecision decision,
            CampaignEvidence evidence)
            => new()
            {
                ["event"] = "policy_decision",
                ["campaign_id"] = plan.Id,
                ["campaign_digest"] = plan.Digest,
                ["phase_before"] = state.Phase,
                ["action"] = decision.Action,
                ["policy"] = decision.Policy,
                ["reason_code"] = decision.ReasonCode,
                ["detail"] = decision.Detail,
                ["priority"] = decision.Priority,
                ["quantity"] = decision.Quantity,
                ["waypoint_id"] = decision.WaypointId,
                ["risk_anchor"] = decision.RiskAnchor,
                ["risk_anchor_evidence_id"] = decision.RiskAnchorEvidenceId,
                ["expires_at"] = decision.ExpiresAt,
                ["evidence_id"] = evidence.EventId,
                ["evidence_ts_utc"] = evidence.Timestamp,
                ["evidence_source"] = evidence.Source,
                ["evidence_kind"] = evidence.Kind,
                ["evidence_side"] = evidence.Side,
                ["evidence_price"] = evidence.Price,
                ["evidence_range"] = evidence.Range,
                ["evidence_delta"] = evidence.Delta,
                ["evidence_volume"] = evidence.Volume,
                ["evidence_score"] = evidence.Score,
                ["simulated_position_before"] = state.SimulatedPositionQuantity,
            };

        private static Dictionary<string, object> StatePayload(CampaignPlan plan,
            CampaignState state)
            => new()
            {
                ["event"] = "campaign_state",
                ["campaign_id"] = plan.Id,
                ["phase"] = state.Phase,
                ["simulated_position_quantity"] = state.SimulatedPositionQuantity,
                ["active_risk_anchor"] = state.ActiveRiskAnchor,
                ["active_risk_anchor_evidence_id"] = state.ActiveRiskAnchorEvidenceId,
                ["root_risk_anchor"] = state.RootRiskAnchor,
                ["root_risk_anchor_evidence_id"] = state.RootRiskAnchorEvidenceId,
                ["armed_waypoint_id"] = state.ArmedWaypointId,
                ["suppress_adds_until"] = state.SuppressAddsUntil,
            };

        private static void WriteJsonLine(StreamWriter writer, Dictionary<string, object> payload)
            => writer.WriteLine(JsonSerializer.Serialize(NormalizePayload(payload), SerializerOptions));

        private static Dictionary<string, object> NormalizePayload(Dictionary<string, object> payload)
        {
            Dictionary<string, object> result = new(StringComparer.Ordinal);
            foreach ((string key, object value) in payload)
                result[JsonNamingPolicy.SnakeCaseLower.ConvertName(key)] = NormalizeValue(value);
            return result;
        }

        private static object NormalizeValue(object value)
            => value switch
            {
                null => null,
                double number when !double.IsFinite(number) => null,
                float number when !float.IsFinite(number) => null,
                Enum item => item.ToString(),
                DateTimeOffset timestamp => timestamp.ToString("O", CultureInfo.InvariantCulture),
                PriceRange range => new
                {
                    range.Lower,
                    range.Upper,
                },
                _ => value,
            };

        private static string Digest(string text)
        {
            byte[] bytes = System.Security.Cryptography.SHA256.HashData(
                Encoding.UTF8.GetBytes(text ?? string.Empty));
            return Convert.ToHexString(bytes).ToLowerInvariant();
        }

        private static readonly JsonSerializerOptions SerializerOptions = new()
        {
            WriteIndented = false,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        };
    }

    internal sealed class ReplaySummary
    {
        public string CampaignId { get; init; }
        public int EventsRead { get; init; }
        public int EventsIgnored { get; init; }
        public int DecisionsWritten { get; init; }
        public string FinalPhase { get; init; }
        public int FinalPosition { get; init; }
        public string ReportPath { get; init; }
    }

    internal sealed class ReplayOptions
    {
        public string CampaignPath { get; init; }
        public string EvidencePath { get; init; }
        public string OutputPath { get; init; }
        public double TickSize { get; init; } = 0.25;
        public bool SimulateAcceptedDecisions { get; init; } = true;
        public bool SortByTimestamp { get; init; }
        public bool IncludeIgnored { get; init; }
        public bool ReportRequested { get; init; }
        public string ReportPath { get; init; }
        public TimeSpan DedupeInterval { get; init; } = TimeSpan.Zero;
        public bool ShowHelp { get; init; }

        public static string Usage =>
            "Usage: dotnet run --project KahnRuntime.Replay -- "
            + "--campaign <campaign.json> --evidence <evidence.jsonl> --out <decisions.jsonl> "
            + "[--tick-size 0.25] [--no-sim] [--sort] [--include-ignored] "
            + "[--dedupe-seconds N] [--report [report.md]]";

        public static ReplayOptions Parse(string[] args)
        {
            if (args == null || args.Length == 0 || args.Contains("--help"))
                return new ReplayOptions { ShowHelp = true };

            Dictionary<string, string> values = new(StringComparer.OrdinalIgnoreCase);
            HashSet<string> flags = new(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i];
                if (!arg.StartsWith("--", StringComparison.Ordinal))
                    throw new ArgumentException($"Unexpected argument: {arg}");
                if (arg == "--report")
                {
                    flags.Add(arg);
                    if (i + 1 < args.Length
                        && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
                    {
                        values[arg] = args[++i];
                    }
                    continue;
                }
                if (arg is "--no-sim" or "--sort" or "--include-ignored")
                {
                    flags.Add(arg);
                    continue;
                }
                if (i + 1 >= args.Length)
                    throw new ArgumentException($"Missing value for {arg}");
                values[arg] = args[++i];
            }

            string campaign = Required(values, "--campaign");
            string evidence = Required(values, "--evidence");
            string output = Required(values, "--out");
            bool reportRequested = flags.Contains("--report");
            string reportPath = null;
            if (reportRequested)
            {
                if (output == "-")
                    throw new ArgumentException("--report requires --out to be a decisions JSONL file path");
                if (values.TryGetValue("--report", out string explicitReport))
                    reportPath = explicitReport;
                else
                    reportPath = Path.ChangeExtension(output, ".report.md");
                if (string.IsNullOrWhiteSpace(reportPath))
                    throw new ArgumentException("--report path must not be empty");
            }
            double tickSize = values.TryGetValue("--tick-size", out string tickText)
                ? double.Parse(tickText, CultureInfo.InvariantCulture)
                : 0.25;
            if (!double.IsFinite(tickSize) || tickSize <= 0)
                throw new ArgumentException("--tick-size must be positive");

            TimeSpan dedupe = values.TryGetValue("--dedupe-seconds", out string dedupeText)
                ? TimeSpan.FromSeconds(double.Parse(dedupeText, CultureInfo.InvariantCulture))
                : TimeSpan.Zero;
            if (dedupe < TimeSpan.Zero)
                throw new ArgumentException("--dedupe-seconds must be non-negative");

            return new ReplayOptions
            {
                CampaignPath = campaign,
                EvidencePath = evidence,
                OutputPath = output,
                TickSize = tickSize,
                SimulateAcceptedDecisions = !flags.Contains("--no-sim"),
                SortByTimestamp = flags.Contains("--sort"),
                IncludeIgnored = flags.Contains("--include-ignored"),
                ReportRequested = reportRequested,
                ReportPath = reportPath,
                DedupeInterval = dedupe,
            };
        }

        private static string Required(Dictionary<string, string> values, string key)
        {
            if (!values.TryGetValue(key, out string value) || string.IsNullOrWhiteSpace(value))
                throw new ArgumentException($"{key} is required");
            return value;
        }
    }
}
