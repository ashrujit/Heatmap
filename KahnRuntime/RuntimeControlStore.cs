using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KahnRuntime
{
    internal enum RuntimeControlAction
    {
        Unknown,
        Cancel,
        Flat,
        GoLive,
        Breakeven,
    }

    internal sealed class RuntimeControlCommand
    {
        public int SchemaVersion { get; init; }
        public string Kind { get; init; }
        public string Id { get; init; }
        public RuntimeControlAction Action { get; init; }
        public string RawAction { get; init; }
        public string Reason { get; init; }
        public DateTimeOffset CreatedAt { get; init; }
        public string Digest { get; init; }
        public string CampaignId { get; init; }
        public string CampaignDigest { get; init; }
        public string RuntimeInstanceId { get; init; }
        public int Attempt { get; init; }
    }

    internal sealed class RuntimeControlLoadResult
    {
        public RuntimeControlCommand Command { get; init; }
        public bool Changed { get; init; }
        public string Error { get; init; }
    }

    internal sealed class RuntimeControlStore
    {
        private readonly string _path;
        private string _lastDigest;

        public RuntimeControlStore(string path)
        {
            _path = Environment.ExpandEnvironmentVariables(path ?? string.Empty);
            if (string.IsNullOrWhiteSpace(_path))
                throw new ArgumentException("Control path is empty.", nameof(path));
            try
            {
                if (File.Exists(_path))
                    _lastDigest = Sha256(File.ReadAllText(_path));
            }
            catch
            {
                _lastDigest = null;
            }
        }

        public RuntimeControlLoadResult LoadIfChanged()
        {
            if (!File.Exists(_path))
                return new RuntimeControlLoadResult { Changed = false };

            string json;
            try
            {
                json = File.ReadAllText(_path);
            }
            catch (Exception ex) when (ex is IOException
                || ex is UnauthorizedAccessException)
            {
                return new RuntimeControlLoadResult
                {
                    Changed = false,
                    Error = "control read failed: " + ex.Message,
                };
            }

            string digest = Sha256(json);
            if (string.Equals(digest, _lastDigest, StringComparison.Ordinal))
                return new RuntimeControlLoadResult { Changed = false };

            try
            {
                RuntimeControlCommand command = RuntimeControlParser.Parse(json, digest);
                _lastDigest = digest;
                return new RuntimeControlLoadResult
                {
                    Command = command,
                    Changed = true,
                };
            }
            catch (Exception ex)
            {
                _lastDigest = digest;
                return new RuntimeControlLoadResult
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

    internal static class RuntimeControlParser
    {
        public static RuntimeControlCommand Parse(string json, string digest = null)
        {
            using JsonDocument document = JsonDocument.Parse(json);
            JsonElement root = CampaignPlanParser.RequireObject(
                document.RootElement,
                "control");

            int schemaVersion = OptionalInt(root, "schema_version", 1);
            if (schemaVersion is not (1 or 2))
                throw CampaignPlanParser.Invalid("control.schema_version must be 1 or 2");

            string kind = OptionalString(root, "kind", "KAHN_CONTROL");
            if (!string.Equals(kind, "KAHN_CONTROL", StringComparison.Ordinal))
                throw CampaignPlanParser.Invalid("control.kind must be KAHN_CONTROL");

            string id = CampaignPlanParser.RequireString(root, "id", "control");
            string rawAction = CampaignPlanParser.RequireString(root, "action", "control");
            RuntimeControlAction action = ParseAction(rawAction);
            if (action == RuntimeControlAction.Unknown)
                throw CampaignPlanParser.Invalid(
                    "control.action must be FLAT, CANCEL, GO_LIVE or BE");

            bool scoped = action is RuntimeControlAction.GoLive or RuntimeControlAction.Breakeven;
            if (scoped && schemaVersion != 2)
                throw CampaignPlanParser.Invalid("GO_LIVE/BE require schema_version 2");

            return new RuntimeControlCommand
            {
                SchemaVersion = schemaVersion,
                Kind = kind,
                Id = id,
                Action = action,
                RawAction = rawAction,
                Reason = CampaignPlanParser.OptionalString(root, "reason"),
                CreatedAt = scoped ? CampaignPlanParser.RequireTimestamp(root, "created_at", "control")
                    : OptionalTimestamp(root, "created_at", DateTimeOffset.UtcNow),
                Digest = digest,
                CampaignId = scoped ? CampaignPlanParser.RequireString(root, "campaign_id", "control") : null,
                CampaignDigest = scoped ? CampaignPlanParser.RequireString(root, "campaign_digest", "control") : null,
                RuntimeInstanceId = scoped ? CampaignPlanParser.RequireString(root, "runtime_instance_id", "control") : null,
                Attempt = scoped ? CampaignPlanParser.RequireInt(root, "attempt", "control") : 0,
            };
        }

        private static RuntimeControlAction ParseAction(string text)
        {
            string value = Normalize(text);
            return value switch
            {
                "golive" => RuntimeControlAction.GoLive,
                "be" or "breakeven" => RuntimeControlAction.Breakeven,
                "flat" or "flatten" or "closeposition" or "closepositions"
                    or "cancelandflatten" or "flattenandcancel" => RuntimeControlAction.Flat,
                "cancel" or "canceldirective" or "cancelcampaign"
                    or "retire" or "retirecampaign" => RuntimeControlAction.Cancel,
                _ => RuntimeControlAction.Unknown,
            };
        }

        private static string Normalize(string text)
            => (text ?? string.Empty)
                .Replace("_", string.Empty)
                .Replace("-", string.Empty)
                .Replace(" ", string.Empty)
                .ToLowerInvariant();

        private static string OptionalString(JsonElement element,
            string property,
            string fallback)
            => element.TryGetProperty(property, out JsonElement value)
                && value.ValueKind != JsonValueKind.Null
                    ? CampaignPlanParser.RequireString(element, property, "control")
                    : fallback;

        private static int OptionalInt(JsonElement element,
            string property,
            int fallback)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return fallback;
            }
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out int result))
                throw CampaignPlanParser.Invalid($"control.{property} must be an integer");
            return result;
        }

        private static DateTimeOffset OptionalTimestamp(JsonElement element,
            string property,
            DateTimeOffset fallback)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return fallback;
            }
            return CampaignPlanParser.RequireTimestamp(element, property, "control");
        }
    }
}
