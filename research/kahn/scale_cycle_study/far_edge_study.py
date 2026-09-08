"""Offline far-edge repair ablations. The September 6 model remains frozen."""
from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import polars as pl

import audit_episodes as audit
import episode_study as old
import stress_episodes as stress
import study as s


OUT = s.REPO / "research/out/kahn-far-edge-20260907"
MODELS = ("frozen", "edge_gate", "edge_local_mid", "edge_local_trade")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize_batch(events):
    """Artificial fragments need explicit parent bounds; never infer ID lineage."""
    result, seen = [], set()
    for row in events:
        if row.get("claim_id"):
            row = {**row, "id": row["claim_id"],
                   "lo": row["claim_lo"], "hi": row["claim_hi"]}
        key = (row.get("id"), row["kind"], row["t"])
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


class PriceCrossings:
    def __init__(self, sign, side, initial):
        self.sign, self.side = sign, side
        self.previous = sign * initial
        self.armed = set()
        self.records = []

    def walk(self, t, price, rails, relevant):
        x, previous = self.sign * price, self.previous
        hits, touches = [], set()
        for rail in rails.values():
            if rail.side != self.side or rail.failed is not None or not relevant(rail):
                continue
            back, front = sorted((self.sign * rail.lo, self.sign * rail.hi))
            if rail.id in self.armed and previous >= back and x < back:
                hits.append({"t": t, "id": rail.id, "price": price,
                             "lo": rail.lo, "hi": rail.hi, "reason": "far_edge_cross"})
            if rail.id in self.armed and x < previous and x <= front and previous >= back:
                touches.add(rail.id)
            if x >= front:
                self.armed.add(rail.id)
        self.previous = x
        self.records.extend(hits)
        return hits, touches

    def arm_current(self, price, rails):
        x = self.sign * price
        for rail in rails.values():
            if rail.side == self.side and rail.failed is None:
                front = max(self.sign * rail.lo, self.sign * rail.hi)
                if x >= front:
                    self.armed.add(rail.id)


class EdgeGate(old.Observer):
    """Isolate the extra prerequisite without changing old grouping or closure."""
    def __init__(self, side, seed, warm=()):
        super().__init__(side, seed, normalize_batch(warm))
        self.crossings = PriceCrossings(self.sign, self.side, seed["price"])
        self.crossings.arm_current(seed["price"], self.rails)
        self.rejected = []

    def step(self, t, price, events=()):
        events = normalize_batch(events)
        self.crossings.walk(t, price, self.rails, self.relevant)
        for row in events:
            rail = self.rails.get(row.get("id"))
            if rail and rail.side == self.side and row["kind"] == "RailFailed" and self.relevant(rail):
                self.crossings.records.append({"t": t, "id": rail.id, "price": price,
                                               "lo": rail.lo, "hi": rail.hi, "reason": "typed_same_failure"})
        count = len(self.offers)
        super().step(t, price, events)
        keep = []
        for row in self.offers[count:]:
            breaches = [b for b in self.crossings.records
                        if row["start_t"] <= b["t"] <= row["t"] and b["id"] in row["members"]]
            tagged = {**row, "far_edge_breaches": breaches}
            (keep if breaches else self.rejected).append(tagged)
        self.offers[count:] = keep
        self.crossings.arm_current(price, self.rails)


