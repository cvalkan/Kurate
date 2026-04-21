# Emergent Universal Key — Budget & Proxy Issues Report

**App:** kurate.org (AI paper ranking platform)  
**User Job ID:** 7c9f7afa-9d20-4f8e-993e-e51bd59ad35f  
**Date:** April 20-21, 2026  

---

## Issue 1: Budget Exceeded Despite Available Balance

**Symptom:** All LLM calls through the Emergent proxy fail with:
```
Budget has been exceeded! Current cost: 13791.321838350119, Max budget: 13800
```

**User's dashboard shows:**
- Universal Key balance: 1,055 credits (sufficient)
- Project Budget: "No limit" configured
- Auto-recharge: enabled

**Root cause:** There appears to be an internal budget cap (~$13,800) enforced by the Emergent proxy/litellm layer that is NOT visible in the user's dashboard. The user's Project Budget setting ("No limit") and Universal Key balance (1,055 credits) are separate from this internal cap.

**Resolution:** User set a large explicit Project Budget number, which raised the cap slightly (from 13,800 to ~14,154). But this is a workaround — the internal cap should respect the "No limit" setting or be visible in the dashboard.

**Impact:** The app's tournament pipeline (running 24/7 making ~8,000 LLM calls/hour across GPT-5.2, Claude Opus 4.6, and Gemini 3 Pro) was completely blocked for ~12 hours until the budget issue was resolved.

---

## Issue 2: Claude Opus 4.6 Access Revoked Without Notice

**Symptom:** Claude Opus 4.6 calls through the Emergent proxy suddenly started failing with:
```
AuthenticationError: invalid x-api-key ... This key can only access models=['gpt-4', 'gpt-4o', ...]
```

**Timeline:**
- Claude Opus 4.6 was working through the Emergent key for weeks
- Around April 18, 2026: Claude Opus 4.6 calls started returning authentication errors
- Claude Opus 4.7 was released April 16, 2026 — the key's allowed model list was not updated to include it
- Claude Sonnet 4.5 still worked through the same key
- GPT and Gemini models continued working normally

**Impact:** The app generates ~7,000 Claude thinking summaries per week. All summary generation was blocked. The user had to implement a direct Anthropic API key fallback as a workaround.

**Questions for Emergent team:**
1. Was Claude Opus 4.6 intentionally removed from the allowed models list?
2. When new Claude models are released (e.g., 4.7), are they automatically added to Universal Keys?
3. Is there a way for users to see which models their key can access?

---

## Issue 3: Intermittent 502 Bad Gateway on Claude

**Symptom:** Before the authentication error, Claude calls intermittently failed with:
```
BadGatewayError: Error code: 502
```
Each failed call took ~230 seconds to timeout before returning the error.

**Impact:** With 20 parallel workers, each 502 blocked a worker for ~4 minutes. This reduced throughput from ~8,000/hr to ~2,200/hr.

**Workaround implemented:** 
- Circuit breaker: after 2 consecutive proxy failures for a provider, skip the proxy entirely and use the direct API key
- Periodic probe: every 5 minutes, try the proxy once to detect recovery
- Budget errors: fail fast (no retry) instead of 4 × 15s retries

---

## Summary of Workarounds Implemented

Because of these issues, the app now has a full fallback system:

1. **Direct Anthropic key** (`ANTHROPIC_API_KEY`) — fallback when Emergent proxy fails for Claude
2. **Direct OpenAI key** (`OPENAI_API_KEY_DIRECT`) — fallback when Emergent proxy fails for GPT
3. **Circuit breaker** — skips proxy after 2 failures, probes every 5 min
4. **Budget fail-fast** — no retries on budget errors
5. **LLM error logging** — all proxy errors persisted to MongoDB for debugging (`GET /api/admin/llm-errors`)

Ideally these workarounds shouldn't be necessary if the Emergent proxy reliably handles budget management and model access.

---

## Request

1. **Make the internal budget cap visible** in the dashboard, or remove it when "No limit" is set
2. **Update model access lists** promptly when new Claude/GPT versions are released
3. **Reduce 502 timeout** from 230s to something reasonable (30s) on the proxy side
4. **Provide a `/models` endpoint** on the proxy that lists available models for a given key
