"""
Export 4 CSV files for the benchmark controlled pairs:
1. legacy (cross-tier only) without PeerRead ACL
2. legacy with PeerRead ACL
3. extended (incl. within-tier) without PeerRead ACL
4. extended with PeerRead ACL
"""
import asyncio, csv, sys
sys.path.insert(0, "/app/backend")

from collections import defaultdict, Counter

ICLR_DATASETS = [
    "iclr-codegen", "iclr-fairness", "iclr-llm", "iclr-molecules",
    "iclr-optimization", "iclr-ot", "iclr-pdes", "iclr-protein",
]
PEERREAD = "peerread_acl_2017"


async def get_controlled_cf_pairs(db, dataset_id, include_within_tier=False):
    from routers.human_ai_benchmark import build_expert_ratings, collect_all, norm_tier
    import routers.human_ai_benchmark as hab
    hab.db = db

    papers = await collect_all(db.validation_papers.find(
        {"dataset_id": dataset_id},
        {"_id": 0, "id": 1, "title": 1, "decision": 1, "evaluations": 1,
         "ai_impact_summary_thinking": 1}
    ))
    if not papers:
        return []

    papers_by_id = {p["id"]: p for p in papers}
    expert_ratings = build_expert_ratings(papers)
    experts_with_data = {e: r for e, r in expert_ratings.items() if len(r) >= 3}
    if len(experts_with_data) < 2:
        return []

    # Expert pairwise preferences (non-tie)
    expert_pair_prefs = defaultdict(dict)
    for exp, ratings in experts_with_data.items():
        rated_ids = list(ratings.keys())
        for i in range(len(rated_ids)):
            for j in range(i + 1, len(rated_ids)):
                a, b = rated_ids[i], rated_ids[j]
                if ratings[a] == ratings[b]:
                    continue
                pair = tuple(sorted([a, b]))
                expert_pair_prefs[pair][exp] = a if ratings[a] > ratings[b] else b

    # All rated pairs (including ties)
    expert_pair_rated = defaultdict(set)
    for exp, ratings in experts_with_data.items():
        rated_ids = list(ratings.keys())
        for i in range(len(rated_ids)):
            for j in range(i + 1, len(rated_ids)):
                pair = tuple(sorted([rated_ids[i], rated_ids[j]]))
                expert_pair_rated[pair].add(exp)

    # AI content mode
    has_thinking = any(p.get("ai_impact_summary_thinking") for p in papers)
    ai_content_mode = "abstract_plus_summary:thinking" if has_thinking else "abstract_plus_summary"
    mode_count = await db.validation_matches.count_documents(
        {"dataset_id": dataset_id, "completed": True, "content_mode": ai_content_mode})
    if mode_count == 0:
        ai_content_mode = "abstract_plus_summary"

    # Load AI matches
    if include_within_tier:
        import random as _rng
        TIER_MAP = {"oral": 4, "spotlight": 3, "poster": 2, "reject": 1, "withdrawn": 0, "desk rejected": 0}
        def _is_within(m):
            t1 = norm_tier(papers_by_id.get(m["paper1_id"], {}).get("decision"))
            t2 = norm_tier(papers_by_id.get(m["paper2_id"], {}).get("decision"))
            return t1 is not None and t2 is not None and TIER_MAP.get(t1, -1) == TIER_MAP.get(t2, -2)

        base_raw = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))
        exp_raw = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": True}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))
        all_combined = base_raw + exp_raw
        cross_adj = sorted([m for m in all_combined if not _is_within(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))
        within = sorted([m for m in all_combined if _is_within(m)], key=lambda m: (m['paper1_id'], m['paper2_id']))

        all_pids = list(papers_by_id.keys())
        nat_cross_adj, nat_within = 0, 0
        for i in range(len(all_pids)):
            for j in range(i+1, len(all_pids)):
                t1 = norm_tier(papers_by_id[all_pids[i]].get("decision"))
                t2 = norm_tier(papers_by_id[all_pids[j]].get("decision"))
                if t1 and t2:
                    if TIER_MAP.get(t1) == TIER_MAP.get(t2):
                        nat_within += 1
                    else:
                        nat_cross_adj += 1
        nat_total = nat_cross_adj + nat_within
        nat_within_frac = nat_within / nat_total if nat_total > 0 else 0.3
        target_within = int(len(cross_adj) * nat_within_frac / max(0.01, 1 - nat_within_frac))
        target_within = min(target_within, len(within))
        if target_within < len(within):
            _rng.seed(42 + hash(dataset_id))
            within = _rng.sample(within, target_within)
        ai_raw = cross_adj + within
    else:
        ai_raw = await collect_all(db.validation_matches.find(
            {"dataset_id": dataset_id, "completed": True, "failed": {"$ne": True},
             "content_mode": ai_content_mode, "experiment_tag": {"$exists": False}},
            {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1},
        ))

    # AI majority vote per pair
    ai_pair_votes = defaultdict(list)
    for m in ai_raw:
        if m.get("winner_id"):
            pair = tuple(sorted([m["paper1_id"], m["paper2_id"]]))
            ai_pair_votes[pair].append(m["winner_id"])
    ai_pair = {}
    for pair, votes in ai_pair_votes.items():
        c = Counter(votes)
        ai_pair[pair] = c.most_common(1)[0][0]

    # Controlled CF pairs
    controlled_cf = set(expert_pair_rated.keys()) & set(ai_pair.keys())

    rows = []
    for pair in sorted(controlled_cf):
        p1, p2 = pair
        human_votes = expert_pair_prefs.get(pair, {})
        if human_votes:
            c = Counter(human_votes.values())
            human_winner = c.most_common(1)[0][0] if c.most_common(1)[0][1] > len(human_votes) / 2 else "tie"
        else:
            human_winner = "tie"

        rows.append({
            "dataset_id": dataset_id,
            "paper1_id": p1, "paper2_id": p2,
            "paper1_title": papers_by_id.get(p1, {}).get("title", ""),
            "paper2_title": papers_by_id.get(p2, {}).get("title", ""),
            "paper1_decision": papers_by_id.get(p1, {}).get("decision", ""),
            "paper2_decision": papers_by_id.get(p2, {}).get("decision", ""),
            "ai_winner_id": ai_pair[pair],
            "human_majority_winner_id": human_winner,
            "n_ai_judges": len(ai_pair_votes.get(pair, [])),
            "n_human_experts": len(expert_pair_rated.get(pair, set())),
            "human_has_preference": pair in expert_pair_prefs,
        })
    return rows


def write_csv(rows, path):
    fields = ["dataset_id", "paper1_id", "paper2_id", "paper1_title", "paper2_title",
              "paper1_decision", "paper2_decision", "ai_winner_id", "human_majority_winner_id",
              "n_ai_judges", "n_human_experts", "human_has_preference"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path}: {len(rows)} pairs")


async def main():
    import motor.motor_asyncio
    client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["test_database"]

    # Collect all pairs
    legacy_iclr, legacy_acl = [], []
    extended_iclr, extended_acl = [], []

    for did in ICLR_DATASETS:
        print(f"Processing {did}...")
        legacy_iclr.extend(await get_controlled_cf_pairs(db, did, include_within_tier=False))
        extended_iclr.extend(await get_controlled_cf_pairs(db, did, include_within_tier=True))

    print(f"Processing {PEERREAD}...")
    legacy_acl = await get_controlled_cf_pairs(db, PEERREAD, include_within_tier=False)
    extended_acl = legacy_acl  # PeerRead has no tiers, so extended = legacy

    # Write 4 files
    print("\nWriting CSVs:")
    write_csv(legacy_iclr, "/app/backend/data/matches_legacy.csv")
    write_csv(legacy_iclr + legacy_acl, "/app/backend/data/matches_legacy_with_acl.csv")
    write_csv(extended_iclr, "/app/backend/data/matches_extended.csv")
    write_csv(extended_iclr + extended_acl, "/app/backend/data/matches_extended_with_acl.csv")

asyncio.run(main())