class ExcursionObserver(old.Observer):
    """Repair starts at a far-edge breach, not TEST or an opposing OWN alone.

    Locality is a causal hypothesis: claims intersect the observed adverse
    excursion from its pre-breach extreme. It is not an ownership hull.
    """
    def __init__(self, side, seed, warm=()):
        super().__init__(side, seed, normalize_batch(warm))
        # Live warm claims remain known, but cannot open a repair without a breach.
        self.episode, self.number = None, 0
        self.crossings = PriceCrossings(self.sign, self.side, seed["price"])
        self.crossings.arm_current(seed["price"], self.rails)
        self.touches = set()
        self.member_reasons = {}
        self.ep_breaches = []
        self.ignored = []
        self.resolved_peak = None

    def intersects(self, rail):
        back, front = self.oriented(rail)
        return front >= self.episode.min_price and back <= self.episode.peak

    def start_repair(self, t, price, hits):
        ep = self.episode
        if ep and ep.resolved_at is not None and t > ep.resolved_at:
            prior_breaches = {b["id"] for b in self.ep_breaches}
            new_attack = any(hit["reason"] == "far_edge_cross" or hit["id"] not in prior_breaches for hit in hits)
            if new_attack:
                peak, touches = self.resolved_peak, set(self.touches)
                self.finish(t, price, "resolved_then_new_far_edge_attack")
                self.peak = peak if peak is not None else self.sign * price
                self.touches = touches
        if self.episode is None:
            super().open(t, hits[0]["reason"])
            self.episode.members = set()
            self.episode.min_price = min(self.sign * price, self.episode.peak)
            self.member_reasons, self.ep_breaches = {}, []
            self.resolved_peak = None
        for hit in hits:
            self.ep_breaches.append(hit)
            self.episode.members.add(hit["id"])
            self.episode.attacked.add(hit["id"])
            self.member_reasons.setdefault(hit["id"], "breached_claim")
        self.associate(t)

    def associate(self, t):
        ep = self.episode
        for rail in self.rails.values():
            if not self.relevant(rail) or not self.intersects(rail):
                continue
            if rail.side == self.side:
                if rail.kind != "RailFailed" or rail.id in ep.members:
                    ep.members.add(rail.id)
                    self.member_reasons.setdefault(rail.id, "owned_in_excursion" if rail.first >= ep.start else "existing_in_excursion")
                    if rail.id in self.touches:
                        ep.attacked.add(rail.id)
            elif rail.kind != "RailFailed":
                ep.claims.add(rail.id)
                ep.claim_last_confirmed[rail.id] = rail.last

    def walk(self, t, price):
        hits, touches = self.crossings.walk(t, price, self.rails, self.relevant)
        x = self.sign * price
        self.touches.update(touches)
        if self.episode and self.episode.resolved_at is not None:
            self.resolved_peak = max(self.resolved_peak, x)
        if hits:
            self.start_repair(t, price, hits)
        if self.episode:
            self.episode.min_price = min(self.episode.min_price, x)
            self.associate(t)
        elif x > self.peak:
            self.peak = x
            self.touches.clear()

    def snapshot(self, t, price):
        row = super().snapshot(t, price)
        if row is None:
            return None
        ep = self.episode
        # LL TEST often precedes the actual far-edge breach. A later HOLD can
        # defend that breach without requiring a second TEST message.
        defended = [self.rails[k] for k in ep.attacked
                    if self.rails[k].kind in old.CONFIRMED
                    and self.rails[k].held is not None and self.rails[k].held >= ep.start
                    and self.rails[k].tested is not None
                    and self.rails[k].held >= self.rails[k].tested]
        row.update(defended=sorted(r.id for r in defended),
                   defended_coverage=old.union((r.lo, r.hi) for r in defended),
                   far_edge_breaches=list(self.ep_breaches),
                   member_reasons=dict(self.member_reasons),
                   excursion_bounds=sorted((self.sign * ep.min_price, self.sign * ep.peak)))
        return row

    def finish(self, t, price, reason):
        super().finish(t, price, reason)
        self.touches.clear()

    def step(self, t, price, events=(), path=None):
        if self.stopped:
            return
        events = normalize_batch(events)
        if any(row["kind"] == "Reset" for row in events):
            if self.episode:
                self.finish(t, price, "evidence_gap")
            self.stopped = True
            return
        # Observe prices against claims known BEFORE this LL sample. Do not
        # retroactively test a newly confirmed claim against earlier trades.
        for pt, value in ([(t, price)] if path is None else path):
            self.walk(pt, value)
        for row in events:
            rail = self.rails.get(row.get("id"))
            if (rail and rail.side == self.side and rail.failed is None
                    and row["kind"] == "RailFailed" and self.relevant(rail)):
                self.start_repair(t, price, [{"t": t, "id": rail.id, "price": price,
                    "lo": rail.lo, "hi": rail.hi, "reason": "typed_same_failure"}])
        for row in events:
            self._update(row)
            rail = self.rails[row["id"]]
            if rail.side == self.side and row["kind"] in old.CONFIRMED and self.relevant(rail):
                self.forming.add(rail.id)
        self.crossings.arm_current(price if path is None else self.sign * self.crossings.previous, self.rails)
        ep = self.episode
        if ep is None:
            return
        self.associate(t)
        for row in events:
            if row.get("id") not in ep.members | ep.claims:
                self.ignored.append({"episode": ep.n, "t": t, "id": row.get("id"),
                                     "kind": row["kind"], "reason": "outside_excursion_or_not_live"})
        row = self.snapshot(t, price)
        x = self.sign * price
        live = [self.rails[k] for k in ep.members if self.rails[k].kind in old.CONFIRMED
                and x > self.oriented(self.rails[k])[1]]
        defended = [r for r in live if r.id in row["defended"]]
        fresh = [r for r in live if r.owned is not None and r.owned >= self.boundary]
        support = defended or fresh
        edge = max((self.oriented(self.rails[k])[1] for k in ep.claims), default=None)
        clear = bool(ep.claims) and not row["claims_live"] and x > edge
        if clear and ep.resolved_at is None:
            ep.resolved_at = t
            self.resolved_peak = x
            self.touches.clear()
            row["repair_resolved_t"] = t
        if clear and support and "typed_clear" not in ep.offered:
            ep.offered.add("typed_clear")
            self.offers.append({**row, "signature": "typed_clear",
                "completion": "renewed_defense" if defended else "clearance_rebuilt_after_breach" if ep.breaches else "clearance_without_defended_member",
                "support": sorted(r.id for r in support),
                "support_coverage": old.union((r.lo, r.hi) for r in support),
                "support_last_t": max(r.last for r in support),
                "claim_failure_t": max(self.rails[k].failed for k in ep.claims),
                "claim_clearance_ticks": (x - edge) / old.TICK,
                "recovered_pre_attack_extreme": x > ep.peak})
        if events:
            self.trace.append(row)
        if ep.attacked and all(self.rails[k].failed is not None for k in ep.attacked) and not ep.breaches:
            ep.breaches.append(t)
        # Stop banking a resolution after the excursion has fully departed.
        # No timer, price-speed threshold, or future formation information.
        if not row["claims_live"] and x > ep.peak + old.TICK:
            self.finish(t, price, "extension_resumed" if support else "departed_without_associated_proof")


