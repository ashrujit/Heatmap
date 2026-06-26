using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ExecAssistantRuntime
{
    internal enum TradeDirection
    {
        Long,
        Short,
    }

    internal enum ResolutionType
    {
        DirectConversion,
        SupportedReclaim,
    }

    internal enum TargetMode
    {
        HardTp,
    }

    internal enum ControlAction
    {
        Flat,
        CancelDirective,
    }

    internal enum DirectiveLineageMode
    {
        New,
        Continue,
    }

    internal sealed class PriceRange
    {
        public double Lower { get; init; }
        public double Upper { get; init; }

        public bool Contains(double price)
            => double.IsFinite(price) && price >= Lower && price <= Upper;

        public bool Intersects(double lower, double upper)
            => upper >= Lower && lower <= Upper;
    }

    internal sealed class PriceTrigger
    {
        public bool IsBelow { get; init; }
        public double Price { get; init; }
    }

    internal sealed class DirectiveLineage
    {
        public DirectiveLineageMode Mode { get; init; }
        public string ParentDirectiveId { get; init; }

        public bool IsContinuation
            => Mode == DirectiveLineageMode.Continue;
    }

    internal sealed class TradeDirective
    {
        public int SchemaVersion { get; init; }
        public string Id { get; init; }
        public DateTimeOffset CreatedAt { get; init; }
        public TradeDirection Direction { get; init; }
        public DateTimeOffset NotBefore { get; init; }
        public DateTimeOffset ExpiresAt { get; init; }
        public PriceRange OrderPriceRange { get; init; }
        public PriceRange ContextPriceRange { get; init; }
        public PriceRange AddPriceRange { get; init; }
        public PriceTrigger PreEntryInvalidation { get; init; }
        public IReadOnlySet<ResolutionType> AllowedResolutions { get; init; }
        public int BaseQuantity { get; init; }
        public int AddQuantity { get; init; }
        public int MaxPositionQuantity { get; init; }
        public bool AddsAllowed { get; init; }
        public int MaxBaseReentries { get; init; }
        public TargetMode TargetMode { get; init; }
        public double TargetPrice { get; init; }
        public string TargetReference { get; init; }
        public DirectiveLineage Lineage { get; init; }
        public string Notes { get; init; }
        public string Digest { get; init; }

    }

    internal sealed class ControlCommand
    {
        public int SchemaVersion { get; init; }
        public string CommandId { get; init; }
        public DateTimeOffset IssuedAt { get; init; }
        public ControlAction Action { get; init; }
        public string DirectiveId { get; init; }
        public string Reason { get; init; }
        public string Digest { get; init; }
    }

    internal static class DirectiveContracts
    {
        private static readonly Regex IdPattern = new(
            "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            RegexOptions.CultureInvariant | RegexOptions.Compiled);

        private static readonly Regex OffsetPattern = new(
            "(?:Z|[+-][0-9]{2}:[0-9]{2})$",
            RegexOptions.CultureInvariant | RegexOptions.IgnoreCase | RegexOptions.Compiled);

        public static TradeDirective ParseTradeDirective(
            string json,
            int instanceMaxQuantity,
            bool allowLegacyWeightedBreakeven = false)
        {
            using JsonDocument document = ParseDocument(json);
            JsonElement root = RequireObject(document.RootElement, "directive");
            EnsureProperties(root, "directive",
                new[]
                {
                    "schema_version", "kind", "id", "status", "created_at", "side",
                    "window", "entry", "sizing", "retries", "stop", "target",
                    "lineage", "notes",
                },
                new[]
                {
                    "schema_version", "kind", "id", "status", "created_at", "side",
                    "window", "entry", "sizing", "retries", "stop", "target",
                });

            int schemaVersion = RequireInt(root, "schema_version", "directive");
            RequireConstant(schemaVersion, 1, "directive.schema_version");
            RequireConstant(RequireString(root, "kind", "directive"), "TRADE_DIRECTIVE", "directive.kind");
            RequireConstant(RequireString(root, "status", "directive"), "active", "directive.status");
            string id = ValidateId(RequireString(root, "id", "directive"), "directive.id");
            DateTimeOffset createdAt = RequireTimestamp(root, "created_at", "directive");

            string sideText = RequireString(root, "side", "directive");
            TradeDirection direction = sideText switch
            {
                "long" => TradeDirection.Long,
                "short" => TradeDirection.Short,
                _ => throw Invalid("directive.side must be 'long' or 'short'"),
            };

            JsonElement window = RequireObjectProperty(root, "window", "directive");
            EnsureProperties(window, "directive.window",
                new[] { "not_before", "expires_at" },
                new[] { "not_before", "expires_at" });
            DateTimeOffset notBefore = RequireTimestamp(window, "not_before", "directive.window");
            DateTimeOffset expiresAt = RequireTimestamp(window, "expires_at", "directive.window");
            if (expiresAt <= notBefore)
                throw Invalid("directive.window.expires_at must be after not_before");
            if (createdAt > expiresAt)
                throw Invalid("directive.created_at must not be after expires_at");

            JsonElement entry = RequireObjectProperty(root, "entry", "directive");
            EnsureProperties(entry, "directive.entry",
                new[]
                {
                    "mode", "order_price_range", "context_price_range", "add_price_range",
                    "pre_entry_invalidation", "allowed_resolutions",
                },
                new[]
                {
                    "mode", "order_price_range", "context_price_range", "add_price_range",
                    "pre_entry_invalidation", "allowed_resolutions",
                });
            RequireConstant(RequireString(entry, "mode", "directive.entry"),
                "contest_transition", "directive.entry.mode");
            PriceRange orderRange = ParsePriceRange(
                RequireObjectProperty(entry, "order_price_range", "directive.entry"),
                "directive.entry.order_price_range");
            PriceRange contextRange = ParsePriceRange(
                RequireObjectProperty(entry, "context_price_range", "directive.entry"),
                "directive.entry.context_price_range");
            if (contextRange.Lower > orderRange.Lower || contextRange.Upper < orderRange.Upper)
                throw Invalid("directive.entry.context_price_range must contain order_price_range");

            PriceRange addRange = null;
            JsonElement addRangeElement = RequireProperty(entry, "add_price_range", "directive.entry");
            if (addRangeElement.ValueKind != JsonValueKind.Null)
                addRange = ParsePriceRange(RequireObject(addRangeElement, "directive.entry.add_price_range"),
                    "directive.entry.add_price_range");
            if (addRange != null
                && (contextRange.Lower > addRange.Lower || contextRange.Upper < addRange.Upper))
            {
                throw Invalid("directive.entry.context_price_range must contain add_price_range");
            }

            PriceTrigger preEntryInvalidation = ParseOptionalTrigger(
                RequireProperty(entry, "pre_entry_invalidation", "directive.entry"),
                direction);
            HashSet<ResolutionType> allowedResolutions = ParseResolutions(
                RequireProperty(entry, "allowed_resolutions", "directive.entry"));

            JsonElement sizing = RequireObjectProperty(root, "sizing", "directive");
            EnsureProperties(sizing, "directive.sizing",
                new[] { "base_quantity", "add_quantity", "max_position_quantity", "adds_allowed" },
                new[] { "base_quantity", "add_quantity", "max_position_quantity", "adds_allowed" });
            int baseQuantity = RequirePositiveInt(sizing, "base_quantity", "directive.sizing");
            int addQuantity = RequireNonNegativeInt(sizing, "add_quantity", "directive.sizing");
            int maxPositionQuantity = RequirePositiveInt(sizing, "max_position_quantity", "directive.sizing");
            bool addsAllowed = RequireBool(sizing, "adds_allowed", "directive.sizing");
            if (baseQuantity > maxPositionQuantity)
                throw Invalid("directive.sizing.base_quantity must not exceed max_position_quantity");
            if (maxPositionQuantity > Math.Max(1, instanceMaxQuantity))
                throw Invalid("directive.sizing.max_position_quantity exceeds the strategy instance ceiling");
            if (addsAllowed)
            {
                if (addQuantity < 1 || addRange == null)
                    throw Invalid("scaling requires positive add_quantity and non-null add_price_range");
                if (baseQuantity + addQuantity > maxPositionQuantity)
                    throw Invalid("scaling requires capacity for one complete add");
            }
            else if (addQuantity != 0 || addRange != null)
            {
                throw Invalid("disabled scaling requires add_quantity=0 and add_price_range=null");
            }
            else if (maxPositionQuantity != baseQuantity)
            {
                throw Invalid("disabled scaling requires max_position_quantity=base_quantity");
            }

            JsonElement retries = RequireObjectProperty(root, "retries", "directive");
            EnsureProperties(retries, "directive.retries",
                new[] { "max_base_reentries" },
                new[] { "max_base_reentries" });
            int maxBaseReentries = RequireNonNegativeInt(retries, "max_base_reentries", "directive.retries");
            if (maxBaseReentries > 10)
                throw Invalid("directive.retries.max_base_reentries must not exceed 10");

            ParseStop(RequireObjectProperty(root, "stop", "directive"),
                allowLegacyWeightedBreakeven);
            (TargetMode targetMode, double targetPrice, string targetReference) = ParseTarget(
                RequireObjectProperty(root, "target", "directive"), direction);

            if (direction == TradeDirection.Long && targetPrice <= orderRange.Lower)
                throw Invalid("long target must be above the entry range lower boundary");
            if (direction == TradeDirection.Short && targetPrice >= orderRange.Upper)
                throw Invalid("short target must be below the entry range upper boundary");

            DirectiveLineage lineage = ParseLineage(root);
            string notes = OptionalString(root, "notes", "directive", 4096);
            return new TradeDirective
            {
                SchemaVersion = schemaVersion,
                Id = id,
                CreatedAt = createdAt,
                Direction = direction,
                NotBefore = notBefore,
                ExpiresAt = expiresAt,
                OrderPriceRange = orderRange,
                ContextPriceRange = contextRange,
                AddPriceRange = addRange,
                PreEntryInvalidation = preEntryInvalidation,
                AllowedResolutions = allowedResolutions,
                BaseQuantity = baseQuantity,
                AddQuantity = addQuantity,
                MaxPositionQuantity = maxPositionQuantity,
                AddsAllowed = addsAllowed,
                MaxBaseReentries = maxBaseReentries,
                TargetMode = targetMode,
                TargetPrice = targetPrice,
                TargetReference = targetReference,
                Lineage = lineage,
                Notes = notes,
                Digest = CanonicalDigest(root),
            };
        }

        public static ControlCommand ParseControlCommand(string json)
        {
            using JsonDocument document = ParseDocument(json);
            JsonElement root = RequireObject(document.RootElement, "control");
            EnsureProperties(root, "control",
                new[]
                {
                    "schema_version", "kind", "command_id", "issued_at", "action",
                    "directive_id", "reason",
                },
                new[] { "schema_version", "kind", "command_id", "issued_at", "action" });

            int schemaVersion = RequireInt(root, "schema_version", "control");
            RequireConstant(schemaVersion, 1, "control.schema_version");
            RequireConstant(RequireString(root, "kind", "control"), "CONTROL", "control.kind");
            string commandId = ValidateId(RequireString(root, "command_id", "control"), "control.command_id");
            DateTimeOffset issuedAt = RequireTimestamp(root, "issued_at", "control");
            string actionText = RequireString(root, "action", "control");
            ControlAction action = actionText switch
            {
                "FLAT" => ControlAction.Flat,
                "CANCEL_DIRECTIVE" => ControlAction.CancelDirective,
                _ => throw Invalid("control.action must be FLAT or CANCEL_DIRECTIVE"),
            };

            string directiveId = OptionalString(root, "directive_id", "control", 128);
            if (action == ControlAction.CancelDirective)
            {
                if (string.IsNullOrWhiteSpace(directiveId))
                    throw Invalid("CANCEL_DIRECTIVE requires directive_id");
                directiveId = ValidateId(directiveId, "control.directive_id");
            }
            else if (directiveId != null)
            {
                throw Invalid("FLAT must not contain directive_id");
            }

            return new ControlCommand
            {
                SchemaVersion = schemaVersion,
                CommandId = commandId,
                IssuedAt = issuedAt,
                Action = action,
                DirectiveId = directiveId,
                Reason = OptionalString(root, "reason", "control", 1024),
                Digest = CanonicalDigest(root),
            };
        }

        private static JsonDocument ParseDocument(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
                throw Invalid("JSON payload is empty");
            try
            {
                return JsonDocument.Parse(json, new JsonDocumentOptions
                {
                    AllowTrailingCommas = false,
                    CommentHandling = JsonCommentHandling.Disallow,
                    MaxDepth = 32,
                });
            }
            catch (JsonException ex)
            {
                throw Invalid($"invalid JSON: {ex.Message}");
            }
        }

        private static void ParseStop(JsonElement stop, bool allowLegacyWeightedBreakeven)
        {
            EnsureProperties(stop, "directive.stop",
                new[] { "base", "leveraged", "opposite_failure_object" },
                new[] { "base", "leveraged", "opposite_failure_object" });
            RequireConstant(RequireString(stop, "base", "directive.stop"),
                "reverse_entry_resolution", "directive.stop.base");
            string leveraged = RequireString(stop, "leveraged", "directive.stop");
            if (leveraged != "current_sponsor_failure"
                && !(allowLegacyWeightedBreakeven && leveraged == "weighted_breakeven"))
            {
                throw Invalid("directive.stop.leveraged must be 'current_sponsor_failure'");
            }
            RequireConstant(RequireString(stop, "opposite_failure_object", "directive.stop"),
                "flatten", "directive.stop.opposite_failure_object");
        }

        private static (TargetMode mode, double price, string reference) ParseTarget(
            JsonElement target,
            TradeDirection direction)
        {
            EnsureProperties(target, "directive.target",
                new[] { "mode", "price", "direction", "reference" },
                new[] { "mode", "price", "direction" });
            string modeText = RequireString(target, "mode", "directive.target");
            RequireConstant(modeText, "HARD_TP", "directive.target.mode");
            string directionText = RequireString(target, "direction", "directive.target");
            string expected = direction == TradeDirection.Long ? "above" : "below";
            RequireConstant(directionText, expected, "directive.target.direction");
            return (
                TargetMode.HardTp,
                RequirePositiveDouble(target, "price", "directive.target"),
                OptionalString(target, "reference", "directive.target", 128));
        }

        private static PriceTrigger ParseOptionalTrigger(JsonElement value, TradeDirection direction)
        {
            if (value.ValueKind == JsonValueKind.Null)
                return null;
            JsonElement trigger = RequireObject(value, "directive.entry.pre_entry_invalidation");
            EnsureProperties(trigger, "directive.entry.pre_entry_invalidation",
                new[] { "direction", "price" },
                new[] { "direction", "price" });
            string text = RequireString(trigger, "direction", "directive.entry.pre_entry_invalidation");
            string expected = direction == TradeDirection.Long ? "below" : "above";
            RequireConstant(text, expected, "directive.entry.pre_entry_invalidation.direction");
            return new PriceTrigger
            {
                IsBelow = text == "below",
                Price = RequirePositiveDouble(trigger, "price", "directive.entry.pre_entry_invalidation"),
            };
        }

        private static DirectiveLineage ParseLineage(JsonElement root)
        {
            if (!root.TryGetProperty("lineage", out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return new DirectiveLineage { Mode = DirectiveLineageMode.New };
            }

            JsonElement lineage = RequireObject(value, "directive.lineage");
            EnsureProperties(lineage, "directive.lineage",
                new[] { "mode", "parent_directive_id" },
                new[] { "mode" });
            string modeText = RequireString(lineage, "mode", "directive.lineage");
            if (modeText == "NEW")
            {
                if (lineage.TryGetProperty("parent_directive_id", out JsonElement parent)
                    && parent.ValueKind != JsonValueKind.Null)
                {
                    throw Invalid("directive.lineage.parent_directive_id must be absent or null for NEW");
                }
                return new DirectiveLineage { Mode = DirectiveLineageMode.New };
            }

            if (modeText == "CONTINUE")
            {
                string parentId = ValidateId(
                    RequireString(lineage, "parent_directive_id", "directive.lineage"),
                    "directive.lineage.parent_directive_id");
                return new DirectiveLineage
                {
                    Mode = DirectiveLineageMode.Continue,
                    ParentDirectiveId = parentId,
                };
            }

            throw Invalid("directive.lineage.mode must be NEW or CONTINUE");
        }

        private static HashSet<ResolutionType> ParseResolutions(JsonElement value)
        {
            if (value.ValueKind != JsonValueKind.Array)
                throw Invalid("directive.entry.allowed_resolutions must be an array");
            var result = new HashSet<ResolutionType>();
            foreach (JsonElement item in value.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.String)
                    throw Invalid("allowed_resolutions entries must be strings");
                ResolutionType resolution = item.GetString() switch
                {
                    "direct_conversion" => ResolutionType.DirectConversion,
                    "supported_reclaim" => ResolutionType.SupportedReclaim,
                    _ => throw Invalid("unknown allowed resolution"),
                };
                if (!result.Add(resolution))
                    throw Invalid("allowed_resolutions must be unique");
            }
            if (result.Count < 1 || result.Count > 2)
                throw Invalid("allowed_resolutions must contain one or two entries");
            return result;
        }

        private static PriceRange ParsePriceRange(JsonElement range, string path)
        {
            EnsureProperties(range, path, new[] { "lower", "upper" }, new[] { "lower", "upper" });
            double lower = RequirePositiveDouble(range, "lower", path);
            double upper = RequirePositiveDouble(range, "upper", path);
            if (lower > upper)
                throw Invalid($"{path}.lower must not exceed upper");
            return new PriceRange { Lower = lower, Upper = upper };
        }

        private static JsonElement RequireObjectProperty(JsonElement parent, string name, string path)
            => RequireObject(RequireProperty(parent, name, path), $"{path}.{name}");

        private static JsonElement RequireObject(JsonElement value, string path)
        {
            if (value.ValueKind != JsonValueKind.Object)
                throw Invalid($"{path} must be an object");
            return value;
        }

        private static JsonElement RequireProperty(JsonElement parent, string name, string path)
        {
            if (!parent.TryGetProperty(name, out JsonElement value))
                throw Invalid($"{path}.{name} is required");
            return value;
        }

        private static string RequireString(JsonElement parent, string name, string path)
        {
            JsonElement value = RequireProperty(parent, name, path);
            if (value.ValueKind != JsonValueKind.String)
                throw Invalid($"{path}.{name} must be a string");
            string result = value.GetString();
            if (string.IsNullOrWhiteSpace(result))
                throw Invalid($"{path}.{name} must not be empty");
            return result;
        }

        private static string OptionalString(JsonElement parent, string name, string path, int maxLength)
        {
            if (!parent.TryGetProperty(name, out JsonElement value))
                return null;
            if (value.ValueKind != JsonValueKind.String)
                throw Invalid($"{path}.{name} must be a string");
            string result = value.GetString();
            if (result != null && result.Length > maxLength)
                throw Invalid($"{path}.{name} exceeds {maxLength} characters");
            return result;
        }

        private static bool RequireBool(JsonElement parent, string name, string path)
        {
            JsonElement value = RequireProperty(parent, name, path);
            if (value.ValueKind != JsonValueKind.True && value.ValueKind != JsonValueKind.False)
                throw Invalid($"{path}.{name} must be boolean");
            return value.GetBoolean();
        }

        private static int RequireInt(JsonElement parent, string name, string path)
        {
            JsonElement value = RequireProperty(parent, name, path);
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out int result))
                throw Invalid($"{path}.{name} must be an integer");
            return result;
        }

        private static int RequirePositiveInt(JsonElement parent, string name, string path)
        {
            int value = RequireInt(parent, name, path);
            if (value < 1)
                throw Invalid($"{path}.{name} must be positive");
            return value;
        }

        private static int RequireNonNegativeInt(JsonElement parent, string name, string path)
        {
            int value = RequireInt(parent, name, path);
            if (value < 0)
                throw Invalid($"{path}.{name} must be non-negative");
            return value;
        }

        private static double RequirePositiveDouble(JsonElement parent, string name, string path)
        {
            JsonElement value = RequireProperty(parent, name, path);
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out double result)
                || !double.IsFinite(result) || result <= 0)
            {
                throw Invalid($"{path}.{name} must be a positive finite number");
            }
            return result;
        }

        private static DateTimeOffset RequireTimestamp(JsonElement parent, string name, string path)
        {
            string text = RequireString(parent, name, path);
            if (!OffsetPattern.IsMatch(text)
                || !DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture,
                    DateTimeStyles.RoundtripKind, out DateTimeOffset result))
            {
                throw Invalid($"{path}.{name} must be an RFC 3339 timestamp with offset");
            }
            return result;
        }

        private static string ValidateId(string id, string path)
        {
            if (id.Length > 128 || !IdPattern.IsMatch(id))
                throw Invalid($"{path} has invalid format");
            return id;
        }

        private static void EnsureProperties(
            JsonElement element,
            string path,
            IEnumerable<string> allowed,
            IEnumerable<string> required)
        {
            var allowedSet = new HashSet<string>(allowed, StringComparer.Ordinal);
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (JsonProperty property in element.EnumerateObject())
            {
                if (!seen.Add(property.Name))
                    throw Invalid($"{path} contains duplicate property '{property.Name}'");
                if (!allowedSet.Contains(property.Name))
                    throw Invalid($"{path} contains unknown property '{property.Name}'");
            }
            foreach (string name in required)
            {
                if (!seen.Contains(name))
                    throw Invalid($"{path}.{name} is required");
            }
        }

        private static void RequireConstant<T>(T actual, T expected, string path)
        {
            if (!EqualityComparer<T>.Default.Equals(actual, expected))
                throw Invalid($"{path} must equal {expected}");
        }

        private static string CanonicalDigest(JsonElement root)
        {
            using var stream = new MemoryStream();
            using (var writer = new Utf8JsonWriter(stream))
                WriteCanonical(writer, root);
            byte[] hash = SHA256.HashData(stream.ToArray());
            return Convert.ToHexString(hash).ToLowerInvariant();
        }

        private static void WriteCanonical(Utf8JsonWriter writer, JsonElement element)
        {
            switch (element.ValueKind)
            {
                case JsonValueKind.Object:
                    writer.WriteStartObject();
                    foreach (JsonProperty property in element.EnumerateObject()
                        .OrderBy(p => p.Name, StringComparer.Ordinal))
                    {
                        writer.WritePropertyName(property.Name);
                        WriteCanonical(writer, property.Value);
                    }
                    writer.WriteEndObject();
                    break;
                case JsonValueKind.Array:
                    writer.WriteStartArray();
                    foreach (JsonElement item in element.EnumerateArray())
                        WriteCanonical(writer, item);
                    writer.WriteEndArray();
                    break;
                default:
                    element.WriteTo(writer);
                    break;
            }
        }

        private static InvalidDataException Invalid(string message)
            => new(message);
    }
}
