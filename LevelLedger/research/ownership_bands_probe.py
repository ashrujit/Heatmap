"""Research replay for LevelLedger ownership bands.

This is not indicator code. It reuses the LevelLedger snapshot math and tests a
different visual object: sparse bands that answer "who owns this leg, and where
are they wrong?"
"""

from __future__ import annotations

import argparse
import math
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from replay_levelledger import (
    BOOK_LOOKBACK_SEC,
    BROAD_LEVELS,
    EVENT_Z_THRESHOLD,
    BookSample,
    abbrev,
    build_sample,
    load_snapshots,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)


@dataclass
class OwnershipEvent:
    ts: datetime
    price_tick: int
    side: str
    abs_z: float
    kind: str


@dataclass
class CandidateBand:
    id: int
    evidence_side: str
    min_tick: int
    max_tick: int
    start_ts: datetime
    formed_ts: datetime
    last_event_ts: datetime
    event_count: int
    score: float
    max_abs_z: float
    kinds: set[str] = field(default_factory=set)
    state: str = "candidate"
    pending_confirm: str | None = None
    pending_confirm_ts: datetime | None = None


@dataclass
class OwnershipBand:
    id: int
    side: str
    source: str
    min_tick: int
    max_tick: int
    evidence_start_ts: datetime
    formed_ts: datetime
    owned_ts: datetime
    last_event_ts: datetime
    event_count: int
    score: float
    max_abs_z: float
    kinds: set[str]
    state: str = "owned"
    tested_ts: datetime | None = None
    held_ts: datetime | None = None
    failed_ts: datetime | None = None
    fail_price_tick: int | None = None
    pending_fail_ts: datetime | None = None


@dataclass
class Transition:
    ts: datetime
    action: str
    band_id: int
    side: str
    source: str
    min_tick: int
    max_tick: int
    event_count: int
    score: float
    max_abs_z: float
    current_mid_tick: int
    state: str
    note: str = ""


@dataclass
class FailureCluster:
    start_ts: datetime
    end_ts: datetime
    min_tick: int
    max_tick: int
    demand_fails: int = 0
    supply_fails: int = 0
    score: float = 0.0

    @property
    def total_fails(self) -> int:
        return self.demand_fails + self.supply_fails


