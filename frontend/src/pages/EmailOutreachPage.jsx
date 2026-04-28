import { useState, useEffect, useCallback, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import {
  ArrowLeft, Mail, Send, RefreshCw, Check, Clock, Users, AlertCircle,
  Edit, ExternalLink, Search, ChevronDown, FileText,
} from "lucide-react";
import { Button } from "../components/ui/button";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

function fmtDate(s) {
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s.slice(0, 10);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

const GRID = "grid gap-1 sm:gap-2 px-2 sm:px-3 md:px-4";

function TemplateEditor({ template, onSave }) {
  const [subject, setSubject] = useState(template?.subject || "");
  const [bodyHtml, setBodyHtml] = useState(template?.body_html || "");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (template) { setSubject(template.subject || ""); setBodyHtml(template.body_html || ""); }
  }, [template]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await axios.post(`${API}/api/admin/email-outreach/templates`,
        { name: "default", subject, body_html: bodyHtml },
        { headers: getAdminHeaders() });
      toast.success("Template saved");
      onSave?.();
    } catch (e) { toast.error(`Save failed: ${e.response?.data?.detail || e.message}`); }
    finally { setSaving(false); }
  };

  return (
    <div className="border rounded-lg px-3 py-2 mb-5 bg-secondary/20" data-testid="template-editor">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 text-xs font-medium w-full text-left">
        <FileText className="h-3.5 w-3.5" /> Email Template
        <ChevronDown className={`h-3.5 w-3.5 ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-3 space-y-2">
          <div>
            <label className="text-[10px] text-muted-foreground block mb-0.5">Subject</label>
            <input value={subject} onChange={(e) => setSubject(e.target.value)}
              className="w-full h-8 px-2 text-xs border rounded-md bg-background" data-testid="template-subject-input" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground block mb-0.5">Body (HTML)</label>
            <textarea value={bodyHtml} onChange={(e) => setBodyHtml(e.target.value)} rows={8}
              className="w-full px-2 py-1.5 text-xs font-mono border rounded-md bg-background resize-y" data-testid="template-body-input" />
          </div>
          <div className="text-[10px] text-muted-foreground">
            {"{{author_name}} {{paper_title}} {{category}} {{rank}} {{period}} {{paper_id}} {{total_papers}} {{arxiv_id}} {{leaderboard_url}} {{badge_html}}"}
          </div>
          <Button size="sm" onClick={handleSave} disabled={saving} className="h-7 text-xs" data-testid="template-save-btn">
            {saving ? "Saving…" : "Save Template"}
          </Button>
        </div>
      )}
    </div>
  );
}

function ManualEmailInput({ paperId, onSaved }) {
  const [val, setVal] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    const parsed = val.split(",").map(e => e.trim()).filter(e => e.includes("@"));
    if (!parsed.length) return;
    setSaving(true);
    try {
      await axios.post(`${API}/api/admin/email-outreach/set-emails`,
        { paper_id: paperId, emails: parsed }, { headers: getAdminHeaders() });
      toast.success("Emails saved");
      setVal("");
      onSaved?.();
    } catch (e) { toast.error(`Save failed: ${e.response?.data?.detail || e.message}`); }
    finally { setSaving(false); }
  };

  return (
    <div className="flex items-center gap-1.5 mt-1.5">
      <input value={val} onChange={(e) => setVal(e.target.value)}
        placeholder="email@univ.edu, email2@lab.org"
        className="flex-1 h-6 px-2 text-[11px] border rounded bg-background"
        data-testid={`manual-input-${paperId}`}
        onKeyDown={(e) => e.key === "Enter" && handleSave()} />
      <button onClick={handleSave} disabled={saving}
        className="h-6 px-2 text-[10px] rounded border border-accent text-accent hover:bg-accent hover:text-background transition-colors disabled:opacity-50"
        data-testid={`manual-save-${paperId}`}
      >{saving ? "…" : "Save"}</button>
    </div>
  );
}

export default function EmailOutreachPage() {
  const navigate = useNavigate();
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState("");
  const [archivePeriods, setArchivePeriods] = useState({ weekly: [], monthly: [] });
  const [template, setTemplate] = useState(null);
  const [gmailStatus, setGmailStatus] = useState(null);
  const [query, setQuery] = useState("");
  const [extracting, setExtracting] = useState(new Set());
  const [sending, setSending] = useState(new Set());
  const [stats, setStats] = useState({});

  useEffect(() => {
    const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
    if (!token) navigate("/admin", { replace: true });
  }, [navigate]);

  useEffect(() => {
    const h = getAdminHeaders();
    axios.get(`${API}/api/admin/outreach/archive-periods`, { headers: h })
      .then(r => {
        setArchivePeriods(r.data);
        if (r.data.monthly?.length) setPeriod(`monthly:${r.data.monthly[0].value}`);
        else if (r.data.weekly?.length) setPeriod(`weekly:${r.data.weekly[0].value}`);
      }).catch(() => {});
    axios.get(`${API}/api/admin/email-outreach/templates`, { headers: h })
      .then(r => setTemplate(r.data.templates?.[0] || r.data.default)).catch(() => {});
    axios.get(`${API}/api/admin/email-outreach/gmail-status`, { headers: h })
      .then(r => setGmailStatus(r.data)).catch(() => {});
  }, []);

  const loadMedalists = useCallback(async () => {
    if (!period) return;
    setLoading(true);
    try {
      const res = await axios.get(`${API}/api/admin/email-outreach/medalists`, {
        headers: getAdminHeaders(), params: { period, top_n: 3 },
      });
      setPapers(res.data.papers || []);
      setStats({
        total: res.data.total_papers,
        withEmails: res.data.total_with_emails,
        sent: res.data.total_sent,
        noEmails: res.data.total_no_emails,
      });
    } catch { toast.error("Failed to load medalists"); }
    finally { setLoading(false); }
  }, [period]);

  useEffect(() => { loadMedalists(); }, [loadMedalists]);

  // Auto-extract emails for papers that haven't been extracted yet
  useEffect(() => {
    if (!papers.length) return;
    const unextracted = papers.filter(p => !p.emails_extracted).map(p => p.id);
    if (!unextracted.length) return;

    setExtracting(new Set(unextracted));
    axios.post(`${API}/api/admin/email-outreach/extract-emails-batch`,
      { paper_ids: unextracted }, { headers: getAdminHeaders() })
      .then(() => {
        let attempts = 0;
        const poll = setInterval(async () => {
          attempts++;
          try {
            const res = await axios.get(`${API}/api/admin/email-outreach/medalists`, {
              headers: getAdminHeaders(), params: { period, top_n: 3 },
            });
            const updated = res.data.papers || [];
            const stillPending = updated.filter(p => unextracted.includes(p.id) && !p.emails_extracted);
            setPapers(updated);
            setStats({
              total: res.data.total_papers,
              withEmails: res.data.total_with_emails,
              sent: res.data.total_sent,
              noEmails: res.data.total_no_emails,
            });
            if (stillPending.length === 0 || attempts > 30) {
              clearInterval(poll);
              setExtracting(new Set());
              if (stillPending.length === 0) toast.success("Email extraction complete");
            } else {
              setExtracting(new Set(stillPending.map(p => p.id)));
            }
          } catch { clearInterval(poll); setExtracting(new Set()); }
        }, 3000);
      })
      .catch(() => setExtracting(new Set()));
  }, [papers.length > 0 && papers[0]?.id, period]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleExtract = async (paperId) => {
    setExtracting(prev => new Set([...prev, paperId]));
    try {
      const res = await axios.post(`${API}/api/admin/email-outreach/extract-emails`,
        { paper_id: paperId }, { headers: getAdminHeaders() });
      setPapers(prev => prev.map(p => p.id === paperId
        ? { ...p, emails: res.data.emails || [], emails_extracted: true }
        : p));
      if (res.data.emails?.length) toast.success(`Found ${res.data.emails.length} email(s)`);
      else toast.info("No emails found");
    } catch (e) { toast.error(`Extraction failed: ${e.response?.data?.detail || e.message}`); }
    finally { setExtracting(prev => { const n = new Set(prev); n.delete(paperId); return n; }); }
  };

  const handleSend = async (paper) => {
    if (!paper.emails?.length) return;
    if (!window.confirm(`Send congratulations to ${paper.emails.join(", ")}?`)) return;
    setSending(prev => new Set([...prev, paper.id]));
    try {
      await axios.post(`${API}/api/admin/email-outreach/send`, {
        paper_id: paper.id, to_emails: paper.emails,
        period, category: paper.category || "", rank: paper.rank || 1,
      }, { headers: getAdminHeaders() });
      toast.success(`Sent to ${paper.emails.length} recipient(s)`);
      loadMedalists();
    } catch (e) { toast.error(`Send failed: ${e.response?.data?.detail || e.message}`); }
    finally { setSending(prev => { const n = new Set(prev); n.delete(paper.id); return n; }); }
  };

  const handleTestSend = async (paper) => {
    if (!window.confirm(`Send TEST email (with badge) to roblauko@gmail.com for "${paper.title?.slice(0, 50)}..."?`)) return;
    setSending(prev => new Set([...prev, paper.id]));
    try {
      await axios.post(`${API}/api/admin/email-outreach/test-send`, {
        paper_id: paper.id, period, category: paper.category || "", rank: paper.rank || 1,
      }, { headers: getAdminHeaders() });
      toast.success("Test email sent to roblauko@gmail.com");
    } catch (e) { toast.error(`Test send failed: ${e.response?.data?.detail || e.message}`); }
    finally { setSending(prev => { const n = new Set(prev); n.delete(paper.id); return n; }); }
  };

  const filtered = useMemo(() => {
    if (!query.trim()) return papers;
    const q = query.toLowerCase();
    return papers.filter(p =>
      (p.title || "").toLowerCase().includes(q) ||
      (p.category_name || "").toLowerCase().includes(q) ||
      (p.emails || []).some(e => e.toLowerCase().includes(q)) ||
      (p.authors || []).some(a => a.toLowerCase().includes(q))
    );
  }, [papers, query]);

  const cols = ["2rem", "1fr", "12rem", "8rem", "4.5rem", "5.5rem"];
  const gridStyle = { gridTemplateColumns: cols.join(" ") };

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5 sm:py-6">
        <div className="flex items-center justify-between mb-4">
          <Link to="/admin/dashboard" data-testid="email-outreach-back"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft className="h-3.5 w-3.5" /> Back to Admin
          </Link>
          <Button onClick={loadMedalists} disabled={loading} size="sm" variant="outline"
            className="gap-1.5 text-xs h-8" data-testid="email-outreach-refresh">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>

        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight" data-testid="email-outreach-title">
          Email Outreach
        </h1>
        <p className="text-sm text-muted-foreground mt-1 mb-5">
          Send personalized congratulations to top-ranked paper authors via Gmail.
        </p>

        {!gmailStatus?.authorized && (
          <div className="mb-4 px-3 py-2 rounded-md border border-amber-200 bg-amber-50 text-amber-800 text-xs inline-flex items-center gap-2"
            data-testid="gmail-warning">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            Gmail not connected.
            <button onClick={async () => {
              try {
                const r = await axios.get(`${API}/api/admin/email-outreach/gmail/auth-url`, { headers: getAdminHeaders() });
                if (r.data?.url) window.open(r.data.url, "_blank");
              } catch (e) { toast.error(`Gmail auth failed: ${e.response?.data?.detail || e.message}`); }
            }} className="underline font-medium hover:text-amber-900" data-testid="connect-gmail-btn">
              Connect Gmail
            </button>
            to send emails.
          </div>
        )}

        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <select value={period} onChange={(e) => setPeriod(e.target.value)}
            className="h-8 px-2 text-xs border rounded-md bg-background min-w-[180px]"
            data-testid="email-period-select">
            <optgroup label="Monthly">
              {archivePeriods.monthly?.map(p => (
                <option key={p.value} value={`monthly:${p.value}`}>{p.label} ({p.categories} cats)</option>
              ))}
            </optgroup>
            <optgroup label="Weekly">
              {archivePeriods.weekly?.map(p => (
                <option key={p.value} value={`weekly:${p.value}`}>{p.label} ({p.categories} cats)</option>
              ))}
            </optgroup>
          </select>

          <div className="relative w-56">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Search paper, author, email…" data-testid="email-outreach-search"
              className="w-full h-8 pl-8 pr-3 text-xs border rounded-md bg-background focus:outline-none focus:ring-1 focus:ring-accent" />
          </div>
        </div>

        <div className="mb-4">
          <TemplateEditor template={template} onSave={() => {
            axios.get(`${API}/api/admin/email-outreach/templates`, { headers: getAdminHeaders() })
              .then(r => setTemplate(r.data.templates?.[0] || r.data.default)).catch(() => {});
          }} />
        </div>

        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-4" data-testid="email-outreach-stats">
          <span>{stats.total || 0} papers</span>
          <span className="text-blue-600">{stats.withEmails || 0} with emails</span>
          <span className="text-amber-600">{stats.noEmails || 0} no email</span>
          <span className="text-green-600">{stats.sent || 0} sent</span>
          {extracting.size > 0 && (
            <span className="text-gray-500 animate-pulse">extracting {extracting.size}…</span>
          )}
        </div>

        {loading && !papers.length ? (
          <div className="space-y-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-10 bg-secondary/30 rounded animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground text-sm border border-border rounded-lg"
            data-testid="email-outreach-empty">
            {query ? "No matches for your search." : "No medalists found for this period."}
          </div>
        ) : (
          <div className="border border-border rounded-lg overflow-x-auto" data-testid="email-outreach-table">
            <div className={`${GRID} py-2 bg-secondary/40 text-[11px] font-medium text-muted-foreground border-b border-border select-none`}
              style={gridStyle}>
              <div>#</div>
              <div>Paper</div>
              <div>Emails</div>
              <div>Category</div>
              <div className="text-right">Status</div>
              <div className="text-right"></div>
            </div>

            {filtered.map((p, i) => {
              const isExtracting = extracting.has(p.id);
              const isSending = sending.has(p.id);
              const medal = { 1: "\u{1F947}", 2: "\u{1F948}", 3: "\u{1F949}" }[p.rank] || "";
              const hasEmails = p.emails?.length > 0;

              return (
                <div key={p.id} data-testid={`email-row-${p.id}`}>
                  <div
                    className={`${GRID} py-2.5 items-center border-b border-border/40 last:border-0 hover:bg-secondary/20 transition-colors ${
                      p.already_sent ? "bg-green-50/30" : ""
                    }`}
                    style={gridStyle}
                  >
                    <div className="text-[11px] text-muted-foreground/70 font-mono">{i + 1}</div>

                    <div className="min-w-0">
                      <p className="text-[13px] font-medium truncate leading-snug" title={p.title}>
                        {medal && <span className="mr-0.5">{medal}</span>}{p.title}
                      </p>
                      <p className="text-[11px] text-muted-foreground truncate mt-0.5">
                        {(p.authors || []).slice(0, 2).join(", ")}
                        {(p.authors || []).length > 2 && ` +${p.authors.length - 2}`}
                        {p.arxiv_id && (
                          <a href={`https://arxiv.org/abs/${p.arxiv_id}`} target="_blank" rel="noopener noreferrer"
                            className="ml-1.5 text-accent/70 hover:text-accent hover:underline">{p.arxiv_id}</a>
                        )}
                      </p>
                    </div>

                    <div className="min-w-0">
                      {isExtracting ? (
                        <span className="text-[11px] text-muted-foreground/60 italic flex items-center gap-1">
                          <RefreshCw className="h-2.5 w-2.5 animate-spin" /> extracting…
                        </span>
                      ) : hasEmails ? (
                        <div className="space-y-0">
                          {p.emails.slice(0, 2).map(e => (
                            <a key={e} href={`mailto:${e}`} className="block text-[11px] text-blue-600 hover:underline truncate leading-relaxed" title={e}>{e}</a>
                          ))}
                          {p.emails.length > 2 && (
                            <p className="text-[10px] text-muted-foreground/60">+{p.emails.length - 2} more</p>
                          )}
                        </div>
                      ) : p.emails_extracted ? (
                        <span className="text-[11px] text-muted-foreground/50 italic">no email found</span>
                      ) : (
                        <button onClick={() => handleExtract(p.id)}
                          className="text-[11px] text-accent/70 hover:text-accent hover:underline" data-testid={`extract-btn-${p.id}`}>
                          extract
                        </button>
                      )}
                    </div>

                    <div className="text-[11px] text-muted-foreground/70 truncate" title={`${p.category_name} · #${p.rank}`}>
                      {p.category_name || p.category} <span className="opacity-60">#{p.rank}</span>
                    </div>

                    <div className="text-right">
                      {p.already_sent ? (
                        <span className="text-[10px] text-green-600">sent {fmtDate(p.sent_at)}</span>
                      ) : hasEmails ? (
                        <span className="text-[10px] text-blue-500">ready</span>
                      ) : (
                        <span className="text-[10px] text-muted-foreground/40">—</span>
                      )}
                    </div>

                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => handleTestSend(p)} disabled={isSending}
                        className="h-5 px-1.5 rounded text-[9px] font-medium text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50"
                        title="Test send to roblauko@gmail.com" data-testid={`test-btn-${p.id}`}>
                        {isSending ? "…" : "Test"}
                      </button>
                      {!p.already_sent && hasEmails && gmailStatus?.authorized ? (
                        <button onClick={() => handleSend(p)} disabled={isSending}
                          className="h-5 w-5 rounded text-accent hover:bg-accent hover:text-background flex items-center justify-center transition-colors disabled:opacity-50"
                          title="Send email" data-testid={`send-btn-${p.id}`}>
                          {isSending ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                        </button>
                      ) : p.already_sent ? (
                        <Check className="h-3.5 w-3.5 text-green-500" />
                      ) : (
                        <Send className="h-3 w-3 text-muted-foreground/20" />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
