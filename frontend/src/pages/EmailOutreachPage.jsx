import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Mail, Send, RefreshCw, Check, Clock, FileText, Users, AlertCircle, Edit, ChevronDown, ExternalLink } from "lucide-react";
import { Button } from "../components/ui/button";
import { Link } from "react-router-dom";

const API = process.env.REACT_APP_BACKEND_URL;

function getAdminHeaders() {
  const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
  return token ? { "X-Admin-Token": token } : {};
}

function OutreachNav() {
  return (
    <div className="flex items-center gap-1 p-0.5 bg-secondary/50 rounded-md w-fit mb-5" data-testid="outreach-nav">
      <Link to="/admin/outreach"
        className="px-3 py-1.5 text-xs font-medium rounded transition-colors text-muted-foreground hover:text-foreground"
      >
        <Mail className="h-3.5 w-3.5 inline mr-1" />X Outreach
      </Link>
      <Link to="/admin/outreach/email"
        className="px-3 py-1.5 text-xs font-medium rounded transition-colors bg-background text-foreground shadow-sm"
      >
        <Send className="h-3.5 w-3.5 inline mr-1" />Email Outreach
      </Link>
    </div>
  );
}

function TemplateEditor({ template, onSave }) {
  const [subject, setSubject] = useState(template?.subject || "");
  const [bodyHtml, setBodyHtml] = useState(template?.body_html || "");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (template) {
      setSubject(template.subject || "");
      setBodyHtml(template.body_html || "");
    }
  }, [template]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await axios.post(`${API}/api/admin/email-outreach/templates`, {
        name: "default", subject, body_html: bodyHtml,
      }, { headers: getAdminHeaders() });
      toast.success("Template saved");
      onSave?.();
    } catch (e) {
      toast.error(`Save failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border rounded-lg p-4 mb-6 bg-secondary/20" data-testid="template-editor">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 text-sm font-medium w-full text-left">
        <FileText className="h-4 w-4" />
        Email Template
        <ChevronDown className={`h-4 w-4 ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Subject</label>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full h-9 px-3 text-sm border rounded-md bg-background"
              placeholder="Your paper ranked #{{rank}} in {{category}}..."
              data-testid="template-subject-input"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Body (HTML)</label>
            <textarea
              value={bodyHtml}
              onChange={(e) => setBodyHtml(e.target.value)}
              rows={10}
              className="w-full px-3 py-2 text-xs font-mono border rounded-md bg-background resize-y"
              placeholder="<p>Hi {{author_name}},</p>..."
              data-testid="template-body-input"
            />
          </div>
          <div className="text-[10px] text-muted-foreground">
            Variables: {"{{author_name}}"}, {"{{paper_title}}"}, {"{{category}}"}, {"{{rank}}"}, {"{{period}}"}, {"{{paper_id}}"}, {"{{total_papers}}"}, {"{{arxiv_id}}"}
          </div>
          <Button size="sm" onClick={handleSave} disabled={saving} data-testid="template-save-btn">
            {saving ? "Saving..." : "Save Template"}
          </Button>
        </div>
      )}
    </div>
  );
}

