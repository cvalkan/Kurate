#!/usr/bin/env python3
"""
Exhaustive dead code audit for Kurate.org backend.
Focus areas 1-4:
  1. Write-only MongoDB collections
  2. Unused functions in hot-path files
  3. Legacy BT/scoring code still running
  4. Unused routers/endpoints

Outputs results to /app/memory/DEAD_CODE_AUDIT.md
"""

import os
import re
import ast
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path("/app/backend")
FRONTEND_SRC = Path("/app/frontend/src")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def read_file(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except:
        return ""

def all_py_files():
    for f in BACKEND.rglob("*.py"):
        if "__pycache__" not in str(f):
            yield f

def all_jsx_files():
    for f in FRONTEND_SRC.rglob("*.jsx"):
        yield f
    for f in FRONTEND_SRC.rglob("*.js"):
        yield f

def relative(path):
    try:
        return str(path.relative_to(Path("/app")))
    except:
        return str(path)


# ═══════════════════════════════════════════════════════════════════════════════
# AREA 1: Write-only MongoDB collections
# ═══════════════════════════════════════════════════════════════════════════════

def audit_mongodb_collections():
    """Find collections that are written to but never read by any endpoint."""
    results = []
    
    # Regex patterns for MongoDB operations
    write_ops = re.compile(r'db\.(\w+)\.(insert_one|insert_many|update_one|update_many|bulk_write|replace_one|delete_one|delete_many|drop|create_index|drop_index|drop_indexes)')
    read_ops = re.compile(r'db\.(\w+)\.(find_one|find\b|aggregate|count_documents|distinct|estimated_document_count)')
    
    writes = defaultdict(list)  # collection -> [(file, line_num, operation)]
    reads = defaultdict(list)   # collection -> [(file, line_num, operation)]
    
    for f in all_py_files():
        content = read_file(f)
        rel = relative(f)
        for i, line in enumerate(content.split("\n"), 1):
            for m in write_ops.finditer(line):
                coll = m.group(1)
                op = m.group(2)
                writes[coll].append((rel, i, op))
            for m in read_ops.finditer(line):
                coll = m.group(1)
                op = m.group(2)
                reads[coll].append((rel, i, op))
    
    # Find write-only collections
    for coll in sorted(writes.keys()):
        read_locations = reads.get(coll, [])
        write_locations = writes[coll]
        
        # Filter out self-referential reads (e.g., find_one to get last round number before insert)
        # and count_documents used only in startup seeding checks
        endpoint_reads = [r for r in read_locations 
                         if "routers/" in r[0]  # Read by an actual endpoint
                         or ("server.py" not in r[0] and "scheduler.py" not in r[0])]
        
        if not endpoint_reads and len(write_locations) > 0:
            # Also check: does anything in routers/ reference this collection name?
            coll_referenced_in_routers = False
            for f in (BACKEND / "routers").glob("*.py"):
                if coll in read_file(f):
                    coll_referenced_in_routers = True
                    break
            
            results.append({
                "collection": coll,
                "write_count": len(write_locations),
                "read_count": len(read_locations),
                "endpoint_reads": len(endpoint_reads),
                "referenced_in_routers": coll_referenced_in_routers,
                "writes": write_locations[:5],
                "reads": read_locations[:5],
                "verdict": "WRITE-ONLY (no endpoint reads)" if not coll_referenced_in_routers else "POSSIBLY DEAD (no direct endpoint reads but referenced)",
            })
    
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# AREA 2: Unused functions in hot-path files
# ═══════════════════════════════════════════════════════════════════════════════

def audit_unused_functions():
    """Find functions defined but never called in hot-path backend files."""
    hot_files = [
        BACKEND / "services" / "scheduler.py",
        BACKEND / "services" / "ranking.py",
        BACKEND / "services" / "llm.py",
        BACKEND / "routers" / "leaderboard.py",
        BACKEND / "server.py",
        BACKEND / "services" / "precompute.py",
    ]
    
    results = []
    
    # Step 1: Collect all function/method definitions in hot files
    all_functions = {}  # func_name -> (file, line)
    for f in hot_files:
        content = read_file(f)
        rel = relative(f)
        for i, line in enumerate(content.split("\n"), 1):
            m = re.match(r'^(?:async )?def (\w+)\s*\(', line)
            if m:
                fname = m.group(1)
                if not fname.startswith("__"):  # Skip dunder methods
                    all_functions[fname] = (rel, i)
    
    # Step 2: Search for usages across ALL backend files
    all_backend_content = ""
    file_contents = {}
    for f in all_py_files():
        content = read_file(f)
        all_backend_content += content + "\n"
        file_contents[relative(f)] = content
    
    # Also check frontend for API endpoint references
    all_frontend_content = ""
    for f in all_jsx_files():
        all_frontend_content += read_file(f) + "\n"
    
    for fname, (defined_in, line_num) in sorted(all_functions.items()):
        # Count occurrences (excluding the definition line itself)
        # A function is "used" if its name appears in a context other than its definition
        pattern = re.compile(r'\b' + re.escape(fname) + r'\b')
        
        occurrences = []
        for fpath, content in file_contents.items():
            for i, line in enumerate(content.split("\n"), 1):
                if pattern.search(line):
                    # Skip the definition itself
                    if fpath == defined_in and i == line_num:
                        continue
                    # Skip comments
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    occurrences.append((fpath, i, stripped[:100]))
        
        if not occurrences:
            results.append({
                "function": fname,
                "defined_in": defined_in,
                "line": line_num,
                "call_count": 0,
                "callers": [],
            })
    
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# AREA 3: Legacy BT/scoring code still executing
# ═══════════════════════════════════════════════════════════════════════════════

def audit_legacy_bt():
    """Find BT/full-match-loading code that still executes in production paths."""
    results = []
    
    # Functions that load all matches or compute BT
    bt_functions = [
        "compute_leaderboard",
        "compute_leaderboard_async",
        "compute_bt_ranking_scores",
        "compute_trueskill_ranking_scores",
        "calculate_bradley_terry",
        "compute_weighted_bt",
        "calculate_bt_confidence_intervals",
    ]
    
    # Find all call sites
    for f in all_py_files():
        content = read_file(f)
        rel = relative(f)
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for func in bt_functions:
                if func + "(" in stripped or func + " " in stripped:
                    # Check if this is a definition vs a call
                    if re.match(r'^(?:async )?def ' + func, stripped):
                        continue
                    # Check if it's an import
                    if "import" in stripped and func in stripped:
                        # Still record imports — they indicate the function is used
                        results.append({
                            "function": func,
                            "file": rel,
                            "line": i,
                            "code": stripped[:120],
                            "type": "import",
                        })
                        continue
                    results.append({
                        "function": func,
                        "file": rel,
                        "line": i,
                        "code": stripped[:120],
                        "type": "call",
                    })
    
    # Also find patterns that load ALL matches into memory
    match_load_pattern = re.compile(r'(collect_all|to_list)\s*\(.*matches', re.IGNORECASE)
    for f in all_py_files():
        content = read_file(f)
        rel = relative(f)
        for i, line in enumerate(content.split("\n"), 1):
            if match_load_pattern.search(line) and not line.strip().startswith("#"):
                results.append({
                    "function": "MATCH_BULK_LOAD",
                    "file": rel,
                    "line": i,
                    "code": line.strip()[:120],
                    "type": "bulk_load",
                })
    
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# AREA 4: Unused endpoints
# ═══════════════════════════════════════════════════════════════════════════════

def audit_unused_endpoints():
    """Find API endpoints never called by the frontend."""
    results = []
    
    # Step 1: Extract all endpoint paths from routers
    endpoints = []
    route_pattern = re.compile(r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']')
    
    for f in (BACKEND / "routers").glob("*.py"):
        content = read_file(f)
        rel = relative(f)
        # Find the router prefix
        prefix_match = re.search(r'router\s*=\s*APIRouter\s*\(\s*prefix\s*=\s*["\']([^"\']+)["\']', content)
        prefix = prefix_match.group(1) if prefix_match else ""
        
        for m in route_pattern.finditer(content):
            method = m.group(1).upper()
            path = m.group(2)
            full_path = prefix + path
            # Find the function name on the next line
            pos = m.end()
            func_match = re.search(r'(?:async )?def (\w+)', content[pos:pos+200])
            func_name = func_match.group(1) if func_match else "?"
            line_num = content[:m.start()].count("\n") + 1
            endpoints.append({
                "method": method,
                "path": full_path,
                "function": func_name,
                "file": rel,
                "line": line_num,
            })
    
    # Step 2: Search frontend for references to each endpoint path
    frontend_content = ""
    for f in all_jsx_files():
        frontend_content += read_file(f) + "\n"
    
    # Also check backend (internal calls between endpoints)
    backend_content = ""
    for f in all_py_files():
        backend_content += read_file(f) + "\n"
    
    for ep in endpoints:
        path = ep["path"]
        # Normalize: strip /api prefix for frontend search (frontend uses ${API}/api/...)
        search_path = path.replace("/api/", "")
        
        # Search in frontend
        fe_found = False
        # Check various patterns: "/api/path", `${API}/api/path`, "api/path"
        for pattern in [path, search_path, path.lstrip("/")]:
            if pattern in frontend_content:
                fe_found = True
                break
        
        # Search in backend (for internal calls)
        be_found = False
        for pattern in [path, f'"{path}"', f"'{path}'"]:
            # Count occurrences minus the definition
            count = backend_content.count(pattern)
            if count > 1:  # More than just the route definition
                be_found = True
                break
        
        if not fe_found and not be_found:
            ep["frontend_referenced"] = False
            ep["backend_referenced"] = False
            results.append(ep)
        elif not fe_found:
            ep["frontend_referenced"] = False
            ep["backend_referenced"] = True
            # Still flag — only used internally
            results.append(ep)
    
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report():
    output = []
    output.append("# Dead Code Audit — Kurate.org Backend")
    output.append(f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
    output.append(f"Codebase: ~37K lines across {sum(1 for _ in all_py_files())} Python files")
    output.append("")
    
    # ─── Area 1 ───────────────────────────────────────────────────────────────
    output.append("## 1. Write-Only MongoDB Collections")
    output.append("")
    output.append("Collections written to but never read by any API endpoint.")
    output.append("")
    
    colls = audit_mongodb_collections()
    if colls:
        for c in colls:
            output.append(f"### `{c['collection']}` — {c['verdict']}")
            output.append(f"- Writes: {c['write_count']} locations")
            output.append(f"- Reads: {c['read_count']} total ({c['endpoint_reads']} from endpoints)")
            output.append(f"- Referenced in routers: {'Yes' if c['referenced_in_routers'] else 'No'}")
            output.append(f"- Write locations:")
            for loc in c['writes']:
                output.append(f"  - `{loc[0]}:{loc[1]}` — {loc[2]}")
            if c['reads']:
                output.append(f"- Read locations:")
                for loc in c['reads']:
                    output.append(f"  - `{loc[0]}:{loc[1]}` — {loc[2]}")
            output.append("")
    else:
        output.append("No write-only collections found.")
        output.append("")
    
    # ─── Area 2 ───────────────────────────────────────────────────────────────
    output.append("## 2. Unused Functions in Hot-Path Files")
    output.append("")
    output.append("Functions defined in scheduler.py, ranking.py, llm.py, leaderboard.py,")
    output.append("server.py, precompute.py that have zero call sites across the entire backend.")
    output.append("")
    
    unused = audit_unused_functions()
    if unused:
        # Group by file
        by_file = defaultdict(list)
        for u in unused:
            by_file[u["defined_in"]].append(u)
        
        for fpath in sorted(by_file.keys()):
            funcs = by_file[fpath]
            output.append(f"### `{fpath}` ({len(funcs)} unused)")
            for u in funcs:
                output.append(f"- **`{u['function']}`** (line {u['line']})")
            output.append("")
    else:
        output.append("No unused functions found.")
        output.append("")
    
    # ─── Area 3 ───────────────────────────────────────────────────────────────
    output.append("## 3. Legacy BT/Match-Loading Code Still Executing")
    output.append("")
    output.append("Call sites for Bradley-Terry computation and bulk match loading.")
    output.append("Since the architecture moved to incremental TrueSkill + WR with")
    output.append("pre-stored scores in the `rankings` collection, full match loads")
    output.append("should only be needed for admin reconciliation and convergence charts.")
    output.append("")
    
    bt = audit_legacy_bt()
    if bt:
        # Group by type
        calls = [b for b in bt if b["type"] == "call"]
        imports = [b for b in bt if b["type"] == "import"]
        bulk = [b for b in bt if b["type"] == "bulk_load"]
        
        if calls:
            output.append("### BT/Leaderboard Function Calls")
            output.append("")
            output.append("| Function | File | Line | Code |")
            output.append("|---|---|---|---|")
            for b in calls:
                code = b['code'].replace("|", "\\|")
                output.append(f"| `{b['function']}` | `{b['file']}` | {b['line']} | `{code[:80]}` |")
            output.append("")
        
        if bulk:
            output.append("### Bulk Match Loads (collect_all/to_list on matches)")
            output.append("")
            output.append("Each of these loads ALL match documents for a category into memory.")
            output.append("")
            output.append("| File | Line | Code |")
            output.append("|---|---|---|")
            for b in bulk:
                code = b['code'].replace("|", "\\|")
                output.append(f"| `{b['file']}` | {b['line']} | `{code[:100]}` |")
            output.append("")
        
        if imports:
            output.append("### BT Function Imports")
            output.append("")
            for b in imports:
                output.append(f"- `{b['file']}:{b['line']}` — `{b['code'][:100]}`")
            output.append("")
    
    # ─── Area 4 ───────────────────────────────────────────────────────────────
    output.append("## 4. Potentially Unused API Endpoints")
    output.append("")
    output.append("Endpoints with no frontend reference. Some may be admin-only or")
    output.append("called programmatically (e.g., from scheduler). Marked accordingly.")
    output.append("")
    
    eps = audit_unused_endpoints()
    if eps:
        # Separate into fully unused vs backend-only
        fully_unused = [e for e in eps if not e.get("backend_referenced")]
        backend_only = [e for e in eps if e.get("backend_referenced")]
        
        if fully_unused:
            output.append("### No Frontend or Backend References")
            output.append("")
            output.append("| Method | Path | Function | File | Line |")
            output.append("|---|---|---|---|---|")
            for e in fully_unused:
                output.append(f"| {e['method']} | `{e['path']}` | `{e['function']}` | `{e['file']}` | {e['line']} |")
            output.append("")
        
        if backend_only:
            output.append("### Backend-Only (no frontend reference)")
            output.append("")
            output.append("These are called internally (admin, scheduler, etc.) but not by the frontend.")
            output.append("")
            output.append("| Method | Path | Function | File | Line |")
            output.append("|---|---|---|---|---|")
            for e in backend_only:
                output.append(f"| {e['method']} | `{e['path']}` | `{e['function']}` | `{e['file']}` | {e['line']} |")
            output.append("")
    else:
        output.append("All endpoints appear to be referenced.")
        output.append("")
    
    return "\n".join(output)


if __name__ == "__main__":
    print("Running dead code audit...", file=sys.stderr)
    report = generate_report()
    
    out_path = Path("/app/memory/DEAD_CODE_AUDIT.md")
    out_path.write_text(report, encoding="utf-8")
    print(f"Report written to {out_path}", file=sys.stderr)
    print(f"Report length: {len(report)} chars, {report.count(chr(10))} lines", file=sys.stderr)