class OwnershipProbe:
    def __init__(
        self,
        event_z: float,
        cluster_min_events: int,
        cluster_ticks: int,
        cluster_sec: int,
        cluster_min_score: float,
        confirm_ticks: int,
        confirm_sec: int,
        test_buffer_ticks: int,
        fail_buffer_ticks: int,
        fail_confirm_ticks: int,
        fail_sec: int,
        hold_confirm_ticks: int,
        book_lookback_sec: int = BOOK_LOOKBACK_SEC,
    ) -> None:
        self.event_z = max(1.0, event_z)
        self.cluster_min_events = max(2, cluster_min_events)
        self.cluster_ticks = max(1, cluster_ticks)
        self.cluster_sec = max(1, cluster_sec)
        self.cluster_min_score = max(0.0, cluster_min_score)
        self.confirm_ticks = max(1, confirm_ticks)
        self.confirm_sec = max(0, confirm_sec)
        self.test_buffer_ticks = max(0, test_buffer_ticks)
        self.fail_buffer_ticks = max(0, fail_buffer_ticks)
        self.fail_confirm_ticks = max(1, fail_confirm_ticks)
        self.fail_sec = max(0, fail_sec)
        self.hold_confirm_ticks = max(1, hold_confirm_ticks)
        self.book_lookback_sec = max(5, book_lookback_sec)

        self.samples: deque[BookSample] = deque()
        self.pending_events: deque[OwnershipEvent] = deque()
        self.candidates: list[CandidateBand] = []
        self.bands: list[OwnershipBand] = []
        self.transitions: list[Transition] = []
        self.next_band_id = 1
        self.current_mid_tick = 0

    def on_sample(self, sample: BookSample) -> None:
        now = sample.ts
        self.current_mid_tick = sample.mid_tick
        self.samples.append(sample)
        self.evict_samples(now, self.book_lookback_sec * 2)
        self.evict_pending_events(now)

        if len(self.samples) >= 5:
            mbi, sbi = self.mean_std(now, lambda s: s.bid_inner)
            mai, sai = self.mean_std(now, lambda s: s.ask_inner)
            mbc, sbc = self.mean_std(now, lambda s: s.bid_centroid)
            mac, sac = self.mean_std(now, lambda s: s.ask_centroid)

            zbi = (sample.bid_inner - mbi) / max(1.0, sbi)
            zai = (sample.ask_inner - mai) / max(1.0, sai)
            zbc = (sample.bid_centroid - mbc) / max(0.01, sbc)
            zac = (sample.ask_centroid - mac) / max(0.01, sac)

            self.fire(now, sample.mid_tick, zbi, "demand", "BID_BUILD", "BID_PULL")
            self.fire(now, sample.mid_tick, zbi, "supply", "BID_PULL", "BID_BUILD", negative_only=True)
            self.fire(now, sample.mid_tick, zai, "supply", "ASK_BUILD", "ASK_PULL")
            self.fire(now, sample.mid_tick, zai, "demand", "ASK_PULL", "ASK_BUILD", negative_only=True)
            self.fire(now, sample.mid_tick, zbc, "supply", "BID_OUT", "BID_IN")
            self.fire(now, sample.mid_tick, zbc, "demand", "BID_IN", "BID_OUT", negative_only=True)
            self.fire(now, sample.mid_tick, zac, "demand", "ASK_OUT", "ASK_IN")
            self.fire(now, sample.mid_tick, zac, "supply", "ASK_IN", "ASK_OUT", negative_only=True)

        self.update_candidates(now, sample.mid_tick)
        self.update_bands(now, sample.mid_tick)

    def evict_samples(self, now: datetime, seconds: int) -> None:
        cutoff = now - timedelta(seconds=seconds)
        while self.samples and self.samples[0].ts < cutoff:
            self.samples.popleft()

    def evict_pending_events(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.cluster_sec)
        while self.pending_events and self.pending_events[0].ts < cutoff:
            self.pending_events.popleft()

    def mean_std(self, now: datetime, selector) -> tuple[float, float]:
        cutoff = now - timedelta(seconds=self.book_lookback_sec)
        vals = [selector(s) for s in self.samples if s.ts >= cutoff]
        if len(vals) < 2:
            return 0.0, 0.0
        mean = sum(vals) / len(vals)
        var = sum(v * v for v in vals) / len(vals) - mean * mean
        return mean, math.sqrt(var) if var > 0 else 0.0

    def fire(
        self,
        ts: datetime,
        price_tick: int,
        z: float,
        side: str,
        kind: str,
        opposite_kind: str,
        *,
        negative_only: bool = False,
    ) -> None:
        if negative_only:
            if z >= -self.event_z:
                return
            abs_z = abs(z)
        else:
            if z <= self.event_z:
                return
            abs_z = abs(z)

        self.on_event(OwnershipEvent(ts, price_tick, side, abs_z, kind))

    def on_event(self, ev: OwnershipEvent) -> None:
        for candidate in self.candidates:
            if candidate.state != "candidate":
                continue
            if candidate.evidence_side != ev.side:
                continue
            if (ev.ts - candidate.last_event_ts).total_seconds() > self.cluster_sec:
                continue
            if ev.price_tick < candidate.min_tick - self.cluster_ticks:
                continue
            if ev.price_tick > candidate.max_tick + self.cluster_ticks:
                continue

            candidate.min_tick = min(candidate.min_tick, ev.price_tick)
            candidate.max_tick = max(candidate.max_tick, ev.price_tick)
            candidate.last_event_ts = ev.ts
            candidate.event_count += 1
            candidate.score += ev.abs_z
            candidate.max_abs_z = max(candidate.max_abs_z, ev.abs_z)
            candidate.kinds.add(ev.kind)
            return

        members = [ev]
        for pending in self.pending_events:
            if pending.side != ev.side:
                continue
            if abs(pending.price_tick - ev.price_tick) > self.cluster_ticks:
                continue
            if (ev.ts - pending.ts).total_seconds() > self.cluster_sec:
                continue
            members.append(pending)

        score = sum(member.abs_z for member in members)
        if len(members) >= self.cluster_min_events and score >= self.cluster_min_score:
            candidate = CandidateBand(
                id=self.next_band_id,
                evidence_side=ev.side,
                min_tick=min(member.price_tick for member in members),
                max_tick=max(member.price_tick for member in members),
                start_ts=min(member.ts for member in members),
                formed_ts=ev.ts,
                last_event_ts=max(member.ts for member in members),
                event_count=len(members),
                score=score,
                max_abs_z=max(member.abs_z for member in members),
                kinds={member.kind for member in members},
            )
            self.next_band_id += 1
            self.candidates.append(candidate)
            self.transitions.append(self.transition("FORM", candidate, ev.ts, "candidate"))

            member_ids = {id(member) for member in members}
            self.pending_events = deque(
                pending for pending in self.pending_events
                if id(pending) not in member_ids
            )
        else:
            self.pending_events.append(ev)

    def update_candidates(self, now: datetime, current_mid_tick: int) -> None:
        for candidate in self.candidates:
            if candidate.state != "candidate":
                continue

            favor = self.moved_with_evidence(candidate, current_mid_tick)
            adverse = self.moved_against_evidence(candidate, current_mid_tick)
            if favor:
                self.note_or_confirm(candidate, now, "favor", current_mid_tick)
            elif adverse:
                self.note_or_confirm(candidate, now, "adverse", current_mid_tick)
            else:
                candidate.pending_confirm = None
                candidate.pending_confirm_ts = None

    def note_or_confirm(
        self,
        candidate: CandidateBand,
        now: datetime,
        confirm_type: str,
        current_mid_tick: int,
    ) -> None:
        if candidate.pending_confirm != confirm_type:
            candidate.pending_confirm = confirm_type
            candidate.pending_confirm_ts = now
            return

        if candidate.pending_confirm_ts is None:
            candidate.pending_confirm_ts = now
            return

        if (now - candidate.pending_confirm_ts).total_seconds() < self.confirm_sec:
            return

        if confirm_type == "favor":
            side = candidate.evidence_side
            source = f"{side}_lean"
            action = "OWNED"
        else:
            side = opposite(candidate.evidence_side)
            source = f"{candidate.evidence_side}_consumed"
            action = "CONSUMED"

        band = OwnershipBand(
            id=candidate.id,
            side=side,
            source=source,
            min_tick=candidate.min_tick,
            max_tick=candidate.max_tick,
            evidence_start_ts=candidate.start_ts,
            formed_ts=candidate.formed_ts,
            owned_ts=now,
            last_event_ts=candidate.last_event_ts,
            event_count=candidate.event_count,
            score=candidate.score,
            max_abs_z=candidate.max_abs_z,
            kinds=set(candidate.kinds),
        )
        candidate.state = "confirmed"
        self.bands.append(band)
        self.transitions.append(self.band_transition(action, band, now, current_mid_tick))

    def moved_with_evidence(self, candidate: CandidateBand, current_mid_tick: int) -> bool:
        if candidate.evidence_side == "demand":
            return current_mid_tick >= candidate.max_tick + self.confirm_ticks
        return current_mid_tick <= candidate.min_tick - self.confirm_ticks

    def moved_against_evidence(self, candidate: CandidateBand, current_mid_tick: int) -> bool:
        if candidate.evidence_side == "demand":
            return current_mid_tick <= candidate.min_tick - self.confirm_ticks
        return current_mid_tick >= candidate.max_tick + self.confirm_ticks

    def update_bands(self, now: datetime, current_mid_tick: int) -> None:
        for band in self.bands:
            if band.state == "failed":
                continue

            if self.fail_condition(band, current_mid_tick):
                if band.pending_fail_ts is None:
                    band.pending_fail_ts = now
                fail_move = self.fail_move_confirmed(band, current_mid_tick)
                fail_time = (now - band.pending_fail_ts).total_seconds() >= self.fail_sec
                if fail_move or fail_time:
                    band.state = "failed"
                    band.failed_ts = now
                    band.fail_price_tick = current_mid_tick
                    self.transitions.append(self.band_transition("FAIL", band, now, current_mid_tick))
                continue

            band.pending_fail_ts = None

            if self.test_condition(band, current_mid_tick):
                if band.state != "tested":
                    band.state = "tested"
                    band.tested_ts = now
                    self.transitions.append(self.band_transition("TEST", band, now, current_mid_tick))
                continue

            if band.state == "tested" and self.hold_condition(band, current_mid_tick):
                band.state = "owned"
                band.held_ts = now
                self.transitions.append(self.band_transition("HOLD", band, now, current_mid_tick))

    def test_condition(self, band: OwnershipBand, current_mid_tick: int) -> bool:
        if band.side == "demand":
            return band.min_tick - self.fail_buffer_ticks <= current_mid_tick <= band.max_tick + self.test_buffer_ticks
        return band.min_tick - self.test_buffer_ticks <= current_mid_tick <= band.max_tick + self.fail_buffer_ticks

    def fail_condition(self, band: OwnershipBand, current_mid_tick: int) -> bool:
        if band.side == "demand":
            return current_mid_tick < band.min_tick - self.fail_buffer_ticks
        return current_mid_tick > band.max_tick + self.fail_buffer_ticks

    def fail_move_confirmed(self, band: OwnershipBand, current_mid_tick: int) -> bool:
        if band.side == "demand":
            return current_mid_tick <= band.min_tick - self.fail_confirm_ticks
        return current_mid_tick >= band.max_tick + self.fail_confirm_ticks

    def hold_condition(self, band: OwnershipBand, current_mid_tick: int) -> bool:
        if band.side == "demand":
            return current_mid_tick >= band.max_tick + self.hold_confirm_ticks
        return current_mid_tick <= band.min_tick - self.hold_confirm_ticks

    def transition(
        self,
        action: str,
        candidate: CandidateBand,
        ts: datetime,
        state: str,
    ) -> Transition:
        return Transition(
            ts=ts,
            action=action,
            band_id=candidate.id,
            side=candidate.evidence_side,
            source="candidate",
            min_tick=candidate.min_tick,
            max_tick=candidate.max_tick,
            event_count=candidate.event_count,
            score=candidate.score,
            max_abs_z=candidate.max_abs_z,
            current_mid_tick=self.current_mid_tick,
            state=state,
            note=",".join(sorted(candidate.kinds)),
        )

    def band_transition(
        self,
        action: str,
        band: OwnershipBand,
        ts: datetime,
        current_mid_tick: int,
    ) -> Transition:
        return Transition(
            ts=ts,
            action=action,
            band_id=band.id,
            side=band.side,
            source=band.source,
            min_tick=band.min_tick,
            max_tick=band.max_tick,
            event_count=band.event_count,
            score=band.score,
            max_abs_z=band.max_abs_z,
            current_mid_tick=current_mid_tick,
            state=band.state,
            note=",".join(sorted(band.kinds)),
        )

    def active_bands(self, now: datetime, current_mid_tick: int, topn: int) -> list[OwnershipBand]:
        active = [band for band in self.bands if band.state != "failed"]
        return sorted(
            active,
            key=lambda band: self.relevance_score(band, now, current_mid_tick),
            reverse=True,
        )[:topn]

    @staticmethod
    def relevance_score(band: OwnershipBand, now: datetime, current_mid_tick: int) -> float:
        center = (band.min_tick + band.max_tick) / 2.0
        distance = abs(current_mid_tick - center)
        age_min = max(0.0, (now - band.owned_ts).total_seconds() / 60.0)
        state_boost = 20.0 if band.state == "tested" else 0.0
        return band.score + state_boost - distance * 0.10 - age_min * 0.05


