using System;

namespace ExecAssistantRuntime
{
    internal sealed class BookContinuityUpdate
    {
        public bool HasSeenUsableBook { get; init; }
        public bool IsUsable { get; init; }
        public bool StartedUnusable { get; init; }
        public bool ReasonChanged { get; init; }
        public bool ConfirmedLoss { get; init; }
        public bool Recovered { get; init; }
        public bool RecoveredAfterConfirmedLoss { get; init; }
        public string InitialReason { get; init; }
        public string LatestReason { get; init; }
        public DateTime UnusableSinceUtc { get; init; }
        public DateTime LastUsableUtc { get; init; }
        public double UnusableSeconds { get; init; }
    }

    /// <summary>
    /// Separates a rejected sample from a confirmed forward-data discontinuity.
    /// The tracker intentionally requires one usable sample before it can declare
    /// loss; startup is a warm-up state, not a recovery event.
    /// </summary>
    internal sealed class BookContinuityTracker
    {
        private DateTime _lastUsableUtc = DateTime.MinValue;
        private DateTime _unusableSinceUtc = DateTime.MinValue;
        private string _initialReason;
        private string _latestReason;
        private bool _lossConfirmed;

        public BookContinuityUpdate ObserveUsable(DateTime nowUtc)
        {
            nowUtc = NormalizeUtc(nowUtc);
            bool hadSeenUsable = _lastUsableUtc != DateTime.MinValue;
            bool recovered = hadSeenUsable
                && _unusableSinceUtc != DateTime.MinValue;
            bool recoveredAfterLoss = recovered && _lossConfirmed;
            double unusableSeconds = recovered
                ? Math.Max(0, (nowUtc - _unusableSinceUtc).TotalSeconds)
                : 0;
            DateTime unusableSinceUtc = recovered
                ? _unusableSinceUtc
                : DateTime.MinValue;
            DateTime priorUsableUtc = _lastUsableUtc;
            string initialReason = _initialReason;
            string latestReason = _latestReason;

            _lastUsableUtc = nowUtc;
            _unusableSinceUtc = DateTime.MinValue;
            _initialReason = null;
            _latestReason = null;
            _lossConfirmed = false;

            return new BookContinuityUpdate
            {
                HasSeenUsableBook = true,
                IsUsable = true,
                Recovered = recovered,
                RecoveredAfterConfirmedLoss = recoveredAfterLoss,
                InitialReason = initialReason,
                LatestReason = latestReason,
                UnusableSinceUtc = unusableSinceUtc,
                LastUsableUtc = recovered ? priorUsableUtc : _lastUsableUtc,
                UnusableSeconds = unusableSeconds,
            };
        }

        public BookContinuityUpdate ObserveUnusable(
            DateTime nowUtc,
            string reason,
            double confirmationSeconds)
        {
            nowUtc = NormalizeUtc(nowUtc);
            reason = string.IsNullOrWhiteSpace(reason) ? "unknown" : reason;
            bool hasSeenUsable = _lastUsableUtc != DateTime.MinValue;
            bool started = false;
            bool reasonChanged = false;

            if (_unusableSinceUtc == DateTime.MinValue)
            {
                _unusableSinceUtc = nowUtc;
                _initialReason = reason;
                _latestReason = reason;
                started = hasSeenUsable;
            }
            else if (!string.Equals(_latestReason, reason, StringComparison.Ordinal))
            {
                _latestReason = reason;
                reasonChanged = hasSeenUsable;
            }

            double unusableSeconds = Math.Max(0,
                (nowUtc - _unusableSinceUtc).TotalSeconds);
            bool confirmed = hasSeenUsable
                && !_lossConfirmed
                && unusableSeconds >= Math.Max(0, confirmationSeconds);
            if (confirmed)
                _lossConfirmed = true;

            return new BookContinuityUpdate
            {
                HasSeenUsableBook = hasSeenUsable,
                IsUsable = false,
                StartedUnusable = started,
                ReasonChanged = reasonChanged,
                ConfirmedLoss = confirmed,
                InitialReason = _initialReason,
                LatestReason = _latestReason,
                UnusableSinceUtc = _unusableSinceUtc,
                LastUsableUtc = _lastUsableUtc,
                UnusableSeconds = unusableSeconds,
            };
        }

        public void Reset()
        {
            _lastUsableUtc = DateTime.MinValue;
            _unusableSinceUtc = DateTime.MinValue;
            _initialReason = null;
            _latestReason = null;
            _lossConfirmed = false;
        }

        private static DateTime NormalizeUtc(DateTime value)
            => value.Kind switch
            {
                DateTimeKind.Utc => value,
                DateTimeKind.Local => value.ToUniversalTime(),
                _ => DateTime.SpecifyKind(value, DateTimeKind.Utc),
            };
    }
}
