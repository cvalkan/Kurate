import { ResponsiveContainer, LineChart, Line, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip as RTooltip } from "recharts";

const MOCK = {
  all_visitors: {
    dau: [
      { date: "2026-05-25", active_visitors: 42, page_views: 310 },
      { date: "2026-05-26", active_visitors: 55, page_views: 420 },
      { date: "2026-05-27", active_visitors: 48, page_views: 380 },
      { date: "2026-05-28", active_visitors: 63, page_views: 510 },
      { date: "2026-05-29", active_visitors: 71, page_views: 580 },
      { date: "2026-05-30", active_visitors: 120, page_views: 940 },
      { date: "2026-05-31", active_visitors: 135, page_views: 1100 },
      { date: "2026-06-01", active_visitors: 128, page_views: 1020 },
      { date: "2026-06-02", active_visitors: 95, page_views: 760 },
      { date: "2026-06-03", active_visitors: 110, page_views: 880 },
    ],
    category_popularity: [
      { category: "cs.AI", views: 8900 },
      { category: "cs.LG", views: 3200 },
      { category: "cs.RO", views: 1800 },
      { category: "quant-ph", views: 950 },
      { category: "cs.IR", views: 620 },
      { category: "cond-mat.mtrl-sci", views: 410 },
      { category: "cs.IT", views: 380 },
      { category: "gr-qc", views: 290 },
      { category: "stat.ML", views: 250 },
      { category: "astro-ph.HE", views: 180 },
      { category: "cs.CL", views: 160 },
      { category: "cs.CV", views: 140 },
      { category: "hep-th", views: 120 },
      { category: "math.OC", views: 90 },
      { category: "cs.SE", views: 70 },
      { category: "physics.comp-ph", views: 45 },
      { category: "q-bio.BM", views: 30 },
      { category: "eess.SP", views: 20 },
      { category: "cs.DC", views: 10 },
      { category: "cs.DB", views: 5 },
      { category: "nlin.CD", views: 0 },
    ],
  },
  registered: {
    dau: [
      { date: "2026-05-25", active_users: 12 },
      { date: "2026-05-26", active_users: 18 },
      { date: "2026-05-27", active_users: 15 },
      { date: "2026-05-28", active_users: 22 },
      { date: "2026-05-29", active_users: 28 },
      { date: "2026-05-30", active_users: 45 },
      { date: "2026-05-31", active_users: 70 },
      { date: "2026-06-01", active_users: 54 },
      { date: "2026-06-02", active_users: 38 },
      { date: "2026-06-03", active_users: 42 },
    ],
    visit_frequency: [
      { bucket: "1", count: 98 },
      { bucket: "2", count: 25 },
      { bucket: "3-4", count: 8 },
      { bucket: "5-9", count: 4 },
      { bucket: "10+", count: 2 },
    ],
    returning_since_may31: 21,
    category_popularity: [
      { category: "cs.AI", views: 52 },
      { category: "cs.LG", views: 18 },
      { category: "cs.RO", views: 12 },
      { category: "quant-ph", views: 8 },
      { category: "cs.IR", views: 6 },
      { category: "cond-mat.mtrl-sci", views: 5 },
      { category: "cs.IT", views: 4 },
      { category: "gr-qc", views: 3 },
      { category: "stat.ML", views: 3 },
      { category: "astro-ph.HE", views: 2 },
      { category: "cs.CL", views: 2 },
      { category: "cs.CV", views: 1 },
      { category: "hep-th", views: 1 },
      { category: "math.OC", views: 0 },
      { category: "cs.SE", views: 0 },
      { category: "physics.comp-ph", views: 0 },
      { category: "q-bio.BM", views: 0 },
      { category: "eess.SP", views: 0 },
      { category: "cs.DC", views: 0 },
      { category: "cs.DB", views: 0 },
      { category: "nlin.CD", views: 0 },
    ],
  },
};

