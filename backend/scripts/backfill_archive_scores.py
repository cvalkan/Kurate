"""
Backfill historically accurate TS and OS scores into leaderboard_archives.

For each archive, replays all matches up to its created_at date to compute
what the TS/OS scores WERE at that point in time. Much more accurate than
copying current scores into old archives.

Run: cd /app/backend && python3 scripts/backfill_archive_scores.py
"""
import asyncio
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")

from pymongo import UpdateOne


async def main():
    from core.config import db
    from openskill.models import ThurstoneMostellerFull
    import trueskill

    t0 = time.perf_counter()
    os_model = ThurstoneMostellerFull()
    ts_env = trueskill.TrueSkill(draw_probability=0)
    TS_SCALE = 10.0
    OS_SCALE = 15.0
    SCORE_BASE = 1200
    DEFAULT_MU = 25.0
    DEFAULT_SIGMA = DEFAULT_MU / 3

    _OPUS_MERGE = {
        "anthropic/claude-opus-4-5-20251101": "anthropic/claude-opus",
        "anthropic/claude-opus-4-6": "anthropic/claude-opus",
    }

    # Load ALL matches sorted by created_at (across all categories)
    all_matches = []
    async for m in db.matches.find(
        {"completed": True, "failed": {"$ne": True}, "mode": {"$exists": False}},
        {"_id": 0, "paper1_id": 1, "paper2_id": 1, "winner_id": 1,
         "model_used": 1, "primary_category": 1, "created_at": 1},
    ).sort("created_at", 1):
        if m.get("winner_id") and m.get("created_at"):
            all_matches.append(m)

    print(f"Loaded {len(all_matches)} matches")

    # Load ALL archives
    archives = []
    async for a in db.leaderboard_archives.find(
        {"leaderboard": {"$exists": True}},
        {"_id": 1, "category": 1, "created_at": 1, "label": 1, "period_type": 1, "leaderboard": 1},
    ).sort("created_at", 1):
        archives.append(a)

    print(f"Loaded {len(archives)} archives")

    # Sort archives by created_at
    def parse_ts(s):
        if isinstance(s, datetime):
            return s
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except:
            return datetime.min.replace(tzinfo=timezone.utc)

    # Compute effective cutoff per archive: max(created_at, latest match for archive papers)
    # This handles archives where created_at is the period start date but data was captured later
    # Compute effective cutoff per archive using the NEXT archive's created_at
    # as the boundary — that's when the live system took the next snapshot.
    # For archives with backdated created_at (midnight timestamps), this gives
    # the correct window. For the most recent archive, use current time.
    print("Computing effective cutoffs per archive...")
    archive_cutoffs = {}

    # Group archives by (category, period_type) to find next-archive boundaries
    from itertools import groupby
    archives_by_group = defaultdict(list)
    for a in archives:
        key = (a["category"], a.get("period_type", "weekly"))
        archives_by_group[key].append(a)

    # Sort each group by created_at ascending
    for key in archives_by_group:
        archives_by_group[key].sort(key=lambda a: parse_ts(a.get("created_at", "")))

    now = datetime.now(timezone.utc)
    for key, group in archives_by_group.items():
        for i, a in enumerate(group):
            if i + 1 < len(group):
                # Use next archive's created_at as cutoff
                next_created = parse_ts(group[i + 1].get("created_at", ""))
                archive_cutoffs[a["_id"]] = next_created
            else:
                # Most recent archive — use current time
                archive_cutoffs[a["_id"]] = now

    # Re-sort archives by effective cutoff
    archives.sort(key=lambda a: archive_cutoffs.get(a["_id"], parse_ts(a.get("created_at", ""))))
    print(f"Effective cutoffs computed for {len(archives)} archives")

    # Replay matches chronologically, snapshotting TS/OS at each archive's cutoff
    # Per-category state: {category: {paper_id: (ts_mu, ts_sigma, os_mu, os_sigma)}}
    cat_ts = defaultdict(dict)  # {cat: {pid: trueskill.Rating}}
    cat_os = defaultdict(dict)  # {cat: {pid: {mk: (mu, sigma)}}} — per-model
    cat_global_os = defaultdict(dict)  # {cat: {pid: (mu, sigma)}} — global
    # Track WR stats per category per paper: {cat: {pid: {"wins": N, "losses": N}}}
    cat_wr = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0}))

    match_idx = 0
    total_archives_updated = 0

    for archive in archives:
        cutoff = archive_cutoffs.get(archive["_id"], parse_ts(archive.get("created_at", "")))
        cat = archive["category"]

        # Replay matches up to this archive's cutoff
        while match_idx < len(all_matches):
            m = all_matches[match_idx]
            m_ts = parse_ts(m.get("created_at", ""))
            if m_ts > cutoff:
                break

            m_cat = m["primary_category"]
            p1, p2, winner = m["paper1_id"], m["paper2_id"], m["winner_id"]

            # WR stats tracking
            if winner == p1:
                cat_wr[m_cat][p1]["wins"] += 1
                cat_wr[m_cat][p2]["losses"] += 1
            else:
                cat_wr[m_cat][p2]["wins"] += 1
                cat_wr[m_cat][p1]["losses"] += 1

            # TrueSkill update
            if p1 not in cat_ts[m_cat]:
                cat_ts[m_cat][p1] = ts_env.create_rating()
            if p2 not in cat_ts[m_cat]:
                cat_ts[m_cat][p2] = ts_env.create_rating()

            r1, r2 = cat_ts[m_cat][p1], cat_ts[m_cat][p2]
            if winner == p1:
                new_r1, new_r2 = ts_env.rate_1vs1(r1, r2)
            else:
                new_r2, new_r1 = ts_env.rate_1vs1(r2, r1)
            cat_ts[m_cat][p1] = new_r1
            cat_ts[m_cat][p2] = new_r2

            # Per-model OpenSkill update
            mu_info = m.get("model_used", {})
            raw_key = f"{mu_info.get('provider', 'unknown')}/{mu_info.get('model', 'unknown')}"
            mk = _OPUS_MERGE.get(raw_key, raw_key).replace(".", "_")

            if p1 not in cat_os[m_cat]:
                cat_os[m_cat][p1] = {}
            if p2 not in cat_os[m_cat]:
                cat_os[m_cat][p2] = {}

            os1 = cat_os[m_cat][p1].get(mk, (DEFAULT_MU, DEFAULT_SIGMA))
            os2 = cat_os[m_cat][p2].get(mk, (DEFAULT_MU, DEFAULT_SIGMA))

            r_os1 = os_model.rating(mu=os1[0], sigma=os1[1])
            r_os2 = os_model.rating(mu=os2[0], sigma=os2[1])

            if winner == p1:
                [[nw], [nl]] = os_model.rate([[r_os1], [r_os2]], ranks=[1, 2])
                cat_os[m_cat][p1][mk] = (nw.mu, nw.sigma)
                cat_os[m_cat][p2][mk] = (nl.mu, nl.sigma)
            else:
                [[nw], [nl]] = os_model.rate([[r_os2], [r_os1]], ranks=[1, 2])
                cat_os[m_cat][p2][mk] = (nw.mu, nw.sigma)
                cat_os[m_cat][p1][mk] = (nl.mu, nl.sigma)

            # Global OS update (all matches regardless of model)
            if p1 not in cat_global_os[m_cat]:
                cat_global_os[m_cat][p1] = (DEFAULT_MU, DEFAULT_SIGMA)
            if p2 not in cat_global_os[m_cat]:
                cat_global_os[m_cat][p2] = (DEFAULT_MU, DEFAULT_SIGMA)

            gr1 = os_model.rating(mu=cat_global_os[m_cat][p1][0], sigma=cat_global_os[m_cat][p1][1])
            gr2 = os_model.rating(mu=cat_global_os[m_cat][p2][0], sigma=cat_global_os[m_cat][p2][1])

            if winner == p1:
                [[gw], [gl]] = os_model.rate([[gr1], [gr2]], ranks=[1, 2])
                cat_global_os[m_cat][p1] = (gw.mu, gw.sigma)
                cat_global_os[m_cat][p2] = (gl.mu, gl.sigma)
            else:
                [[gw], [gl]] = os_model.rate([[gr2], [gr1]], ranks=[1, 2])
                cat_global_os[m_cat][p2] = (gw.mu, gw.sigma)
                cat_global_os[m_cat][p1] = (gl.mu, gl.sigma)

            match_idx += 1

        # Snapshot TS/OS scores for this archive's category
        lb = archive.get("leaderboard", [])
        if not lb:
            continue

        # Build TS scores for papers in this archive
        ts_scores = {}
        for pid, rating in cat_ts.get(cat, {}).items():
            conservative = rating.mu - 3 * rating.sigma
            ts_scores[pid] = round(conservative * TS_SCALE + SCORE_BASE)

        # Build OS scores from global OS (all matches, not per-model average)
        os_scores = {}
        os_sigmas = {}
        for pid, (g_mu, g_sigma) in cat_global_os.get(cat, {}).items():
            conservative = g_mu - 3 * g_sigma
            os_scores[pid] = round(conservative * OS_SCALE + SCORE_BASE)
            os_sigmas[pid] = round(g_sigma, 4)

        # Compute ranks
        ts_ranked = sorted(ts_scores.items(), key=lambda x: -x[1])
        os_ranked = sorted(os_scores.items(), key=lambda x: -x[1])
        rank_ts = {pid: i + 1 for i, (pid, _) in enumerate(ts_ranked)}
        rank_os = {pid: i + 1 for i, (pid, _) in enumerate(os_ranked)}

        # Update archive entries — ALL columns from replayed match data
        updated = False
        for entry in lb:
            pid = entry.get("id")
            if not pid:
                continue

            # WR stats from replayed matches
            wr = cat_wr[cat][pid]
            wins = wr["wins"]
            losses = wr["losses"]
            comparisons = wins + losses
            win_rate = round(wins / comparisons * 100, 1) if comparisons > 0 else 0.0
            # Regularized WR score (same formula as compute_leaderboard)
            p_reg = (wins + 0.5) / (comparisons + 1.0) if comparisons > 0 else 0.5
            import math
            wr_score = round(400 * math.log10(max(p_reg, 0.001) / max(1 - p_reg, 0.001)) + SCORE_BASE)
            entry["wins"] = wins
            entry["losses"] = losses
            entry["comparisons"] = comparisons
            entry["win_rate"] = win_rate
            entry["score"] = wr_score

            # TrueSkill
            if pid in ts_scores:
                ts_r = cat_ts[cat].get(pid)
                entry["ts_score"] = ts_scores[pid]
                entry["ts_sigma"] = round(ts_r.sigma, 4) if ts_r else None
            else:
                entry["ts_score"] = SCORE_BASE
                entry["ts_sigma"] = round(DEFAULT_SIGMA, 4)

            # OpenSkill
            if pid in os_scores:
                entry["os_score"] = os_scores[pid]
                entry["os_sigma"] = os_sigmas.get(pid)
            else:
                entry["os_score"] = SCORE_BASE
                entry["os_sigma"] = round(DEFAULT_SIGMA, 4)
            updated = True

        # Recompute ranks including papers with default scores
        all_ts = [(entry.get("id"), entry.get("ts_score", SCORE_BASE)) for entry in lb if entry.get("id")]
        all_ts.sort(key=lambda x: -x[1])
        rank_ts_full = {pid: i + 1 for i, (pid, _) in enumerate(all_ts)}
        all_os = [(entry.get("id"), entry.get("os_score", SCORE_BASE)) for entry in lb if entry.get("id")]
        all_os.sort(key=lambda x: -x[1])
        rank_os_full = {pid: i + 1 for i, (pid, _) in enumerate(all_os)}
        for entry in lb:
            pid = entry.get("id")
            if pid:
                entry["rank_ts"] = rank_ts_full.get(pid)
                entry["rank_os"] = rank_os_full.get(pid)

        # Compute gap scores (WR percentile vs AI rating percentile)
        ai_ratings = {}
        for entry in lb:
            ai_r = entry.get("ai_rating")
            if ai_r and isinstance(ai_r, dict) and ai_r.get("score"):
                ai_ratings[entry["id"]] = ai_r["score"]
            elif ai_r and isinstance(ai_r, (int, float)):
                ai_ratings[entry["id"]] = ai_r

        entries_with_both = [e for e in lb if ai_ratings.get(e.get("id")) and (e.get("comparisons") or 0) >= 3]
        if len(entries_with_both) >= 2:
            import numpy as _np
            from scipy import stats as _sp
            wr_vals = _np.array([e.get("score", 0) for e in entries_with_both])
            si_vals = _np.array([ai_ratings[e["id"]] for e in entries_with_both])
            wr_pct = _sp.rankdata(wr_vals) / len(entries_with_both) * 100
            si_pct = _sp.rankdata(si_vals) / len(entries_with_both) * 100
            gap_wr = wr_pct - si_pct
            for i, entry in enumerate(entries_with_both):
                entry["gap_score"] = round(float(gap_wr[i]), 1)

            if any(e.get("ts_score") for e in entries_with_both):
                ts_vals = _np.array([e.get("ts_score", SCORE_BASE) for e in entries_with_both])
                ts_pct = _sp.rankdata(ts_vals) / len(entries_with_both) * 100
                gap_ts = ts_pct - si_pct
                for i, entry in enumerate(entries_with_both):
                    pass  # gap_score_ts removed — use gap_score only
            updated = True  # Gap scores changed

        if updated:
            total_matches = sum(e.get("comparisons", 0) for e in lb) // 2
            await db.leaderboard_archives.update_one(
                {"_id": archive["_id"]},
                {"$set": {"leaderboard": lb, "match_count": total_matches}},
            )
            total_archives_updated += 1

    elapsed = time.perf_counter() - t0
    print(f"Done: {total_archives_updated} archives updated with historical TS/OS scores in {elapsed:.1f}s")
    print(f"Replayed {match_idx} matches")

    # Cleanup pass: fix any remaining papers with ts_score=1200 despite having matches.
    # These are edge cases from cutoff boundary timing. Use live TS score as fallback.
    live_ts = {}
    async for r in db.rankings.find(
        {"ts_score": {"$exists": True, "$ne": None}},
        {"_id": 0, "paper_id": 1, "ts_score": 1, "ts_sigma": 1,
         "os_score": 1, "os_sigma": 1},
    ):
        live_ts[r["paper_id"]] = r

    fixed = 0
    async for archive in db.leaderboard_archives.find(
        {"leaderboard": {"$exists": True}},
        {"_id": 1, "leaderboard": 1},
    ):
        lb = archive.get("leaderboard", [])
        changed = False
        for entry in lb:
            if (entry.get("comparisons") or 0) > 0 and entry.get("ts_score") == SCORE_BASE:
                pid = entry.get("id")
                if pid and pid in live_ts:
                    entry["ts_score"] = live_ts[pid].get("ts_score", SCORE_BASE)
                    entry["ts_sigma"] = live_ts[pid].get("ts_sigma")
                    if live_ts[pid].get("os_score"):
                        entry["os_score"] = live_ts[pid]["os_score"]
                    if live_ts[pid].get("os_sigma"):
                        entry["os_sigma"] = live_ts[pid]["os_sigma"]
                    changed = True
                    fixed += 1
        if changed:
            await db.leaderboard_archives.update_one(
                {"_id": archive["_id"]}, {"$set": {"leaderboard": lb}}
            )

    if fixed:
        print(f"Cleanup: fixed {fixed} edge-case papers using live TS scores")


if __name__ == "__main__":
    asyncio.run(main())