def opposite(side: str) -> str:
    return "supply" if side == "demand" else "demand"


def range_label(min_tick: int, max_tick: int) -> str:
    if min_tick == max_tick:
        return abbrev(min_tick)
    return f"{abbrev(min_tick)}-{abbrev(max_tick)}"


def side_label(side: str) -> str:
    return "DEMAND" if side == "demand" else "SUPPLY"


def print_transitions(
    probe: OwnershipProbe,
    window_start: datetime,
    window_end: datetime,
) -> None:
    print("\nOwnership transitions in window:")
    count = 0
    for tr in probe.transitions:
        if tr.ts < window_start or tr.ts > window_end:
            continue
        count += 1
        print(
            f"{ny_hms(tr.ts)} {tr.action:<8} "
            f"band#{tr.band_id:<3} {side_label(tr.side):<6} "
            f"{range_label(tr.min_tick, tr.max_tick):>13} "
            f"{tr.source:<15} "
            f"events={tr.event_count:<2} "
            f"score={tr.score:4.1f} "
            f"maxz={tr.max_abs_z:4.1f} "
            f"current={abbrev(tr.current_mid_tick):>7} "
            f"{tr.note}"
        )
    if count == 0:
        print("(none)")


def print_final_bands(probe: OwnershipProbe, now: datetime, topn: int) -> None:
    print(f"\nTop active ownership bands at {ny_hms(now)}:")
    active = probe.active_bands(now, probe.current_mid_tick, topn)
    if not active:
        print("(none)")
        return
    for band in active:
        print(
            f"band#{band.id:<3} {side_label(band.side):<6} "
            f"{range_label(band.min_tick, band.max_tick):>13} "
            f"{band.source:<15} "
            f"state={band.state:<6} "
            f"owned={ny_hms(band.owned_ts)} "
            f"events={band.event_count:<2} "
            f"score={band.score:4.1f} "
            f"maxz={band.max_abs_z:4.1f}"
        )


