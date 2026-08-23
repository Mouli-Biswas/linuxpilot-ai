import { useCallback, useEffect, useState } from "react";

import QueryBox from "./components/QueryBox";
import PlanTrace from "./components/PlanTrace";
import MetricsBar from "./components/MetricsBar";
import {
  askAgent,
  getHistory,
  getSystemMetrics,
  type AgentRunResult,
  type SystemMetricsSnapshot,
} from "./services/agentApi";
import { useGlobalShortcut } from "./hooks/useGlobalShortcut";

const EXAMPLE_QUERIES = [
  { label: "⚡ System Diagnostics", query: "Why is my computer running slowly?" },
  { label: "🔍 Large Files", query: "Find all large files in my home directory" },
  { label: "🐍 Python Files (>50MB)", query: "Find Python files larger than 50 MB in my home directory" },
  { label: "⚙️ Nginx Status", query: "Show me the status of nginx" },
  { label: "📜 Error Logs", query: "Show recent system errors" },
  { label: "💡 Explain chmod 755", query: "Explain what chmod 755 means" },
  { label: "📊 Disk Usage (df -h)", query: "df -h" },
  { label: "⚠️ Restart Nginx (Modifying)", query: "systemctl restart nginx" },
];

export default function App() {
  const [visible, setVisible] = useState(true);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<AgentRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<SystemMetricsSnapshot | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [currentQuery, setCurrentQuery] = useState("");

  const toggleVisible = useCallback(() => setVisible((v) => !v), []);
  useGlobalShortcut(toggleVisible);

  // Initial load of metrics and history
  useEffect(() => {
    loadMetrics();
    loadHistory();
    const interval = setInterval(loadMetrics, 10000);
    return () => clearInterval(interval);
  }, []);

  async function loadMetrics() {
    const snap = await getSystemMetrics();
    setMetrics(snap);
  }

  async function loadHistory() {
    const rows = await getHistory(10);
    setHistory(rows);
  }

  async function handleQuery(query: string, confirmed: boolean = false) {
    if (confirmed) {
      setConfirming(true);
    } else {
      setLoading(true);
    }
    setError(null);
    setCurrentQuery(query);

    const res = await askAgent(query, confirmed);
    setLoading(false);
    setConfirming(false);

    if (res.success && res.result) {
      setResult(res.result);
      loadHistory();
    } else {
      setError(res.error ?? "Unknown error occurred while processing request.");
    }
  }

  if (!visible) return null;

  return (
    <div className="min-h-screen w-full max-w-full overflow-x-hidden bg-pilot-bg text-gray-100 flex flex-col items-center p-4 sm:p-6 font-sans">
      <div className="w-full max-w-3xl rounded-xl border border-gray-800/90 bg-pilot-panel shadow-2xl overflow-hidden backdrop-blur-sm">
        {/* App Header */}
        <div className="px-5 py-3.5 border-b border-gray-800 flex items-center justify-between bg-gray-950/60">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-pilot-accent/15 border border-pilot-accent/30 flex items-center justify-center text-pilot-accent font-mono font-bold text-sm">
              LP
            </div>
            <div>
              <h1 className="font-semibold text-gray-100 text-sm flex items-center gap-2">
                LinuxPilot AI
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-pilot-accent/20 text-pilot-accent border border-pilot-accent/30">
                  Agentic Ops
                </span>
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowHistory((h) => !h)}
              className="text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded bg-gray-900 border border-gray-800 transition"
            >
              {showHistory ? "Hide History" : "Recent History"}
            </button>
            <span className="text-xs text-gray-500 font-mono hidden sm:inline">
              Super + Space
            </span>
          </div>
        </div>

        {/* Live System Diagnostics Bar */}
        <MetricsBar metrics={metrics} />

        {/* Example Quick Action Chips */}
        <div className="px-4 py-2.5 bg-gray-950/40 border-b border-gray-800/60 flex items-center gap-2 overflow-x-auto text-xs no-scrollbar">
          <span className="text-gray-500 font-medium shrink-0">Try:</span>
          {EXAMPLE_QUERIES.map((item, idx) => (
            <button
              key={idx}
              onClick={() => handleQuery(item.query)}
              className="px-2.5 py-1 rounded-full bg-gray-900/80 hover:bg-gray-800 text-gray-300 hover:text-white border border-gray-800/80 shrink-0 transition"
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Query Input Box */}
        <QueryBox onSubmit={(q) => handleQuery(q, false)} loading={loading || confirming} initialValue={currentQuery} />

        {/* Error Alert Box */}
        {error && (
          <div className="p-4 m-4 rounded-lg bg-red-950/40 border border-red-800 text-red-300 text-xs flex items-center justify-between">
            <span><strong>Error:</strong> {error}</span>
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-red-200 font-bold ml-2"
            >
              ✕
            </button>
          </div>
        )}

        {/* History Drawer */}
        {showHistory && (
          <div className="p-4 bg-gray-950/70 border-b border-gray-800 text-xs space-y-2">
            <div className="font-semibold text-gray-400 uppercase tracking-wider">
              Recent Interaction History
            </div>
            {history.length === 0 ? (
              <div className="text-gray-500">No interaction history recorded yet.</div>
            ) : (
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {history.map((h) => (
                  <div
                    key={h.id}
                    onClick={() => handleQuery(h.query)}
                    className="p-2 rounded bg-gray-900/80 border border-gray-800/80 flex items-center justify-between hover:border-gray-700 cursor-pointer transition"
                  >
                    <span className="truncate text-gray-200 font-medium">{h.query}</span>
                    <div className="flex items-center gap-2 shrink-0 text-gray-500 font-mono text-[10px]">
                      <span>{h.intent}</span>
                      <span>· {h.duration_ms}ms</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Plan Trace & Execution Result */}
        {result && (
          <PlanTrace
            result={result}
            onConfirmCommand={(q) => handleQuery(q, true)}
            confirming={confirming}
          />
        )}

        {/* Welcome State */}
        {!result && !error && !loading && (
          <div className="p-8 text-center space-y-2">
            <div className="text-gray-300 font-medium text-sm">
              LinuxPilot AI Assistant Ready
            </div>
            <p className="text-gray-500 text-xs max-w-md mx-auto">
              Ask system diagnostics, search for files, inspect and manage services, analyze logs, or learn Linux commands.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