def observe(case, market, root, model, warm=True):
    if model == "frozen":
        return old.observe(case, market, root, warm=warm)
    prelude = [row for row in market.events if s.stamp(case.day, case.start) <= row["t"] < root["t"]]
    if not warm or root["root_n"] > 1:
        prelude = []
    observer = (EdgeGate if model == "edge_gate" else ExcursionObserver)(case.side, root, prelude)
    first_quote = market.quote(root["t"])
    if first_quote:
        observer.crossings.previous = case.sign * first_quote["mid"]
    batches = defaultdict(list)
    for row in market.events:
        if root["t"] <= row["t"] <= root["end_t"] and (row["kind"] == "Reset" or row.get("ready")):
            batches[row["t"]].append(row)
    quotes = {q["t"]: q["mid"] for q in market.quotes if root["t"] <= q["t"] <= root["end_t"]}
    trade_cursor = bisect.bisect_left(market.trade_times, root["t"]) if model == "edge_local_trade" else None
    for t in sorted(set(quotes) | set(batches)):
        events = batches.get(t, [])
        q = market.quote(t)
        price = quotes.get(t, q["mid"] if q else events[-1].get("price", root["price"]))
        if trade_cursor is None:
            observer.step(t, price, events)
        else:
            end = bisect.bisect_right(market.trade_times, t)
            path = zip(market.trade_times[trade_cursor:end], market.trade_prices[trade_cursor:end])
            observer.step(t, price, events, path=path)
            trade_cursor = end
    if observer.episode:
        q = market.quote(root["end_t"])
        observer.finish(root["end_t"], q["mid"] if q else root["price"], root["end_reason"])
    return observer