export default function ChartTestPage() {
  const d = MOCK;
  const allCats = d.all_visitors.category_popularity;
  const catOrder = allCats.map(c => c.category);
  const regCatMap = Object.fromEntries(d.registered.category_popularity.map(c => [c.category, c.views]));
  const regCatsOrdered = catOrder.map(c => ({ category: c, views: regCatMap[c] || 0 }));
  const allCatsR = [...allCats].reverse();
  const regCatsR = [...regCatsOrdered].reverse();
  const catH = Math.max(200, allCats.length * 22);
  const tt = { background: "hsl(var(--background))", border: "1px solid hsl(var(--border))", borderRadius: "6px", fontSize: "11px" };
  const fmtD = d => { try { return new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" }); } catch { return d; } };

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-5xl py-6 md:py-10">
      <h1 className="font-heading text-2xl font-semibold mb-2">Chart Visual Test</h1>
      <p className="text-sm text-muted-foreground mb-6">Fictitious data — for layout/alignment debugging only</p>

      {/* Row 1: 2x2 time-series charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div className="p-4 rounded-lg border border-border bg-secondary/10">
          <h3 className="text-sm font-medium mb-0.5">Daily Active Visitors</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Unique visitors per day (all traffic)</p>
          <div className="h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.all_visitors.dau} margin={{ top: 5, right: 10, left: -5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={fmtD} />
                <YAxis tick={{ fontSize: 9 }} width={35} />
                <RTooltip contentStyle={tt} />
                <Line type="monotone" dataKey="active_visitors" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3, fill: "#3b82f6" }} activeDot={{ r: 5 }} name="All visitors" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="p-4 rounded-lg border border-border bg-secondary/10">
          <h3 className="text-sm font-medium mb-0.5">Daily Active Registered Users</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Unique authenticated sessions per day</p>
          <div className="h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.registered.dau} margin={{ top: 5, right: 10, left: -5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={fmtD} />
                <YAxis tick={{ fontSize: 9 }} width={35} />
                <RTooltip contentStyle={tt} />
                <Line type="monotone" dataKey="active_users" stroke="#8b5cf6" strokeWidth={2} dot={{ r: 3, fill: "#8b5cf6" }} activeDot={{ r: 5 }} name="Registered users" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="p-4 rounded-lg border border-border bg-secondary/10">
          <h3 className="text-sm font-medium mb-0.5">Daily Page Views</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Total API hits per day (all traffic)</p>
          <div className="h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.all_visitors.dau} margin={{ top: 5, right: 10, left: -5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={fmtD} />
                <YAxis tick={{ fontSize: 9 }} width={35} />
                <RTooltip contentStyle={tt} />
                <Line type="monotone" dataKey="page_views" stroke="#0ea5e9" strokeWidth={2} dot={{ r: 3, fill: "#0ea5e9" }} activeDot={{ r: 5 }} name="Page views" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="p-4 rounded-lg border border-border bg-secondary/10">
          <h3 className="text-sm font-medium mb-0.5">Visit Frequency</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Registered user sessions (since May 31) &middot; 21 returning</p>
          <div className="h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={d.registered.visit_frequency} margin={{ top: 5, right: 10, left: -5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 9 }} width={35} />
                <RTooltip contentStyle={tt} />
                <Bar dataKey="count" fill="#8b5cf6" radius={[3, 3, 0, 0]} name="Users" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Row 2: Category Popularity side by side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="p-4 rounded-lg border border-border bg-secondary/10">
          <h3 className="text-sm font-medium mb-0.5">Category Popularity — All Traffic</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Leaderboard views by category</p>
          <div style={{ height: catH }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart layout="vertical" data={allCatsR} margin={{ top: 5, right: 10, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 9 }} />
                <YAxis type="category" dataKey="category" tick={{ fontSize: 8 }} width={90} interval={0} />
                <RTooltip contentStyle={tt} />
                <Bar dataKey="views" fill="#10b981" radius={[0, 3, 3, 0]} name="Views" barSize={14} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="p-4 rounded-lg border border-border bg-secondary/10">
          <h3 className="text-sm font-medium mb-0.5">Category Popularity — Registered Users</h3>
          <p className="text-[10px] text-muted-foreground mb-3">Leaderboard views by logged-in users</p>
          <div style={{ height: catH }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart layout="vertical" data={regCatsR} margin={{ top: 5, right: 10, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 9 }} />
                <YAxis type="category" dataKey="category" tick={{ fontSize: 8 }} width={90} interval={0} />
                <RTooltip contentStyle={tt} />
                <Bar dataKey="views" fill="#a78bfa" radius={[0, 3, 3, 0]} name="Views" barSize={14} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
