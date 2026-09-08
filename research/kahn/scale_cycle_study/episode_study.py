"""Causal shared-auction-episode research. No production policy or order routing."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path

import polars as pl
import study as s


OUT = s.REPO / "research/out/kahn-episodes-20260906"
TICK = .25
CONFIRMED = {"RailOwned", "RailHeld"}


def union(ranges):
    """Union actual tick coverage, not a hull that invents evidence in gaps."""
    result = []
    for lo, hi in sorted(set(tuple(r) for r in ranges)):
        if result and lo <= result[-1][1] + TICK:
            result[-1][1] = max(result[-1][1], hi)
        else:
            result.append([lo, hi])
    return result


class Market:
    def __init__(self, symbol, day):
        self.directory = s.OUT / f"{symbol}-{day}"
        self.events = s.read_lines(self.directory / "events.jsonl")
        self.quotes = pl.read_parquet(self.directory / "quotes.parquet").to_dicts()
        self.qt = [q["t"] for q in self.quotes]

    def quote(self, t, *, forward=False):
        i = bisect.bisect_left(self.qt, t) if forward else bisect.bisect_right(self.qt, t) - 1
        return self.quotes[i] if 0 <= i < len(self.qt) and abs(self.qt[i] - t) <= 2_000_000 else None


@dataclass
class Rail:
    id: str
    side: str
    lo: float
    hi: float
    kind: str
    first: int
    last: int
    tested: int | None = None
    held: int | None = None
    failed: int | None = None
    owned: int | None = None

    @classmethod
    def from_event(cls, e):
        r = cls(e["id"], e["side"], e["lo"], e["hi"], e["kind"], e["t"], e["t"])
        r.update(e)
        return r

    def update(self, e):
        self.kind, self.last = e["kind"], e["t"]
        if e["kind"] == "RailOwned":
            self.owned = e["t"]
        elif e["kind"] == "RailTested":
            self.tested = e["t"]
        elif e["kind"] == "RailHeld":
            self.held = e["t"]
        elif e["kind"] == "RailFailed":
            self.failed = e["t"]


@dataclass
class Episode:
    n: int
    start: int
    peak: float
    opening: str
    members: set = field(default_factory=set)
    attacked: set = field(default_factory=set)
    claims: set = field(default_factory=set)
    claim_last_confirmed: dict = field(default_factory=dict)
    offered: set = field(default_factory=set)
    min_price: float = float("inf")
    breaches: list = field(default_factory=list)
    resolved_at: int | None = None


class Observer:
    """Groups by an observed attack and its resolution, never by band count."""
    def __init__(self, side, seed, warm=(), retain_breached=True):
        self.side = "demand" if side == "long" else "supply"
        self.sign = 1 if side == "long" else -1
        self.seed = seed
        self.boundary = seed["t"]
        self.peak = self.sign * seed["price"]
        self.rails = {}
        for e in warm:
            self._update(e)
        if seed["seed"]["id"] not in self.rails or self.rails[seed["seed"]["id"]].last <= seed["seed"]["t"]:
            self._update(seed["seed"])
        self.forming = {k for k, r in self.rails.items() if r.side == self.side and r.kind in CONFIRMED}
        self.carried = {seed["seed"]["id"]}
        self.episode = None
        self.number = 0
        self.completed, self.offers, self.trace = [], [], []
        self.stopped = False
        self.retain_breached = retain_breached
        live_claims = [r for r in self.rails.values() if r.side != self.side
                       and r.kind != "RailFailed" and self.relevant(r)]
        if live_claims:
            self.open(seed["t"], "inherited_live_claim")
            for r in live_claims:
                self.episode.claims.add(r.id)
                self.episode.claim_last_confirmed[r.id] = r.last

    def _update(self, e):
        if e["kind"] == "Reset":
            self.rails.clear()
        elif e.get("id"):
            if e["id"] in self.rails:
                self.rails[e["id"]].update(e)
            else:
                self.rails[e["id"]] = Rail.from_event(e)

    def oriented(self, r):
        return (r.lo, r.hi) if self.sign > 0 else (-r.hi, -r.lo)

    def relevant(self, r):
        root_lo = min(self.sign * self.seed["seed"][k] for k in ("lo", "hi"))
        return self.oriented(r)[1] >= root_lo - 2 * TICK

    def open(self, t, reason):
        if self.episode is None:
            self.number += 1
            self.episode = Episode(self.number, t, self.peak, reason,
                                   members={k for k in self.forming | self.carried
                                            if self.rails[k].kind != "RailFailed"})

    def snapshot(self, t, price):
        ep = self.episode
        if ep is None:
            return None
        live = [self.rails[k] for k in ep.members if self.rails[k].kind in CONFIRMED]
        defended = [r for r in live if r.id in ep.attacked and r.held is not None
                    and r.tested is not None and r.held >= r.tested >= ep.start]
        failed = [k for k in ep.members if self.rails[k].kind == "RailFailed"]
        claims_live = [k for k in ep.claims if self.rails[k].kind != "RailFailed"]
        return {"episode": ep.n, "t": t, "time": s.clock(t), "start_t": ep.start,
                "start": s.clock(ep.start), "opening": ep.opening, "price": price,
                "pre_attack_extreme": self.sign * ep.peak,
                "members": sorted(ep.members), "attacked": sorted(ep.attacked),
                "defended": sorted(r.id for r in defended), "failed": sorted(failed),
                "untested": sorted(ep.members - ep.attacked),
                "claims": sorted(ep.claims), "claims_live": sorted(claims_live),
                "member_coverage": union((self.rails[k].lo, self.rails[k].hi) for k in ep.members),
                "defended_coverage": union((r.lo, r.hi) for r in defended),
                "claim_coverage": union((self.rails[k].lo, self.rails[k].hi) for k in ep.claims),
                "breach_times": list(ep.breaches),
                "repair_resolved_t": ep.resolved_at,
                "max_adverse_from_peak_ticks": max(0, (ep.peak - ep.min_price) / TICK)}

    def finish(self, t, price, reason):
        row = self.snapshot(t, price)
        row["resolution"] = reason
        self.completed.append(row)
        self.carried = set(row["defended"])
        if not self.carried:
            self.carried = {k for k in self.episode.members if self.rails[k].kind in CONFIRMED
                            and self.rails[k].owned is not None and self.rails[k].owned >= self.boundary}
        self.episode = None
        self.forming = set()
        self.boundary = t
        self.peak = self.sign * price

    def step(self, t, price, events=()):
        if self.stopped:
            return
        x = self.sign * price
        if any(e["kind"] == "Reset" for e in events):
            if self.episode:
                self.finish(t, price, "evidence_gap")
            self.stopped = True
            return
        # Preserve event order, but decide only after the complete captured sample.
        # Splitting one observation into equivalent IDs must not create early authority.
        for e in events:
            self._update(e)
            r = self.rails[e["id"]]
            if not self.relevant(r):
                continue
            same = r.side == self.side
            new_attack = (same and e["kind"] == "RailTested") or (not same and e["kind"] in CONFIRMED)
            if self.episode and self.episode.resolved_at is not None and new_attack:
                self.finish(t, price, "resolved_then_superseded")
            if same and e["kind"] in CONFIRMED:
                self.forming.add(r.id)
                if self.episode:
                    self.episode.members.add(r.id)
            if same and e["kind"] == "RailTested":
                self.forming.add(r.id)
                self.open(t, "same_side_test")
                self.episode.members.add(r.id)
                self.episode.attacked.add(r.id)
            if not same and e["kind"] in CONFIRMED:
                self.open(t, "opposing_claim")
                self.episode.claims.add(r.id)
                self.episode.claim_last_confirmed[r.id] = t
            if self.episode and same and e["kind"] == "RailFailed" and r.id in self.episode.members:
                self.episode.attacked.add(r.id)
        ep = self.episode
        if ep is None:
            self.peak = max(self.peak, x)
            return
        ep.min_price = min(ep.min_price, x)
        row = self.snapshot(t, price)
        live = [self.rails[k] for k in ep.members if self.rails[k].kind in CONFIRMED
                and x > self.oriented(self.rails[k])[1]]
        defended = [r for r in live if r.id in row["defended"]]
        fresh = [r for r in live if r.owned is not None and r.owned >= self.boundary]
        support = defended or fresh
        claim_edge = max((self.oriented(self.rails[k])[1] for k in ep.claims), default=None)
        cleared = bool(ep.claims) and not row["claims_live"] and x > claim_edge
        if cleared and ep.resolved_at is None:
            ep.resolved_at = t
            row["repair_resolved_t"] = t
        types = ["typed_clear"] if cleared else ["defense_only"] if not ep.claims and defended else []
        if not ep.claims and defended and x > ep.peak + TICK:
            types.append("defense_departed")
        for typ in types:
            if not support or typ in ep.offered:
                continue
            ep.offered.add(typ)
            proof = {r.id for r in support}
            self.offers.append({**row, "signature": typ,
                "completion": "renewed_defense" if defended else "clearance_rebuilt_after_breach" if ep.breaches else "clearance_without_defended_member",
                "support": sorted(proof), "support_coverage": union((r.lo, r.hi) for r in support),
                "support_last_t": max(r.last for r in support),
                "claim_failure_t": max((self.rails[k].failed for k in ep.claims), default=None),
                "claim_clearance_ticks": (x - claim_edge) / TICK if claim_edge is not None else None,
                "seconds_from_last_claim_confirmation": (t - max(ep.claim_last_confirmed.values())) / 1e6 if ep.claims else None,
                "recovered_pre_attack_extreme": x > ep.peak})
        if events:
            self.trace.append(row)
        all_attacked_failed = ep.attacked and all(self.rails[k].kind == "RailFailed" for k in ep.attacked)
        attacked_back = min((self.oriented(self.rails[k])[0] for k in ep.attacked), default=float("inf"))
        replacement = any(r.owned is not None and r.owned >= ep.start
                          and self.oriented(r)[1] >= attacked_back for r in live)
        if all_attacked_failed and not replacement:
            if self.retain_breached and row["claims_live"]:
                if not ep.breaches:
                    ep.breaches.append(t)
            else:
                self.finish(t, price, "attacked_structure_failed")
        elif live and not row["claims_live"] and x > ep.peak + TICK and (support or not ep.claims):
            self.finish(t, price, "extension_resumed")
        self.peak = max(self.peak, x)


def observe(case, market, root, warm=True, retain_breached=True):
    start, end = root["t"], root["end_t"]
    prelude = [e for e in market.events if s.stamp(case.day, case.start) <= e["t"] < start]
    if not warm or root["root_n"] > 1:
        prelude = []
    observer = Observer(case.side, root, prelude, retain_breached)
    event_groups = {t: list(rows) for t, rows in groupby(
        [e for e in market.events if start <= e["t"] <= end and e["kind"] != "Reset" and e.get("ready")], lambda e: e["t"])}
    resets = {e["t"]: [e] for e in market.events if start <= e["t"] <= end and e["kind"] == "Reset"}
    event_groups.update(resets)
    quotes = {q["t"]: q["mid"] for q in market.quotes if start <= q["t"] <= end}
    for t in sorted(set(quotes) | set(event_groups)):
        events = event_groups.get(t, [])
        price = quotes.get(t, events[-1].get("price") if events else None)
        if price is None:
            q = market.quote(t)
            price = q["mid"] if q else root["price"]
        observer.step(t, price, events)
    if observer.episode:
        q = market.quote(end)
        observer.finish(end, q["mid"] if q else root["price"], root["end_reason"])
    return observer


def simulate(case, market, root, offers, max_adds, admission, management):
    """Explicit inventory experiment: delayed BBO fills, group-risk trims, BE.

    No target is invented. End-window liquidation is an outcome mark, not harvest.
    Evidence-group management is experimental, not the production risk policy.
    """
    eligible = [r for r in offers if admission == "test_defense" or r["signature"] == "typed_clear"
                or (admission == "departure_defense" and r["signature"] == "defense_departed")]
    jobs = []
    for r in eligible:
        q = market.quote(r["t"] + 250_000, forward=True)
        if q and q["t"] < root["end_t"]:
            jobs.append((q["t"], r))
    known = {}
    for event in market.events:
        if event["t"] >= root["t"]:
            break
        if event["kind"] == "Reset":
            known.clear()
        elif event.get("id"):
            known[event["id"]] = event
    states = {k: event["kind"] for k, event in known.items()}
    events = [e for e in market.events if root["t"] <= e["t"] <= root["end_t"]]
    cursor, job, accepted, consumed = 0, 0, 0, set()
    tranches = [{"episode": 0, "quantity": 2, "price": root["price"], "support": [root["seed"]["id"]]}]
    actions, inventory, decisions = [], [], []
    realized = 0.0
    average = root["price"]
    be_trigger = None
    stopped = False
    latest_support = None
    def close(t, q, selected, reason):
        nonlocal realized, be_trigger
        price = q["bid"] - TICK if case.sign > 0 else q["ask"] + TICK
        quantity = sum(tr["quantity"] for tr in selected)
        for tr in selected:
            realized += case.sign * (price - tr["price"]) * tr["quantity"] / TICK
            tranches.remove(tr)
        if quantity:
            actions.append({"t": t, "time": s.clock(t), "action": "exit", "quantity": quantity,
                            "price": price, "reason": reason, "episodes": [tr["episode"] for tr in selected]})
            be_trigger = None

    def maintain_be(t, q):
        nonlocal be_trigger, stopped
        quantity = sum(tr["quantity"] for tr in tranches)
        if not accepted or quantity <= 2:
            be_trigger = None
            return
        executable = q["bid"] if case.sign > 0 else q["ask"]
        if be_trigger is not None and case.sign * (executable - be_trigger) <= 0:
            close(t, q, list(tranches), "weighted_be_proxy")
            stopped = True
            return
        candidate = (math.ceil(average / TICK - 1e-9) if case.sign > 0 else math.floor(average / TICK + 1e-9)) * TICK
        if case.sign * (executable - candidate) > 0:
            be_trigger = candidate
    for q in market.quotes:
        t = q["t"]
        if t < root["t"] or t > root["end_t"] or stopped:
            continue
        while cursor < len(events) and events[cursor]["t"] <= t:
            e = events[cursor]
            if e.get("id"):
                states[e["id"]] = e["kind"]
                known[e["id"]] = e
            cursor += 1
        failed = lambda ids: bool(ids) and all(states.get(k) == "RailFailed" for k in ids)
        if management == "tranche_groups":
            close(t, q, [tr for tr in tranches if tr["episode"] and failed(tr["support"])], "added_group_failed")
        elif management == "latest_group_campaign" and latest_support and failed(latest_support):
            close(t, q, list(tranches), "latest_confirmed_group_failed")
            stopped = True
        maintain_be(t, q)
        while job < len(jobs) and jobs[job][0] <= t:
            _, r = jobs[job]
            job += 1
            support = r["support"]
            current_support = [k for k in support if states.get(k) in CONFIRMED
                               and case.sign * q["mid"] > max(case.sign * known[k][v] for v in ("lo", "hi"))]
            root_back = min(case.sign * root["seed"][v] for v in ("lo", "hi"))
            new_opposition = any(event["side"] != case.same and event["kind"] != "RailFailed"
                                 and event["t"] > r["t"]
                                 and max(case.sign * event[v] for v in ("lo", "hi")) >= root_back - 2 * TICK
                                 for event in known.values())
            claims_live = any(states.get(k) != "RailFailed" for k in r.get("claims", []))
            clear = all(case.sign * q["mid"] > max(case.sign * v for v in pair)
                        for pair in r.get("claim_coverage", []))
            decision = {"t": t, "time": s.clock(t), "signal_time": r["time"], "episode": r["episode"],
                        "signature": r["signature"]}
            reason = ("position_closed" if stopped else "support_not_current" if not current_support
                      else "new_or_live_opposition" if new_opposition or claims_live
                      else "repair_not_clear" if not clear else None)
            if reason:
                decisions.append({**decision, "result": reason})
                continue
            # Management continues to see completed groups after the add budget is spent.
            if r["signature"] == "typed_clear":
                latest_support = list(current_support)
            if accepted >= max_adds or r["episode"] in consumed:
                decisions.append({**decision, "result": "budget_spent" if accepted >= max_adds else "episode_consumed"})
                continue
            price = q["ask"] + TICK if case.sign > 0 else q["bid"] - TICK
            quantity = sum(tr["quantity"] for tr in tranches)
            if case.sign * (price - average) <= 0:
                decisions.append({**decision, "result": "not_favorable_to_average"})
                continue
            # Assume average-cost position accounting: reductions do not select
            # a cheaper remaining broker entry price by choosing a research lot.
            average = (average * quantity + price * 2) / (quantity + 2)
            tranches.append({"episode": r["episode"], "quantity": 2, "price": price, "support": list(current_support)})
            accepted += 1
            consumed.add(r["episode"])
            decisions.append({**decision, "result": "filled_proxy"})
            actions.append({"t": t, "time": s.clock(t), "signal_time": r["time"], "action": "add",
                            "quantity": 2, "price": price, "episode": r["episode"], "signature": r["signature"],
                            "support": list(current_support)})
        maintain_be(t, q)
        inventory.append({"t": t, "quantity": sum(tr["quantity"] for tr in tranches),
                          "position_average": average, "be_trigger": be_trigger})
    quantity_at_end = sum(tr["quantity"] for tr in tranches)
    q = market.quote(root["end_t"])
    if q and tranches:
        close(root["end_t"], q, list(tranches), "root_failure" if root["end_reason"] == "root_failure" else "window_mark")
    return {"accepted_adds": accepted, "add_times": ";".join(a["signal_time"] for a in actions if a["action"] == "add"),
            "risk_exits": ";".join(a["time"] + ":" + a["reason"] for a in actions if a["action"] == "exit" and a["reason"] != "window_mark"),
            "quantity_before_cutoff": quantity_at_end,
            "unit_ticks_after_spread_and_one_tick_slippage": round(realized, 3),
            "actions": actions, "inventory": inventory, "decisions": decisions}


def cases():
    for symbol in ("NQ", "ES"):
        for day, side, start, end, label in (
            ("2026-09-03", "long", "10:55", "11:30", "main"),
            ("2026-09-04", "short", "10:00", "11:30", "main"),
            ("2026-09-03", "long", "10:00", "10:50", "earlier-control"),
            ("2026-09-04", "short", "09:40", "10:00", "earlier-control"),
        ):
            yield s.Case(symbol, day, side, start, end, label)


def csv_rows(rows, context):
    return [{**context, **{k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()}} for r in rows]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    episodes, offers, summaries, actions = [], [], [], []
    for case in cases():
        market = Market(case.symbol, case.day)
        for root in s.root_seeds(case, market):
            for warm in (False, True):
                context = {"case": case.name, "side": case.side, "root_n": root["root_n"], "warm": warm}
                directory = OUT / case.name / f"root-{root['root_n']}" / ("warm" if warm else "cold")
                observer = observe(case, market, root, warm)
                s.write_json(directory / "root.json", root)
                s.write_lines(directory / "episodes.jsonl", observer.completed)
                s.write_lines(directory / "offers.jsonl", observer.offers)
                s.write_lines(directory / "trace.jsonl", observer.trace)
                reset_observer = observe(case, market, root, warm, retain_breached=False)
                s.write_lines(directory / "reset_on_breach_offers.jsonl", reset_observer.offers)
                episodes.extend(csv_rows(observer.completed, context))
                offers.extend(csv_rows(observer.offers, context))
                for admission in ("typed_only", "departure_defense", "test_defense"):
                    for maximum in (0, 2, 3):
                        for management in ("root_only", "tranche_groups", "latest_group_campaign"):
                            if maximum == 0 and (admission != "typed_only" or management != "root_only"):
                                continue
                            result = simulate(case, market, root, observer.offers, maximum, admission, management)
                            config = {**context, "admission": admission, "max_adds": maximum, "management": management}
                            s.write_json(directory / f"{admission}-{maximum}-{management}.json", {**config, **result})
                            summaries.append({**config, **{k: v for k, v in result.items() if k not in ("actions", "inventory", "decisions")}})
                            actions.extend(csv_rows(result["actions"], config))
                print(json.dumps({**context, "episodes": len(observer.completed),
                                  "offers": dict(Counter(r["signature"] for r in observer.offers))}), flush=True)
    s.write_csv(OUT / "episodes.csv", episodes)
    s.write_csv(OUT / "offers.csv", offers)
    s.write_csv(OUT / "inventory_summary.csv", summaries)
    s.write_csv(OUT / "actions.csv", actions)
    s.write_json(OUT / "manifest.json", {
        "scope": "Shared episode hypothesis; NQ priority mornings, ES same mornings, earlier same-session controls",
        "grouping": "Fresh or reattacked same-side areas since prior episode resolution; opens on TEST or opposing OWN/HOLD; closes on renewed excursion beyond pre-attack quote extreme with no live tracked opposition",
        "claims": "All relevant opposing OWN/HOLD members observed during episode, exact-ID typed failure; no count votes",
        "signature": "typed_clear baseline; defense_departed adds recovery of pre-attack extreme to test/hold; raw defense_only is the aggressive control, not typed failure",
        "warm": "Adopts observations from requested window to root fill; failed-root retry starts cold; no pre-fill failure reused",
        "limits": "Seeded entries; experiment not approved policy. Member coverage retains holes. One-second captured BBO, 250ms minimum fill delay, one adverse tick. Group risk exits, average-cost BE proxy and window liquidation, not broker simulation or target harvest. Reductions do not lower broker average by selecting a research lot. No fees. No independent holdouts. Clearance timing reported, not used as proof of fast continuation.",
        "research_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "production_hashes": {name: hashlib.sha256((s.REPO / 'KahnRuntime' / name).read_bytes()).hexdigest()
                              for name in ('CampaignPolicy.cs', 'CampaignContracts.cs', 'LevelLedgerEvidenceEngine.cs')},
        "input_hashes": {f"{symbol}-{day}/{name}": hashlib.sha256((s.OUT / f"{symbol}-{day}" / name).read_bytes()).hexdigest()
                         for symbol in ('NQ', 'ES') for day in ('2026-09-03', '2026-09-04')
                         for name in ('events.jsonl', 'quotes.parquet', 'quality.json')},
    })


if __name__ == "__main__":
    main()
