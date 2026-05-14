import { useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip as RechartsTooltip, ReferenceLine,
} from "recharts";

function generateSimData() {
  const now = Date.now();
  const data = [];

  // First 3 hours: legacy data (no role), memory ~1400-1800MB
  for (let i = 0; i < 180; i += 2) {
    const epoch = now - (360 - i) * 60000;
    const rss = 1400 + Math.sin(i / 30) * 200 + Math.random() * 100;
    data.push({
      epoch, rss: Math.round(rss), role: "unknown",
      rss_unknown: Math.round(rss), rss_leader: null, rss_follower: null,
      label: "comparison_round",
    });
  }

  const restartEpoch = now - 180 * 60000;

  // Next 3 hours: leader + follower
  let lastLeader = null, lastFollower = null;
  for (let i = 180; i < 360; i += 2) {
    const epoch = now - (360 - i) * 60000;
    const rssL = Math.round(800 + Math.sin(i / 25) * 300 + Math.random() * 80);
    const rssF = Math.round(400 + Math.sin(i / 20) * 100 + Math.random() * 50);
    lastLeader = rssL; lastFollower = rssF;
    data.push({
      epoch, rss: rssL, role: "leader", label: "_check_goals",
      rss_unknown: null, rss_leader: rssL, rss_follower: lastFollower,
    });
    data.push({
      epoch: epoch + 60000, rss: rssF, role: "follower", label: "heartbeat",
      rss_unknown: null, rss_leader: lastLeader, rss_follower: rssF,
    });
  }

  const restartEvents = [
    { epoch: restartEpoch, role: "leader", event: "shutdown_signal", signal: "SIGTERM" },
    { epoch: restartEpoch + 5000, role: "follower", event: "shutdown_signal", signal: "SIGTERM" },
    { epoch: restartEpoch + 30000, role: "leader", event: "server_started" },
    { epoch: restartEpoch + 35000, role: "follower", event: "server_started" },
    { epoch: now - 90 * 60000, role: "leader", event: "server_started" },
  ];

  return { data, restartEvents };
}

export default function SimulatedMemChart() {
  const [sim] = useState(generateSimData);
  const roleColors = { leader: "#ef4444", follower: "#3b82f6", unknown: "#9ca3af" };
  const getColor = (role) => roleColors[role] || "#9ca3af";

  return (
    <div className="container mx-auto px-6 max-w-5xl py-10">
      <h1 className="text-xl font-bold mb-2">Simulated Memory Chart — Leader / Follower</h1>
      <p className="text-sm text-muted-foreground mb-6">
        First 3h: legacy (grey). After deploy: Leader (red) runs scheduler, Follower (blue) serves HTTP only.
      </p>
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-sm font-medium">Memory Usage (RSS)</h3>
          <span className="text-xs text-muted-foreground">Simulated</span>
        </div>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={sim.data} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="memGradSim" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
              <XAxis dataKey="epoch" type="number" scale="time"
                domain={[sim.data[0]?.epoch, sim.data[sim.data.length - 1]?.epoch]}
                tickFormatter={(e) => new Date(e).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}
                tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
              <YAxis domain={[0, 4096]} ticks={[0, 1024, 2048, 3072, 4096]} tickFormatter={v => `${v}MB`} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" width={55} />
              <RechartsTooltip content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                return (
                  <div className="rounded-lg border border-border bg-popover p-2 shadow-lg text-xs">
                    <div className="font-medium">{new Date(d?.epoch).toLocaleTimeString()}</div>
                    <div className="text-muted-foreground">{d?.role !== "unknown" ? d?.role?.charAt(0).toUpperCase() + d?.role?.slice(1) : "Pre-deploy"}</div>
                    <div className="font-mono mt-1" style={{ color: d?.rss > 1536 ? "#ef4444" : d?.rss > 1024 ? "#f59e0b" : "#10b981" }}>{d?.rss}MB</div>
                  </div>
                );
              }} />
              {sim.restartEvents.filter(e => e.event === "server_started").map((d, i) => (
                <ReferenceLine key={`r-${i}`} x={d.epoch} stroke={getColor(d.role)} strokeDasharray="4 4" strokeWidth={1} opacity={0.6} />
              ))}
              {sim.restartEvents.filter(e => e.event === "shutdown_signal").map((d, i) => (
                <ReferenceLine key={`s-${i}`} x={d.epoch} stroke={getColor(d.role)} strokeDasharray="8 3" strokeWidth={1.5} opacity={0.8} />
              ))}
              <Area type="monotone" dataKey={() => 4096} stroke="none" fill="#ef4444" fillOpacity={0.05} />
              <Area type="stepAfter" dataKey="rss_unknown" stroke="#9ca3af" fill="#9ca3af" fillOpacity={0.03} strokeWidth={1} dot={false} connectNulls={false} name="Pre-deploy" />
              <Area type="stepAfter" dataKey="rss_leader" stroke="#ef4444" fill="#ef4444" fillOpacity={0.05} strokeWidth={1.5} dot={false} connectNulls={false} name="Leader" />
              <Area type="stepAfter" dataKey="rss_follower" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.05} strokeWidth={1.5} dot={false} connectNulls={false} name="Follower" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="flex flex-wrap items-center gap-4 mt-3 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-red-500" /> Leader (scheduler, comparisons, fetching)</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue-500" /> Follower (HTTP traffic only)</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-gray-400" /> Pre-deploy (legacy)</span>
          <span className="flex items-center gap-1 ml-2 border-l pl-2 border-border"><span className="w-4 border-t border-dashed border-foreground/40" /> Restart</span>
          <span className="flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-foreground/60" /> SIGTERM</span>
        </div>
      </div>
    </div>
  );
}
