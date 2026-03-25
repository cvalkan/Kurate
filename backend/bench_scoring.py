import time, os
from dotenv import load_dotenv
load_dotenv()
from pymongo import MongoClient
from scipy import stats as scipy_stats
import numpy as np

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "papersumo")
client = MongoClient(MONGO_URL)
db = client[DB_NAME]

# 1. Load matches
t0 = time.perf_counter()
query = {"completed": True, "winner_id": {"$exists": True}, "failed": {"$ne": True}}
proj = {"paper1_id": 1, "paper2_id": 1, "winner_id": 1, "_id": 0}
matches = list(db.matches.find(query, proj))
t_load = time.perf_counter() - t0
print(f"Loaded {len(matches):,} matches in {t_load:.3f}s")

paper_ids = list(set(
    [m["paper1_id"] for m in matches] + [m["paper2_id"] for m in matches]
))
print(f"Unique papers: {len(paper_ids):,}")

# 2. Win-rate
t0 = time.perf_counter()
from services.ranking import compute_leaderboard
papers = [{"id": pid, "title": ""} for pid in paper_ids]
bt_matches = [{"paper1_id": m["paper1_id"], "paper2_id": m["paper2_id"],
               "winner_id": m["winner_id"], "completed": True, "failed": False}
              for m in matches]
lb = compute_leaderboard(papers, bt_matches)
wr_scores = {e["id"]: e["score"] for e in lb}
t_wr = time.perf_counter() - t0
print(f"Win-rate:      {t_wr:.3f}s")

# 3. Bradley-Terry
t0 = time.perf_counter()
from services.ranking import compute_bt_ranking_scores
bt_scores = compute_bt_ranking_scores(bt_matches, paper_ids)
t_bt = time.perf_counter() - t0
print(f"Bradley-Terry: {t_bt:.3f}s")

# 4. TrueSkill
t0 = time.perf_counter()
from services.ranking import compute_trueskill_ranking_scores
ts_scores = compute_trueskill_ranking_scores(bt_matches, paper_ids)
t_ts = time.perf_counter() - t0
print(f"TrueSkill:     {t_ts:.3f}s")

# 5. Spearman correlations
t0 = time.perf_counter()
shared = sorted(set(wr_scores.keys()) & set(bt_scores.keys()) & set(ts_scores.keys()))
wr_arr = [wr_scores[p] for p in shared]
bt_arr = [bt_scores[p] for p in shared]
ts_arr = [ts_scores[p] for p in shared]

rho_wr_bt, _ = scipy_stats.spearmanr(wr_arr, bt_arr)
rho_wr_ts, _ = scipy_stats.spearmanr(wr_arr, ts_arr)
rho_bt_ts, _ = scipy_stats.spearmanr(bt_arr, ts_arr)
t_corr = time.perf_counter() - t0

print(f"Correlations:  {t_corr:.3f}s")
print()
print(f"=== Spearman rank correlations (n={len(shared):,} papers) ===")
print(f"  WinRate vs BT:        {rho_wr_bt:.6f}")
print(f"  WinRate vs TrueSkill: {rho_wr_ts:.6f}")
print(f"  BT vs TrueSkill:      {rho_bt_ts:.6f}")
print()
print(f"=== Wall time breakdown ===")
print(f"  Load matches: {t_load:.3f}s")
print(f"  Win-rate:     {t_wr:.3f}s")
print(f"  Bradley-Terry:{t_bt:.3f}s")
print(f"  TrueSkill:    {t_ts:.3f}s")
print(f"  Correlations: {t_corr:.3f}s")
total = t_load + t_wr + t_bt + t_ts + t_corr
print(f"  TOTAL:        {total:.3f}s")
