import type { SystemMetricsSnapshot } from "../services/agentApi";


interface Props {
  metrics: SystemMetricsSnapshot | null;
  loading?: boolean;
}

export default function MetricsBar({ metrics, loading }: Props) {
  if (!metrics && !loading) return null;

  const cpu = metrics?.cpuUsage ?? 0;
  const mem = metrics?.memoryUsage ?? 0;
  const disk = metrics?.diskUsage ?? 0;
  const net = metrics?.networkConnected ?? true;

  const getUsageColor = (pct: number) => {
    if (pct >= 85) return "text-red-400 bg-red-950/40 border-red-800/60";
    if (pct >= 70) return "text-yellow-400 bg-yellow-950/40 border-yellow-800/60";
    return "text-emerald-400 bg-emerald-950/40 border-emerald-800/60";
  };

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 px-4 py-2 bg-pilot-panel/60 border-b border-gray-800/80 text-xs">
      <div className={`flex items-center justify-between px-2.5 py-1.5 rounded-md border ${getUsageColor(cpu)}`}>
        <span className="text-gray-400 font-mono">CPU</span>
        <span className="font-semibold">{cpu.toFixed(1)}%</span>
      </div>

      <div className={`flex items-center justify-between px-2.5 py-1.5 rounded-md border ${getUsageColor(mem)}`}>
        <span className="text-gray-400 font-mono">RAM</span>
        <span className="font-semibold">{mem.toFixed(1)}%</span>
      </div>

      <div className={`flex items-center justify-between px-2.5 py-1.5 rounded-md border ${getUsageColor(disk)}`}>
        <span className="text-gray-400 font-mono">DISK</span>
        <span className="font-semibold">{disk.toFixed(1)}%</span>
      </div>

      <div className="flex items-center justify-between px-2.5 py-1.5 rounded-md border border-gray-800 bg-gray-900/60 text-gray-300">
        <span className="text-gray-400 font-mono">NET</span>
        <span className="flex items-center gap-1 font-semibold text-emerald-400">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          {net ? "Online" : "Offline"}
        </span>
      </div>
    </div>
  );
}