function PaperEmailCard({ paper, period, onRefresh }) {
  const [emails, setEmails] = useState(paper.emails || []);
  const [extracting, setExtracting] = useState(false);
  const [sending, setSending] = useState(false);
  const [manualEmail, setManualEmail] = useState("");
  const [showManual, setShowManual] = useState(false);

  useEffect(() => { setEmails(paper.emails || []); }, [paper.emails]);

  const handleExtract = async () => {
    setExtracting(true);
    try {
      const res = await axios.post(`${API}/api/admin/email-outreach/extract-emails`, {
        paper_id: paper.id,
      }, { headers: getAdminHeaders() });
      setEmails(res.data.emails || []);
      if (res.data.emails?.length) {
        toast.success(`Found ${res.data.emails.length} email(s)`);
      } else {
        toast.info("No emails found in paper text");
      }
      onRefresh?.();
    } catch (e) {
      toast.error(`Extraction failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setExtracting(false);
    }
  };

  const handleSend = async () => {
    if (!emails.length) return;
    if (!window.confirm(`Send congratulations email to ${emails.join(", ")}?`)) return;
    setSending(true);
    try {
      const res = await axios.post(`${API}/api/admin/email-outreach/send`, {
        paper_id: paper.id,
        to_emails: emails,
        period: period,
        category: paper.category || "",
        rank: paper.rank || 1,
      }, { headers: getAdminHeaders() });
      toast.success(`Sent to ${res.data.recipients?.length || 0} recipient(s)`);
      onRefresh?.();
    } catch (e) {
      toast.error(`Send failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setSending(false);
    }
  };

  const handleManualSave = async () => {
    const parsed = manualEmail.split(",").map(e => e.trim()).filter(e => e.includes("@"));
    if (!parsed.length) return;
    try {
      await axios.post(`${API}/api/admin/email-outreach/set-emails`, {
        paper_id: paper.id, emails: parsed,
      }, { headers: getAdminHeaders() });
      setEmails(parsed);
      setShowManual(false);
      setManualEmail("");
      toast.success("Emails saved");
      onRefresh?.();
    } catch (e) {
      toast.error(`Save failed: ${e.response?.data?.detail || e.message}`);
    }
  };

  const tier = { 1: "Gold", 2: "Silver", 3: "Bronze" }[paper.rank] || `#${paper.rank}`;
  const medal = { 1: "\u{1F947}", 2: "\u{1F948}", 3: "\u{1F949}" }[paper.rank] || "\u{1F3C5}";

  return (
    <div className={`border rounded-lg p-3 ${paper.already_sent ? "bg-green-50/50 border-green-200" : "bg-background"}`}
      data-testid={`paper-email-card-${paper.id}`}
    >
      <div className="flex items-start gap-2">
        <span className="text-lg" title={tier}>{medal}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">{tier}</span>
            {paper.already_sent && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700 border border-green-200 inline-flex items-center gap-1">
                <Check className="h-2.5 w-2.5" /> Sent {paper.sent_at?.slice(0, 10)}
              </span>
            )}
          </div>
          <h4 className="text-sm font-medium mt-0.5 line-clamp-2" title={paper.title}>{paper.title}</h4>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            {paper.authors?.slice(0, 3).join(", ")}{paper.authors?.length > 3 ? " et al." : ""}
          </p>

          {/* Emails section */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {emails.length > 0 ? (
              emails.map((email) => (
                <span key={email} className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                  {email}
                </span>
              ))
            ) : (
              <span className="text-[10px] text-muted-foreground italic">No emails extracted</span>
            )}
          </div>

          {/* Actions */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {!paper.already_sent && (
              <>
                <Button
                  size="sm" variant="outline"
                  onClick={handleExtract}
                  disabled={extracting}
                  className="h-7 text-xs"
                  data-testid={`extract-btn-${paper.id}`}
                >
                  {extracting ? <RefreshCw className="h-3 w-3 animate-spin mr-1" /> : <Users className="h-3 w-3 mr-1" />}
                  {extracting ? "Extracting..." : "Extract Emails"}
                </Button>
                <button
                  onClick={() => setShowManual(!showManual)}
                  className="text-[11px] text-muted-foreground hover:text-foreground underline"
                  data-testid={`manual-btn-${paper.id}`}
                >
                  <Edit className="h-3 w-3 inline mr-0.5" />Manual
                </button>
                {emails.length > 0 && (
                  <Button
                    size="sm"
                    onClick={handleSend}
                    disabled={sending}
                    className="h-7 text-xs ml-auto"
                    data-testid={`send-btn-${paper.id}`}
                  >
                    {sending ? <RefreshCw className="h-3 w-3 animate-spin mr-1" /> : <Send className="h-3 w-3 mr-1" />}
                    {sending ? "Sending..." : "Send Email"}
                  </Button>
                )}
              </>
            )}
            {paper.arxiv_id && (
              <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noopener noreferrer"
                className="text-[10px] text-muted-foreground hover:text-accent inline-flex items-center gap-0.5 ml-auto"
              >
                arXiv <ExternalLink className="h-2.5 w-2.5" />
              </a>
            )}
          </div>

          {/* Manual email input */}
          {showManual && (
            <div className="mt-2 flex items-center gap-2">
              <input
                value={manualEmail}
                onChange={(e) => setManualEmail(e.target.value)}
                placeholder="email1@univ.edu, email2@lab.org"
                className="flex-1 h-7 px-2 text-xs border rounded-md bg-background"
                data-testid={`manual-input-${paper.id}`}
              />
              <Button size="sm" className="h-7 text-xs" onClick={handleManualSave}
                data-testid={`manual-save-${paper.id}`}
              >Save</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function HistoryPanel() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/api/admin/email-outreach/history`, { headers: getAdminHeaders() });
      setHistory(res.data.sends || []);
    } catch { }
    finally { setLoading(false); }
  };

  useEffect(() => { if (open) load(); }, [open]);

  return (
    <div className="border rounded-lg p-4 bg-secondary/20" data-testid="email-history-panel">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 text-sm font-medium w-full text-left">
        <Clock className="h-4 w-4" />
        Send History ({history.length})
        <ChevronDown className={`h-4 w-4 ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-3 space-y-2 max-h-80 overflow-y-auto">
          {loading && <p className="text-xs text-muted-foreground">Loading...</p>}
          {!loading && history.length === 0 && <p className="text-xs text-muted-foreground italic">No emails sent yet</p>}
          {history.map((h, i) => (
            <div key={i} className="text-xs p-2 rounded border bg-background flex items-center gap-3">
              <Check className="h-3.5 w-3.5 text-green-600 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{h.paper_title || h.paper_id}</div>
                <div className="text-[10px] text-muted-foreground">{h.to_email} &middot; {h.period} &middot; {h.sent_at?.slice(0, 16).replace("T", " ")}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function EmailOutreachPage() {
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState("");
  const [medalists, setMedalists] = useState(null);
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState("");
  const [archivePeriods, setArchivePeriods] = useState({ weekly: [], monthly: [] });
  const [template, setTemplate] = useState(null);
  const [gmailStatus, setGmailStatus] = useState(null);

  const handleLogin = async () => {
    try {
      const res = await axios.post(`${API}/api/admin/login`, { password });
      if (res.data.token) {
        localStorage.setItem("admin_token", res.data.token);
        sessionStorage.setItem("admin_token", res.data.token);
        setAuthed(true);
      }
    } catch { toast.error("Invalid password"); }
  };

  useEffect(() => {
    const token = sessionStorage.getItem("admin_token") || localStorage.getItem("admin_token");
    if (token) setAuthed(true);
  }, []);

  // Load archive periods + template + gmail status
  useEffect(() => {
    if (!authed) return;
    axios.get(`${API}/api/admin/outreach/archive-periods`, { headers: getAdminHeaders() })
      .then(r => {
        setArchivePeriods(r.data);
        // Auto-select first available period
        if (r.data.monthly?.length) {
          setPeriod(`monthly:${r.data.monthly[0].value}`);
        } else if (r.data.weekly?.length) {
          setPeriod(`weekly:${r.data.weekly[0].value}`);
        }
      }).catch(() => {});
    axios.get(`${API}/api/admin/email-outreach/templates`, { headers: getAdminHeaders() })
      .then(r => setTemplate(r.data.templates?.[0] || r.data.default))
      .catch(() => {});
    axios.get(`${API}/api/admin/email-outreach/gmail-status`, { headers: getAdminHeaders() })
      .then(r => setGmailStatus(r.data))
      .catch(() => {});
  }, [authed]);

  const loadMedalists = useCallback(async () => {
    if (!authed || !period) return;
    setLoading(true);
    try {
      const res = await axios.get(`${API}/api/admin/email-outreach/medalists`, {
        headers: getAdminHeaders(), params: { period, top_n: 3 },
      });
      setMedalists(res.data);
    } catch (e) {
      toast.error("Failed to load medalists");
    } finally { setLoading(false); }
  }, [authed, period]);

  useEffect(() => { loadMedalists(); }, [loadMedalists]);

  const handleExtractAll = async () => {
    if (!medalists?.categories) return;
    const paperIds = medalists.categories.flatMap(c => c.papers.filter(p => !p.emails_extracted).map(p => p.id));
    if (!paperIds.length) { toast.info("All emails already extracted"); return; }
    try {
      const res = await axios.post(`${API}/api/admin/email-outreach/extract-emails-batch`, {
        paper_ids: paperIds,
      }, { headers: getAdminHeaders() });
      toast.success(`Extracting emails for ${res.data.extracting || 0} papers...`);
      // Refresh after a delay
      setTimeout(loadMedalists, 5000);
    } catch (e) {
      toast.error(`Batch extract failed: ${e.response?.data?.detail || e.message}`);
    }
  };

  if (!authed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-80 space-y-3">
          <h1 className="text-lg font-semibold text-center">Email Outreach — Admin</h1>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleLogin()}
            placeholder="Admin password" className="w-full h-9 px-3 text-sm border rounded-md"
            data-testid="email-outreach-password" />
          <Button onClick={handleLogin} className="w-full" data-testid="email-outreach-login-btn">Sign in</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-5xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-5">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight" data-testid="email-outreach-title">Email Outreach</h1>
            <p className="text-[11px] sm:text-sm text-muted-foreground mt-0.5">
              Send personalized congratulations to top-ranked paper authors via Gmail
            </p>
          </div>
          {gmailStatus && (
            <div className={`text-xs px-2.5 py-1 rounded border inline-flex items-center gap-1.5 ${
              gmailStatus.authorized
                ? "border-green-200 bg-green-50 text-green-700"
                : "border-red-200 bg-red-50 text-red-700"
            }`} data-testid="gmail-status-badge">
              <Mail className="h-3.5 w-3.5" />
              {gmailStatus.authorized ? "Gmail Connected" : "Gmail Not Connected"}
            </div>
          )}
        </div>

        <OutreachNav />

        {!gmailStatus?.authorized && (
          <div className="mb-5 p-4 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm" data-testid="gmail-warning">
            <AlertCircle className="h-4 w-4 inline mr-2" />
            Gmail is not connected. Authorize Gmail sending first on the <a href="/admin/dashboard" className="underline font-medium">admin dashboard</a> (Congrats section).
          </div>
        )}

        {/* Period selector */}
        <div className="flex flex-wrap items-center gap-3 mb-5" data-testid="period-selector">
          <label className="text-xs font-medium">Period:</label>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="h-8 px-2 text-xs border rounded-md bg-background min-w-[180px]"
            data-testid="email-period-select"
          >
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
          <Button size="sm" variant="outline" onClick={loadMedalists} disabled={loading} className="h-8 text-xs"
            data-testid="email-refresh-btn"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button size="sm" variant="outline" onClick={handleExtractAll} className="h-8 text-xs"
            data-testid="extract-all-btn"
          >
            <Users className="h-3.5 w-3.5 mr-1" />
            Extract All Emails
          </Button>
        </div>

        {/* Stats bar */}
        {medalists && (
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground mb-5" data-testid="email-stats">
            <span>{medalists.total_papers} papers</span>
            <span className="text-blue-600">{medalists.total_with_emails} with emails</span>
            <span className="text-green-600">{medalists.total_sent} already sent</span>
          </div>
        )}

        {/* Template */}
        <TemplateEditor template={template} onSave={() => {
          axios.get(`${API}/api/admin/email-outreach/templates`, { headers: getAdminHeaders() })
            .then(r => setTemplate(r.data.templates?.[0] || r.data.default)).catch(() => {});
        }} />

        {/* Medalists by category */}
        {loading && <p className="text-sm text-muted-foreground">Loading medalists...</p>}
        {medalists?.categories?.map((cat) => (
          <div key={cat.category} className="mb-6" data-testid={`category-section-${cat.category}`}>
            <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
              {cat.name}
              <span className="text-[10px] font-normal text-muted-foreground">{cat.label}</span>
            </h3>
            <div className="space-y-2">
              {cat.papers.map((paper) => (
                <PaperEmailCard
                  key={paper.id}
                  paper={{ ...paper, category: cat.category }}
                  period={period}
                  onRefresh={loadMedalists}
                />
              ))}
            </div>
          </div>
        ))}

        {medalists && !medalists.categories?.length && !loading && (
          <div className="text-center py-12 text-muted-foreground text-sm">
            No medalists found for this period. Try a different archive period.
          </div>
        )}

        {/* History */}
        <div className="mt-8">
          <HistoryPanel />
        </div>
      </div>
    </div>
  );
}