def load_market(case):
    market = stress.market(case.day) if case.day in ("2026-09-01", "2026-09-02") else old.Market(case.symbol, case.day)
    ticks = pl.read_parquet(market.directory / "ticks.parquet").sort("timestamp_us")
    # Repeated same-price trades cannot change any crossing predicate.
    ticks = ticks.filter((pl.col("price") != pl.col("price").shift(1)).fill_null(True))
    market.trade_times = ticks["timestamp_us"].to_list()
    market.trade_prices = ticks["price"].to_list()
    return market


def fragmented(market, root, provenance):
    result = audit.fragmented(market, root)
    result.trade_times, result.trade_prices = market.trade_times, market.trade_prices
    if provenance:
        by_id = {r["id"]: r for r in market.events if r.get("id")}
        for row in result.events:
            if row.get("id", "").endswith(("/a", "/b")):
                parent = by_id[row["id"][:-2]]
                row.update(claim_id=parent["id"], claim_lo=parent["lo"], claim_hi=parent["hi"])
    return result


def canonical(observer):
    return [row for row in audit.canonical(observer) if row[1] == "typed_clear"]


def fixtures():
    yield from old.cases()
    yield from stress.CASES
    for start in ("11:55", "12:00"):
        yield s.Case("NQ", "2026-09-01", "short", start, "12:40", "later-directive-" + start.replace(":", ""))


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="Optional case-name substring for focused diagnosis.")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.case:
        OUT = OUT / ("focus-" + hashlib.sha256(args.case.encode()).hexdigest()[:12])
    stress.verify_frozen()
    cases = [c for c in fixtures() if not args.case or args.case in c.name]
    if len({c.name for c in cases}) != len(cases):
        raise ValueError("Fixture names must be unique; otherwise per-root artifacts overwrite each other.")
    markets, summaries, offers, episodes, rejected, checks, quality, contexts = {}, [], [], [], [], [], [], []
    for case in cases:
        key = (case.symbol, case.day)
        if key not in markets:
            markets[key] = load_market(case)
        market = markets[key]
        quality.append(stress.window_quality(case, market))
        for root in s.root_seeds(case, market):
            context = {"case": case.name, "root_n": root["root_n"], "root_time": s.clock(root["t"]),
                       "root_end": s.clock(root["end_t"]), "end_reason": root["end_reason"]}
            for warm in (True, False):
                for model in MODELS:
                    obs = observe(case, market, root, model, warm)
                    cfg = {**context, "warm": warm, "model": model}
                    folder = OUT / case.name / f"root-{root['root_n']}" / ("warm" if warm else "cold") / model
                    s.write_json(folder / "root.json", root)
                    for name, rows in (("offers", obs.offers), ("episodes", obs.completed), ("trace", obs.trace)):
                        s.write_lines(folder / f"{name}.jsonl", rows)
                    if hasattr(obs, "ignored"):
                        s.write_lines(folder / "ignored.jsonl", obs.ignored)
                    typed = [r for r in obs.offers if r["signature"] == "typed_clear"]
                    for maximum in (2, 3):
                        # Hold management constant; do not sneak in the unapproved
                        # tranche-trim/latest-group campaign risk experiments.
                        result = old.simulate(case, market, root, obs.offers, maximum, "typed_only", "root_only")
                        s.write_json(folder / f"inventory-{maximum}.json", result)
                        summaries.append({**cfg, "max_adds": maximum, "permissions": len(typed),
                            "permission_times": ";".join(r["time"] for r in typed),
                            **{k: v for k, v in result.items() if k not in ("actions", "inventory", "decisions")}})
                    offers.extend(old.csv_rows(typed, cfg))
                    episodes.extend(old.csv_rows(obs.completed, cfg))
                    rejected.extend(old.csv_rows(getattr(obs, "rejected", []), cfg))
                    if warm:
                        print(json.dumps({**cfg, "permissions": [r["time"] for r in typed],
                                          "adds": result["add_times"], "exits": result["risk_exits"]}), flush=True)
                    if args.validate and model.startswith("edge_local") and warm:
                        cutoff = root["t"] + (root["end_t"] - root["t"]) // 2
                        prefix_root = {**root, "end_t": cutoff, "end_reason": "prefix_cutoff"}
                        prefix = observe(case, market, prefix_root, model, warm)
                        split = observe(case, fragmented(market, root, True), root, model, warm)
                        naked = observe(case, fragmented(market, root, False), root, model, warm)
                        check = {**cfg,
                            "prefix_equal": [r for r in canonical(obs) if r[0] <= cutoff] == canonical(prefix),
                            "parent_fragmentation_equal": canonical(obs) == canonical(split),
                            "unlabelled_fragmentation_equal": canonical(obs) == canonical(naked)}
                        checks.append(check)
                        if not all(check[k] for k in ("prefix_equal", "parent_fragmentation_equal")):
                            s.write_json(folder / "validation_difference.json", {"full": canonical(obs),
                                "prefix": canonical(prefix), "parent_fragments": canonical(split)})
                contexts.append({**context, "warm": warm})
    for name, rows in (("summary", summaries), ("offers", offers), ("episodes", episodes), ("gate_rejected", rejected)):
        s.write_csv(OUT / f"{name}.csv", rows)
    s.write_json(OUT / "quality.json", quality)
    s.write_json(OUT / "validation.json", checks)
    s.write_json(OUT / "manifest.json", {
        "scope": [vars(c) for c in cases], "frozen_episode_sha256": stress.FROZEN_EPISODE_SHA256,
        "models": {"frozen": "Unmodified prior observer; same roots and risk proxy.",
                   "edge_gate": "Old grouping/closure, discard permissions without an in-episode far-edge breach or same-side typed failure. Diagnostic filter, not a new observer.",
                   "edge_local_mid": "Open on observed mid crossing past a known same-side far edge or typed same-side failure. Associate live claims intersecting the adverse excursion. A new far-edge attack after formal resolution starts a new episode even before the old extreme is exceeded. Close on departure beyond pre-attack extreme with no live opposition, even without support.",
                   "edge_local_trade": "Same local model; observe captured trades between complete LL samples against claims already known. Decide at sample boundaries with current BBO midpoint."},
        "held_constant": "Actual linked LL stream/settings, seeded roots/root cutoffs, typed opposing failure, retained current proof, two-unit tranches, 2/3 add budgets, delayed BBO fill proxy, root plus weighted BE management. No gamma/targets invented.",
        "limits": "Local association and departure expiry are additional hypotheses, not isolated effects of requiring a breach. Existing root-relative eligibility and broad delayed-fill new-opposition veto retained. No production one-behind group sponsorship, target harvest, fees, broker lifecycle, automatic reentry, or full P&L. Later-directive roots are independently seeded, not proof of a manual reissue sequence. Start at root fill, live warm evidence but no pre-fill breach authority.",
        "fragmentation": "Preserve source claim identity/edges for equivalent representation splitting. Unlabelled new boundaries are a separate sensitivity, not equivalent far-edge information.",
        "research_hashes": {name: sha(Path(__file__).with_name(name)) for name in
                            ("far_edge_study.py", "test_far_edge_study.py", "audit_far_edge.py", "episode_study.py", "study.py")},
        "production_hashes": {name: sha(s.REPO / "KahnRuntime" / name) for name in
                              ("CampaignContracts.cs", "CampaignPolicy.cs", "LevelLedgerEvidenceEngine.cs")},
        "input_hashes": {f"{symbol}-{day}/{name}": sha(m.directory / name)
                         for (symbol, day), m in markets.items() for name in ("events.jsonl", "quotes.parquet", "ticks.parquet")},
    })
    print(json.dumps({"output": str(OUT), "roots": len(contexts) // 2, "validation_checks": len(checks),
                      "causal_checks_pass": all(r["prefix_equal"] and r["parent_fragmentation_equal"] for r in checks)}))


if __name__ == "__main__":
    main()
