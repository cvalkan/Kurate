import { useState } from "react";
import {
  AreaChart, Area, ComposedChart, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip as RechartsTooltip, ReferenceLine,
} from "recharts";

// Simulated 6h of data with 2 pods
function generateSimData() {
  const now = Date.now();
  const data = [];
  const pod1 = "pod-abc123-9";
  const pod2 = "pod-def456-10";

  // First 3 hours: legacy data (no pod_id), memory ~1400-1800MB
  for (let i = 0; i < 180; i += 2) {
    const epoch = now - (360 - i) * 60000;
    const rss = 1400 + Math.sin(i / 30) * 200 + Math.random() * 100;
    data.push({
      epoch,
      ts: new Date(epoch).toISOString(),
      rss: Math.round(rss),
      pod_id: "__legacy__",
      label: "comparison_round",
      [`rss___legacy__`]: Math.round(rss),
      [`rss_${pod1}`]: null,
      [`rss_${pod2}`]: null,
    });
  }

  // Restart at 3h mark (deploy)
  const restartEpoch = now - 180 * 60000;

  // Next 3 hours: two pods with pod_id
  for (let i = 180; i < 360; i += 2) {
    const epoch = now - (360 - i) * 60000;
    const rss1 = 800 + Math.sin(i / 25) * 300 + Math.random() * 80;
    const rss2 = 400 + Math.sin(i / 20) * 100 + Math.random() * 50;
    data.push({
      epoch,
      ts: new Date(epoch).toISOString(),
      rss: Math.round(rss1),
      pod_id: pod1,
      label: "_check_goals",
      [`rss___legacy__`]: null,
      [`rss_${pod1}`]: Math.round(rss1),
      [`rss_${pod2}`]: null,
    });
    data.push({
      epoch: epoch + 30000,
      ts: new Date(epoch + 30000).toISOString(),
      rss: Math.round(rss2),
      pod_id: pod2,
      label: "heartbeat",
      [`rss___legacy__`]: null,
      [`rss_${pod1}`]: null,
      [`rss_${pod2}`]: Math.round(rss2),
    });
  }

  const restartEvents = [
    { epoch: restartEpoch, pod_id: pod1, event: "shutdown_signal", signal: "SIGTERM" },
    { epoch: restartEpoch + 5000, pod_id: pod2, event: "shutdown_signal", signal: "SIGTERM" },
    { epoch: restartEpoch + 30000, pod_id: pod1, event: "server_started" },
    { epoch: restartEpoch + 35000, pod_id: pod2, event: "server_started" },
    // An unexplained restart for pod1 1.5h ago
    { epoch: now - 90 * 60000, pod_id: pod1, event: "server_started" },
  ];

  return { data, restartEvents, pods: ["__legacy__", pod1, pod2] };
}

export default function SimulatedMemChart() {
  const [sim] = useState(generateSimData);
  const podColors = ["#ef4444", "#3b82f6", "#10b981", "#8b5cf6", "#f59e0b"];
  const pods = sim.pods;

  const podColor = (pod) => {
    const idx = pods.indexOf(pod);
    return podColors[idx % podColors.length] || "#888";
  };

  return (
    <div className="container mx-auto px-6 max-w-5xl py-10">
      <h1 className="text-xl font-bold mb-2">Simulated Memory Chart — 2 Pods</h1>
      <p className="text-sm text-muted-foreground mb-6">
        First 3h: legacy data (single red line, no pod_id). After deploy: pod-abc (red) = leader, pod-def (blue) = follower.
      </p>
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-sm font-medium">Memory Usage (RSS)</h3>
          <span className="text-xs text-muted-foreground">Simulated: Current 892MB / 4096MB</span>
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
              <XAxis
                dataKey="epoch" type="number" scale="time"
                domain={[sim.data[0]?.epoch, sim.data[sim.data.length - 1]?.epoch]}
                tickFormatter={(e) => new Date(e).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}
                tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))"
              />
              <YAxis domain={[0, 4096]} ticks={[0, 1024, 2048, 3072, 4096]} tickFormatter={v => `${v}MB`} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" width={55} />
              <RechartsTooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0]?.payload;
                  return (
                    <div className="rounded-lg border border-border bg-popover p-2 shadow-lg text-xs">
                      <div className="font-medium">{new Date(d?.epoch).toLocaleTimeString()}</div>
                      <div className="text-muted-foreground">{d?.label}</div>
                      {d?.pod_id && d.pod_id !== "__legacy__" && <div className="text-muted-foreground">Pod: {d.pod_id}</div>}
                      <div className="font-mono mt-1" style={{ color: d?.rss > 1536 ? "#ef4444" : d?.rss > 1024 ? "#f59e0b" : "#10b981" }}>
                        {d?.rss}MB
                      </div>
                    </div>
                  );
                }}
              />
              {/* Restart markers */}
              {sim.restartEvents.filter(e => e.event === "server_started").map((d, i) => (
                <ReferenceLine key={`restart-${i}`} x={d.epoch} stroke={podColor(d.pod_id)} strokeDasharray="4 4" strokeWidth={1} opacity={0.6} />
              ))}
              {sim.restartEvents.filter(e => e.event === "shutdown_signal").map((d, i) => (
                <ReferenceLine key={`sig-${i}`} x={d.epoch} stroke={podColor(d.pod_id)} strokeDasharray="8 3" strokeWidth={1.5} opacity={0.8} />
              ))}
              {/* Danger zone bg */}
              <Area type="monotone" dataKey={() => 4096} stroke="none" fill="#ef4444" fillOpacity={0.05} />
              {/* Legacy line (pre-deploy) */}
              <Area type="stepAfter" dataKey="rss___legacy__" stroke="#ef4444" fill="url(#memGradSim)" strokeWidth={1.5} dot={false} connectNulls={false} name="pre-deploy" />
              {/* Pod 1 (red) */}
              <Area type="stepAfter" dataKey={`rss_${sim.pods[1]}`} stroke="#ef4444" fill="#ef4444" fillOpacity={0.05} strokeWidth={1.5} dot={false} connectNulls={false} name="pod-abc (leader)" />
              {/* Pod 2 (blue) */}
              <Area type="stepAfter" dataKey={`rss_${sim.pods[2]}`} stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.05} strokeWidth={1.5} dot={false} connectNulls={false} name="pod-def (follower)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="flex flex-wrap items-center gap-4 mt-3 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-red-500" /> Pod 1 (leader)</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue-500" /> Pod 2 (follower)</span>
          <span className="flex items-center gap-1 ml-2 border-l pl-2 border-border"><span className="w-4 border-t border-dashed border-foreground/40" /> Restart</span>
          <span className="flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-foreground/60" /> SIGTERM</span>
          <span className="flex items-center gap-1"><span className="w-4 border-t-2 border-dotted border-foreground/60" /> Unknown kill</span>
        </div>
      </div>
    </div>
  );
}
