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
from datetime import datetime, timezone

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
        {"_id": 1, "category": 1, "created_at": 1, "label": 1, "leaderboard": 1},
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

    archives.sort(key=lambda a: parse_ts(a.get("created_at", "")))

    # Replay matches chronologically, snapshotting TS/OS at each archive's cutoff
    # Per-category state: {category: {paper_id: (ts_mu, ts_sigma, os_mu, os_sigma)}}
    cat_ts = defaultdict(dict)  # {cat: {pid: trueskill.Rating}}
    cat_os = defaultdict(dict)  # {cat: {pid: {mk: (mu, sigma)}}} — per-model
    cat_global_os = defaultdict(dict)  # {cat: {pid: (mu, sigma)}} — global

    match_idx = 0
    total_archives_updated = 0

    for archive in archives:
        cutoff = parse_ts(archive.get("created_at", ""))
        cat = archive["category"]

        # Replay matches up to this archive's cutoff
        while match_idx < len(all_matches):
            m = all_matches[match_idx]
            m_ts = parse_ts(m.get("created_at", ""))
            if m_ts > cutoff:
                break

            m_cat = m["primary_category"]
            p1, p2, winner = m["paper1_id"], m["paper2_id"], m["winner_id"]

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
            os_scores[pid] = round(conservative * TS_SCALE + SCORE_BASE)
            os_sigmas[pid] = round(g_sigma, 4)

        # Compute ranks
        ts_ranked = sorted(ts_scores.items(), key=lambda x: -x[1])
        os_ranked = sorted(os_scores.items(), key=lambda x: -x[1])
        rank_ts = {pid: i + 1 for i, (pid, _) in enumerate(ts_ranked)}
        rank_os = {pid: i + 1 for i, (pid, _) in enumerate(os_ranked)}

        # Update archive entries
        updated = False
        for entry in lb:
            pid = entry.get("id")
            if not pid:
                continue
            if pid in ts_scores:
                ts_r = cat_ts[cat].get(pid)
                entry["ts_score"] = ts_scores[pid]
                entry["ts_sigma"] = round(ts_r.sigma, 4) if ts_r else None
                entry["rank_ts"] = rank_ts.get(pid)
                updated = True
            if pid in os_scores:
                entry["os_score"] = os_scores[pid]
                entry["os_sigma"] = os_sigmas.get(pid)
                entry["rank_os"] = rank_os.get(pid)
                updated = True

        if updated:
            await db.leaderboard_archives.update_one(
                {"_id": archive["_id"]},
                {"$set": {"leaderboard": lb}},
            )
            total_archives_updated += 1

    elapsed = time.perf_counter() - t0
    print(f"Done: {total_archives_updated} archives updated with historical TS/OS scores in {elapsed:.1f}s")
    print(f"Replayed {match_idx} matches")


if __name__ == "__main__":
    asyncio.run(main())