def duration_label(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def print_bucket_summary(
    probe: OwnershipProbe,
    window_start: datetime,
    window_end: datetime,
    bucket_min: int,
) -> None:
    if bucket_min <= 0:
        return

    bucket_delta = timedelta(minutes=bucket_min)
    rows: list[tuple[datetime, datetime, Counter[tuple[str, str]]]] = []
    start = window_start
    while start < window_end:
        end = min(start + bucket_delta, window_end)
        counts: Counter[tuple[str, str]] = Counter()
        for tr in probe.transitions:
            if tr.ts < start or tr.ts >= end:
                continue
            if tr.action in ("OWNED", "CONSUMED"):
                counts[("claim", tr.side)] += 1
                if tr.action == "CONSUMED":
                    counts[("consumed", tr.side)] += 1
            elif tr.action == "FAIL":
                counts[("fail", tr.side)] += 1
        rows.append((start, end, counts))
        start = end

    print(f"\nOwnership summary by {bucket_min}m bucket:")
    print("time           claim D/S  consumed D/S  fail D/S")
    for start, end, counts in rows:
        d_claim = counts[("claim", "demand")]
        s_claim = counts[("claim", "supply")]
        d_cons = counts[("consumed", "demand")]
        s_cons = counts[("consumed", "supply")]
        d_fail = counts[("fail", "demand")]
        s_fail = counts[("fail", "supply")]
        print(
            f"{ny_hms(start)}-{ny_hms(end)}  "
            f"{d_claim:>3}/{s_claim:<3}      "
            f"{d_cons:>3}/{s_cons:<3}        "
            f"{d_fail:>3}/{s_fail:<3}"
        )


def print_band_outcomes(
    probe: OwnershipProbe,
    window_start: datetime,
    window_end: datetime,
    topn: int,
) -> None:
    owned = [
        band for band in probe.bands
        if window_start <= band.owned_ts <= window_end
    ]
    print("\nOwned-in-window outcomes:")
    if not owned:
        print("(none)")
        return

    counts: Counter[tuple[str, str]] = Counter()
    for band in owned:
        if band.failed_ts is None:
            bucket = "active"
        else:
            life_sec = (band.failed_ts - band.owned_ts).total_seconds()
            if life_sec <= 60:
                bucket = "fail<=1m"
            elif life_sec <= 300:
                bucket = "fail<=5m"
            else:
                bucket = "fail>5m"
        counts[(band.side, bucket)] += 1

    for side in ("demand", "supply"):
        total = sum(counts[(side, bucket)] for bucket in ("active", "fail<=1m", "fail<=5m", "fail>5m"))
        print(
            f"{side_label(side):<6} total={total:<3} "
            f"active={counts[(side, 'active')]:<3} "
            f"fail<=1m={counts[(side, 'fail<=1m')]:<3} "
            f"fail<=5m={counts[(side, 'fail<=5m')]:<3} "
            f"fail>5m={counts[(side, 'fail>5m')]:<3}"
        )

    durable = sorted(
        owned,
        key=lambda band: (
            ((band.failed_ts or window_end) - band.owned_ts).total_seconds(),
            band.score,
        ),
        reverse=True,
    )[:topn]
    print(f"\nLongest-lived owned-in-window bands:")
    for band in durable:
        end_ts = band.failed_ts or window_end
        life = duration_label((end_ts - band.owned_ts).total_seconds())
        state = "active" if band.failed_ts is None else f"failed@{ny_hms(band.failed_ts)}"
        print(
            f"band#{band.id:<3} {side_label(band.side):<6} "
            f"{range_label(band.min_tick, band.max_tick):>13} "
            f"{band.source:<15} "
            f"owned={ny_hms(band.owned_ts)} "
            f"life={life:<7} "
            f"score={band.score:4.1f} "
            f"{state}"
        )


def print_failure_clusters(
    probe: OwnershipProbe,
    window_start: datetime,
    window_end: datetime,
    contested_sec: int,
    proximity_ticks: int,
    span_ticks: int,
    min_fails: int,
) -> None:
    fails = [
        tr for tr in probe.transitions
        if window_start <= tr.ts <= window_end and tr.action == "FAIL"
    ]
    clusters: list[FailureCluster] = []
    for tr in fails:
        matched: FailureCluster | None = None
        for cluster in clusters:
            if (tr.ts - cluster.end_ts).total_seconds() > contested_sec:
                continue
            if tr.max_tick < cluster.min_tick - proximity_ticks:
                continue
            if tr.min_tick > cluster.max_tick + proximity_ticks:
                continue
            if max(cluster.max_tick, tr.max_tick) - min(cluster.min_tick, tr.min_tick) > span_ticks:
                continue
            matched = cluster
            break

        if matched is None:
            matched = FailureCluster(
                start_ts=tr.ts,
                end_ts=tr.ts,
                min_tick=tr.min_tick,
                max_tick=tr.max_tick,
            )
            clusters.append(matched)
        else:
            matched.end_ts = tr.ts
            matched.min_tick = min(matched.min_tick, tr.min_tick)
            matched.max_tick = max(matched.max_tick, tr.max_tick)

        if tr.side == "demand":
            matched.demand_fails += 1
        else:
            matched.supply_fails += 1
        matched.score += tr.score

    two_sided = [
        cluster for cluster in clusters
        if cluster.demand_fails > 0
        and cluster.supply_fails > 0
        and cluster.total_fails >= min_fails
    ]
    print("\nTwo-sided failure clusters:")
    if not two_sided:
        print("(none)")
        return
    for cluster in sorted(two_sided, key=lambda item: item.start_ts):
        print(
            f"{ny_hms(cluster.start_ts)}-{ny_hms(cluster.end_ts)} "
            f"{range_label(cluster.min_tick, cluster.max_tick):>13} "
            f"fails D/S={cluster.demand_fails}/{cluster.supply_fails} "
            f"score={cluster.score:5.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", default="NQM6")
    parser.add_argument("--window", default="09:30-10:20")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=int, default=BOOK_LOOKBACK_SEC)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-ticks", type=int, default=10)
    parser.add_argument("--cluster-sec", type=int, default=90)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=8)
    parser.add_argument("--fail-sec", type=int, default=10)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--print-transitions", action="store_true")
    parser.add_argument("--bucket-min", type=int, default=30)
    parser.add_argument("--print-outcomes", action="store_true")
    parser.add_argument("--print-contested", action="store_true")
    parser.add_argument("--contested-sec", type=int, default=1200)
    parser.add_argument("--contested-proximity-ticks", type=int, default=80)
    parser.add_argument("--contested-span-ticks", type=int, default=240)
    parser.add_argument("--contested-min-fails", type=int, default=4)
    parser.add_argument("--topn", type=int, default=3)
    args = parser.parse_args()

    start_s, end_s = args.window.split("-", 1)
    window_start = parse_ny(args.date, start_s)
    window_end = parse_ny(args.date, end_s)
    replay_start = window_start - timedelta(minutes=args.warmup_min)

    snap = load_snapshots(args.symbol_dir, replay_start, window_end)
    first_snap, last_snap, duplicate_count, gaps = snapshot_timing_summary(
        snap,
        args.gap_threshold_sec,
    )

    probe = OwnershipProbe(
        event_z=args.event_z,
        cluster_min_events=args.cluster_min_events,
        cluster_ticks=args.cluster_ticks,
        cluster_sec=args.cluster_sec,
        cluster_min_score=args.cluster_min_score,
        confirm_ticks=args.confirm_ticks,
        confirm_sec=args.confirm_sec,
        test_buffer_ticks=args.test_buffer_ticks,
        fail_buffer_ticks=args.fail_buffer_ticks,
        fail_confirm_ticks=args.fail_confirm_ticks,
        fail_sec=args.fail_sec,
        hold_confirm_ticks=args.hold_confirm_ticks,
        book_lookback_sec=args.book_lookback_sec,
    )

    for row in snap.iter_rows(named=True):
        probe.on_sample(build_sample(row))

    print(
        f"{args.date} {args.window}  rows={snap.height:,}  "
        f"candidates={len(probe.candidates):,}  "
        f"owned={len(probe.bands):,}"
    )
    print(
        "params="
        f"event_z>{probe.event_z:g}, "
        f"n={probe.cluster_min_events}, "
        f"ticks={probe.cluster_ticks}, "
        f"sec={probe.cluster_sec}, "
        f"score>={probe.cluster_min_score:g}, "
        f"confirm={probe.confirm_ticks}t/{probe.confirm_sec}s"
    )
    print(
        f"snapshot_span={ny_hms(first_snap)}-{ny_hms(last_snap)}  "
        f"duplicate_timestamps={duplicate_count:,}"
    )
    if gaps:
        print(f"snapshot_gaps>{args.gap_threshold_sec:.1f}s={len(gaps)}")
    else:
        print(f"snapshot_gaps>{args.gap_threshold_sec:.1f}s=0")

    transition_count = sum(1 for tr in probe.transitions if window_start <= tr.ts <= window_end)
    print(f"ownership_transitions_in_window={transition_count}")
    print_bucket_summary(probe, window_start, window_end, args.bucket_min)
    if args.print_outcomes:
        print_band_outcomes(probe, window_start, window_end, args.topn)
    if args.print_contested:
        print_failure_clusters(
            probe,
            window_start,
            window_end,
            args.contested_sec,
            args.contested_proximity_ticks,
            args.contested_span_ticks,
            args.contested_min_fails,
        )
    if args.print_transitions:
        print_transitions(probe, window_start, window_end)
    print_final_bands(probe, window_end, args.topn)


if __name__ == "__main__":
    main()
