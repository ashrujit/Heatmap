using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KahnRuntime
{
    internal sealed class EvidenceInbox
    {
        private readonly string _path;
        private long _offset;

        public EvidenceInbox(string path)
        {
            _path = Environment.ExpandEnvironmentVariables(path ?? string.Empty);
            if (string.IsNullOrWhiteSpace(_path))
                throw new ArgumentException("Evidence path is empty.", nameof(path));
        }

        public IReadOnlyList<CampaignEvidence> ReadNewEvents(Action<string> errorSink = null)
        {
            if (!File.Exists(_path))
                return Array.Empty<CampaignEvidence>();

            byte[] bytes;
            long startOffset;
            int parseLength;
            try
            {
                using FileStream stream = new(
                    _path,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.ReadWrite);
                long length = stream.Length;
                if (length < _offset)
                    _offset = 0;
                startOffset = _offset;
                long available = Math.Max(0, length - startOffset);
                if (available <= 0)
                    return Array.Empty<CampaignEvidence>();
                if (available > int.MaxValue)
                {
                    errorSink?.Invoke("Evidence read skipped: unread span is too large.");
                    return Array.Empty<CampaignEvidence>();
                }

                bytes = new byte[available];
                stream.Seek(startOffset, SeekOrigin.Begin);
                int read = 0;
                while (read < bytes.Length)
                {
                    int next = stream.Read(bytes, read, bytes.Length - read);
                    if (next <= 0)
                        break;
                    read += next;
                }

                parseLength = LastCompleteLineLength(bytes, read);
            }
            catch (Exception ex) when (ex is IOException
                || ex is UnauthorizedAccessException)
            {
                errorSink?.Invoke("Evidence read failed: " + ex.Message);
                return Array.Empty<CampaignEvidence>();
            }

            if (parseLength <= 0)
                return Array.Empty<CampaignEvidence>();

            List<CampaignEvidence> events = new();
            string text = Encoding.UTF8.GetString(bytes, 0, parseLength);
            foreach (string rawLine in text.Split('\n'))
            {
                string line = rawLine.TrimEnd('\r');
                if (string.IsNullOrWhiteSpace(line))
                    continue;
                try
                {
                    events.Add(CampaignEvidenceParser.Parse(line));
                }
                catch (Exception ex)
                {
                    errorSink?.Invoke($"Evidence parse failed: {ex.Message}");
                }
            }
            _offset = startOffset + parseLength;
            return events;
        }

        private static int LastCompleteLineLength(byte[] bytes, int length)
        {
            for (int index = Math.Max(0, length - 1); index >= 0; index--)
            {
                if (bytes[index] == (byte)'\n')
                    return index + 1;
            }
            return 0;
        }
    }

    internal static class CampaignEvidenceParser
    {
        public static CampaignEvidence Parse(string json)
        {
            using JsonDocument document = JsonDocument.Parse(json);
            JsonElement root = CampaignPlanParser.RequireObject(document.RootElement, "evidence");
            string eventId = OptionalString(root, "event_id")
                ?? OptionalString(root, "id")
                ?? StableId(json);
            EvidenceKind kind = ParseEvidenceKind(
                OptionalString(root, "kind")
                ?? OptionalString(root, "event")
                ?? "unknown");
            DateTimeOffset? timestamp = OptionalTimestamp(root, "ts_utc")
                ?? OptionalTimestamp(root, "timestamp");
            if (!timestamp.HasValue)
                throw CampaignPlanParser.Invalid("evidence.ts_utc or evidence.timestamp is required");

            return new CampaignEvidence
            {
                SchemaVersion = OptionalInt(root, "schema_version", 1),
                EventId = eventId,
                Timestamp = timestamp.Value,
                Source = ParseEvidenceSource(OptionalString(root, "source") ?? "unknown"),
                Kind = kind,
                Side = ParseEvidenceSide(OptionalString(root, "side") ?? "none"),
                Price = OptionalDouble(root, "price"),
                Range = ParseOptionalRange(root),
                WaypointId = OptionalString(root, "waypoint_id"),
                RailId = OptionalString(root, "rail_id"),
                Volume = OptionalDouble(root, "volume"),
                Delta = OptionalDouble(root, "delta"),
                Score = OptionalDouble(root, "score"),
                Note = OptionalString(root, "note"),
            };
        }

        private static PriceRange ParseOptionalRange(JsonElement root)
        {
            if (root.TryGetProperty("range", out JsonElement range)
                && range.ValueKind == JsonValueKind.Object)
            {
                return CampaignPlanParser.ParseRange(range, "evidence.range");
            }
            if (root.TryGetProperty("lower", out JsonElement lower)
                && root.TryGetProperty("upper", out JsonElement upper)
                && lower.TryGetDouble(out double lowerValue)
                && upper.TryGetDouble(out double upperValue)
                && double.IsFinite(lowerValue)
                && double.IsFinite(upperValue))
            {
                if (lowerValue > upperValue)
                    (lowerValue, upperValue) = (upperValue, lowerValue);
                return new PriceRange { Lower = lowerValue, Upper = upperValue };
            }
            return null;
        }

        private static EvidenceSource ParseEvidenceSource(string text)
            => CampaignPlanParser.Normalize(text) switch
            {
                "price" => EvidenceSource.Price,
                "levelledger" or "ll" => EvidenceSource.LevelLedger,
                "bubbletape" => EvidenceSource.BubbleTape,
                "footprint" or "delta" => EvidenceSource.Footprint,
                "broker" => EvidenceSource.Broker,
                "replay" => EvidenceSource.Replay,
                _ => EvidenceSource.Unknown,
            };

        private static EvidenceKind ParseEvidenceKind(string text)
            => CampaignPlanParser.Normalize(text) switch
            {
                "pricetouch" or "touch" => EvidenceKind.PriceTouch,
                "pricecross" or "cross" => EvidenceKind.PriceCross,
                "priceaccept" or "accept" or "accepted" => EvidenceKind.PriceAccept,
                "pricereclaim" or "reclaim" => EvidenceKind.PriceReclaim,
                "railowned" or "owned" => EvidenceKind.RailOwned,
                "railheld" or "held" => EvidenceKind.RailHeld,
                "railfailed" or "failed" => EvidenceKind.RailFailed,
                "railtested" or "tested" => EvidenceKind.RailTested,
                "bubblefinalized" or "bubble" => EvidenceKind.BubbleFinalized,
                "absorption" or "absorbed" => EvidenceKind.Absorption,
                "sponsorfailed" => EvidenceKind.SponsorFailed,
                "positionchanged" or "position" => EvidenceKind.PositionChanged,
                "timer" => EvidenceKind.Timer,
                _ => EvidenceKind.Unknown,
            };

        private static EvidenceSide ParseEvidenceSide(string text)
            => CampaignPlanParser.Normalize(text) switch
            {
                "demand" => EvidenceSide.Demand,
                "supply" => EvidenceSide.Supply,
                "buy" or "buyer" or "buyers" => EvidenceSide.Buy,
                "sell" or "seller" or "sellers" => EvidenceSide.Sell,
                "long" => EvidenceSide.Long,
                "short" => EvidenceSide.Short,
                _ => EvidenceSide.None,
            };

        private static string OptionalString(JsonElement element, string property)
            => element.TryGetProperty(property, out JsonElement value)
                && value.ValueKind == JsonValueKind.String
                    ? value.GetString()
                    : null;

        private static int OptionalInt(JsonElement element, string property, int fallback)
            => element.TryGetProperty(property, out JsonElement value)
                && value.TryGetInt32(out int number)
                    ? number
                    : fallback;

        private static double? OptionalDouble(JsonElement element, string property)
        {
            if (!element.TryGetProperty(property, out JsonElement value)
                || value.ValueKind == JsonValueKind.Null)
            {
                return null;
            }
            return value.TryGetDouble(out double number) && double.IsFinite(number)
                ? number
                : null;
        }

        private static DateTimeOffset? OptionalTimestamp(JsonElement element, string property)
        {
            string text = OptionalString(element, property);
            if (string.IsNullOrWhiteSpace(text))
                return null;
            return DateTimeOffset.TryParse(text,
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal,
                out DateTimeOffset timestamp)
                    ? timestamp
                    : null;
        }

        private static string StableId(string text)
        {
            byte[] hash = SHA256.HashData(Encoding.UTF8.GetBytes(text ?? string.Empty));
            return "ev-" + Convert.ToHexString(hash, 0, 8).ToLowerInvariant();
        }
    }
}
