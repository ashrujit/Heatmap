using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KahnRuntime
{
    internal sealed class CampaignPlanLoadResult
    {
        public CampaignPlan Plan { get; init; }
        public bool Changed { get; init; }
        public string Error { get; init; }
    }

    internal sealed class CampaignPlanStore
    {
        private readonly string _path;
        private string _lastDigest;

        public CampaignPlanStore(string path)
        {
            _path = Environment.ExpandEnvironmentVariables(path ?? string.Empty);
            if (string.IsNullOrWhiteSpace(_path))
                throw new ArgumentException("Campaign path is empty.", nameof(path));
        }

        public CampaignPlanLoadResult LoadIfChanged()
        {
            if (!File.Exists(_path))
                return new CampaignPlanLoadResult { Changed = false };

            string json = File.ReadAllText(_path);
            string digest = Sha256(json);
            if (string.Equals(digest, _lastDigest, StringComparison.Ordinal))
                return new CampaignPlanLoadResult { Changed = false };

            try
            {
                CampaignPlan plan = CampaignPlanParser.Parse(json, digest);
                _lastDigest = digest;
                return new CampaignPlanLoadResult
                {
                    Plan = plan,
                    Changed = true,
                };
            }
            catch (Exception ex)
            {
                return new CampaignPlanLoadResult
                {
                    Changed = false,
                    Error = ex.Message,
                };
            }
        }

        private static string Sha256(string text)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(text ?? string.Empty);
            byte[] hash = SHA256.HashData(bytes);
            return Convert.ToHexString(hash).ToLowerInvariant();
        }
    }

    internal static class CampaignPlanParser
    {
        private static readonly Regex IdPattern = new(
            "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            RegexOptions.CultureInvariant | RegexOptions.Compiled);

        public static CampaignPlan Parse(string json, string digest = null)
        {
            using JsonDocument document = JsonDocument.Parse(json);
            JsonElement root = RequireObject(document.RootElement, "campaign");

            int schemaVersion = RequireInt(root, "schema_version", "campaign");
            if (schemaVersion != 1)
                throw Invalid("campaign.schema_version must be 1");
            string kind = RequireString(root, "kind", "campaign");
            if (!string.Equals(kind, "KAHN_CAMPAIGN", StringComparison.Ordinal))
                throw Invalid("campaign.kind must be KAHN_CAMPAIGN");

            CampaignPlan plan = new()
            {
                SchemaVersion = schemaVersion,
                Kind = kind,
                Id = ValidateId(RequireString(root, "id", "campaign"), "campaign.id"),
                Status = RequireString(root, "status", "campaign"),
                CreatedAt = RequireTimestamp(root, "created_at", "campaign"),
                Side = ParseSide(RequireString(root, "side", "campaign"), "campaign.side"),
                Window = ParseWindow(RequireObjectProperty(root, "window", "campaign")),
                Arena = ParseRange(RequireObjectProperty(root, "arena", "campaign"), "campaign.arena"),
                Sizing = ParseSizing(OptionalObjectProperty(root, "sizing")),
                Risk = ParseRisk(OptionalObjectProperty(root, "risk")),
                Objective = ParseObjective(OptionalObjectProperty(root, "objective")),
                Policies = ParsePolicyFlags(OptionalObjectProperty(root, "policies")),
                Waypoints = ParseWaypoints(RequireArrayProperty(root, "waypoints", "campaign")),
                Notes = OptionalString(root, "notes"),
                Digest = digest,
            };

            if (!string.Equals(plan.Status, "active", StringComparison.OrdinalIgnoreCase)
                && !string.Equals(plan.Status, "draft", StringComparison.OrdinalIgnoreCase))
            {
                throw Invalid("campaign.status must be active or draft");
            }
            if (plan.Window.ExpiresAt <= plan.Window.NotBefore)
                throw Invalid("campaign.window.expires_at must be after not_before");
            if (!plan.Arena.IsValid)
                throw Invalid("campaign.arena must be a valid range");
            if (plan.Waypoints.Count == 0)
                throw Invalid("campaign.waypoints must contain at least one waypoint");
            if (plan.Sizing.ProbeQuantity > plan.Sizing.MaxPositionQuantity)
                throw Invalid("sizing.probe_quantity must not exceed max_position_quantity");

            foreach (CampaignWaypoint waypoint in plan.Waypoints)
            {
                if (!waypoint.Range.IsValid)
                    throw Invalid($"waypoint {waypoint.Id} has an invalid range");
                if (!plan.Arena.Intersects(waypoint.Range))
                    throw Invalid($"waypoint {waypoint.Id} must intersect campaign.arena");
            }

            return plan;
        }

        private static CampaignWindow ParseWindow(JsonElement element)
            => new()
            {
                NotBefore = RequireTimestamp(element, "not_before", "campaign.window"),
                ExpiresAt = RequireTimestamp(element, "expires_at", "campaign.window"),
            };

        private static CampaignSizing ParseSizing(JsonElement? element)
        {
            if (!element.HasValue)
                return new CampaignSizing();
            JsonElement value = element.Value;
            return new CampaignSizing
            {
                ProbeQuantity = OptionalPositiveInt(value, "probe_quantity", 1),
                AddQuantity = OptionalPositiveInt(value, "add_quantity", 1),
                MaxPositionQuantity = OptionalPositiveInt(value, "max_position_quantity", 1),
            };
        }

        private static CampaignRisk ParseRisk(JsonElement? element)
        {
            if (!element.HasValue)
                return new CampaignRisk();
            JsonElement value = element.Value;
            return new CampaignRisk
            {
                RootStopTicks = OptionalPositiveInt(value, "root_stop_ticks", 16),
                SponsorFailureBufferTicks = OptionalNonNegativeInt(value, "sponsor_failure_buffer_ticks", 2),
                AllowContestBeyondRiskAnchor = OptionalBool(value, "allow_contest_beyond_risk_anchor", true),
            };
        }

        private static CampaignObjective ParseObjective(JsonElement? element)
        {
            if (!element.HasValue)
                return new CampaignObjective();
            JsonElement value = element.Value;
            PriceRange target = null;
            if (value.TryGetProperty("target_range", out JsonElement targetElement)
                && targetElement.ValueKind != JsonValueKind.Null)
            {
                target = ParseRange(RequireObject(targetElement, "campaign.objective.target_range"),
                    "campaign.objective.target_range");
            }
            return new CampaignObjective
            {
                TargetRange = target,
                TargetProximityTicks = OptionalNonNegativeInt(value, "target_proximity_ticks", 8),
                SuppressAddsInTargetZone = OptionalBool(value, "suppress_adds_in_target_zone", true),
            };
        }

        private static CampaignPolicyFlags ParsePolicyFlags(JsonElement? element)
        {
            if (!element.HasValue)
                return new CampaignPolicyFlags();
            JsonElement value = element.Value;
            return new CampaignPolicyFlags
            {
                TrapProbeEnabled = OptionalBool(value, "trap_probe", true),
                PressEnabled = OptionalBool(value, "press", true),
                BuildTrialEnabled = OptionalBool(value, "build_trial", true),
                TargetZoneEnabled = OptionalBool(value, "target_zone", true),
                RepairHoldEnabled = OptionalBool(value, "repair_hold", true),
                PathStressEnabled = OptionalBool(value, "path_stress", true),
            };
        }

        private static IReadOnlyList<CampaignWaypoint> ParseWaypoints(JsonElement array)
        {
            List<CampaignWaypoint> result = new();
            HashSet<string> ids = new(StringComparer.Ordinal);
            int index = 0;
            foreach (JsonElement element in array.EnumerateArray())
            {
                string context = $"campaign.waypoints[{index}]";
                JsonElement obj = RequireObject(element, context);
                string id = ValidateId(RequireString(obj, "id", context), $"{context}.id");
                if (!ids.Add(id))
                    throw Invalid($"duplicate waypoint id {id}");

                result.Add(new CampaignWaypoint
                {
                    Id = id,
                    Role = ParseWaypointRole(RequireString(obj, "role", context), $"{context}.role"),
                    Range = ParseRange(RequireObjectProperty(obj, "range", context), $"{context}.range"),
                    Label = OptionalString(obj, "label"),
                    SuppressAddsWithinTicks = OptionalNullableNonNegativeInt(obj, "suppress_adds_within_ticks"),
                    MaxPositionQuantity = OptionalNullablePositiveInt(obj, "max_position_quantity"),
                    PreserveRiskAnchorOnAdd = OptionalBool(obj, "preserve_risk_anchor_on_add", false),
                    RequirePriceInside = OptionalBool(obj, "require_price_inside", false),
                });
                index++;
            }
            return result;
        }

        internal static PriceRange ParseRange(JsonElement element, string context)
        {
            double lower = RequireDouble(element, "lower", context);
            double upper = RequireDouble(element, "upper", context);
            if (lower > upper)
                (lower, upper) = (upper, lower);
            return new PriceRange { Lower = lower, Upper = upper };
        }

        internal static JsonElement RequireObject(JsonElement element, string context)
        {
            if (element.ValueKind != JsonValueKind.Object)
                throw Invalid($"{context} must be an object");
            return element;
        }

        internal static JsonElement RequireObjectProperty(JsonElement element,
            string property,
            string context)
            => RequireObject(RequireProperty(element, property, context), $"{context}.{property}");

        internal static JsonElement RequireArrayProperty(JsonElement element,
            string property,
            string context)
        {
            JsonElement value = RequireProperty(element, property, context);
            if (value.ValueKind != JsonValueKind.Array)
                throw Invalid($"{context}.{property} must be an array");
            return value;
        }

        internal static JsonElement? OptionalObjectProperty(JsonElement element, string property)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return null;
            }
            return RequireObject(value, property);
        }

        internal static JsonElement RequireProperty(JsonElement element,
            string property,
            string context)
        {
            if (!element.TryGetProperty(property, out JsonElement value))
                throw Invalid($"{context}.{property} is required");
            return value;
        }

        internal static string RequireString(JsonElement element, string property, string context)
        {
            JsonElement value = RequireProperty(element, property, context);
            if (value.ValueKind != JsonValueKind.String)
                throw Invalid($"{context}.{property} must be a string");
            string text = value.GetString();
            if (string.IsNullOrWhiteSpace(text))
                throw Invalid($"{context}.{property} must not be empty");
            return text;
        }

        internal static string OptionalString(JsonElement element, string property)
            => element.TryGetProperty(property, out JsonElement value)
                && value.ValueKind == JsonValueKind.String
                    ? value.GetString()
                    : null;

        internal static int RequireInt(JsonElement element, string property, string context)
        {
            JsonElement value = RequireProperty(element, property, context);
            if (!value.TryGetInt32(out int number))
                throw Invalid($"{context}.{property} must be an integer");
            return number;
        }

        internal static double RequireDouble(JsonElement element, string property, string context)
        {
            JsonElement value = RequireProperty(element, property, context);
            if (!value.TryGetDouble(out double number) || !double.IsFinite(number))
                throw Invalid($"{context}.{property} must be a finite number");
            return number;
        }

        internal static DateTimeOffset RequireTimestamp(JsonElement element,
            string property,
            string context)
        {
            string text = RequireString(element, property, context);
            if (!DateTimeOffset.TryParse(text,
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.AssumeUniversal,
                    out DateTimeOffset timestamp))
            {
                throw Invalid($"{context}.{property} must be an ISO timestamp");
            }
            return timestamp;
        }

        private static int OptionalPositiveInt(JsonElement element, string property, int fallback)
        {
            int value = OptionalNonNegativeInt(element, property, fallback);
            if (value < 1)
                throw Invalid($"{property} must be positive");
            return value;
        }

        private static int OptionalNonNegativeInt(JsonElement element, string property, int fallback)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return fallback;
            }
            if (!value.TryGetInt32(out int number) || number < 0)
                throw Invalid($"{property} must be a non-negative integer");
            return number;
        }

        private static int? OptionalNullablePositiveInt(JsonElement element, string property)
        {
            int? value = OptionalNullableNonNegativeInt(element, property);
            if (value.HasValue && value.Value < 1)
                throw Invalid($"{property} must be positive");
            return value;
        }

        private static int? OptionalNullableNonNegativeInt(JsonElement element, string property)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return null;
            }
            if (!value.TryGetInt32(out int number) || number < 0)
                throw Invalid($"{property} must be a non-negative integer");
            return number;
        }

        private static bool OptionalBool(JsonElement element, string property, bool fallback)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return fallback;
            }
            if (value.ValueKind != JsonValueKind.True && value.ValueKind != JsonValueKind.False)
                throw Invalid($"{property} must be a boolean");
            return value.GetBoolean();
        }

        private static CampaignSide ParseSide(string text, string context)
            => Normalize(text) switch
            {
                "long" => CampaignSide.Long,
                "short" => CampaignSide.Short,
                _ => throw Invalid($"{context} must be long or short"),
            };

        private static WaypointRole ParseWaypointRole(string text, string context)
            => Normalize(text) switch
            {
                "trap_probe" or "trapprobe" => WaypointRole.TrapProbe,
                "press" => WaypointRole.Press,
                "build_trial" or "buildtrial" => WaypointRole.BuildTrial,
                "target" => WaypointRole.Target,
                "no_add" or "noadd" => WaypointRole.NoAdd,
                "evaluate" => WaypointRole.Evaluate,
                "risk" => WaypointRole.Risk,
                "repair_hold" or "repairhold" => WaypointRole.RepairHold,
                "path_stress" or "pathstress" or "mature_path" or "maturepath" => WaypointRole.PathStress,
                "invalidation" => WaypointRole.Invalidation,
                _ => throw Invalid($"{context} is not a supported waypoint role"),
            };

        private static string ValidateId(string id, string context)
        {
            if (!IdPattern.IsMatch(id))
                throw Invalid($"{context} contains unsupported characters");
            return id;
        }

        internal static InvalidDataException Invalid(string message)
            => new(message);

        internal static string Normalize(string text)
            => new((text ?? string.Empty)
                .Trim()
                .Where(ch => ch != '-' && ch != '_' && ch != ' ')
                .Select(char.ToLowerInvariant)
                .ToArray());
    }
}
