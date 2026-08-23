/**
 * agentApi.ts
 * -----------
 * Fetch wrapper around the LinuxPilot AI FastAPI backend.
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface AgentStepResult {
  step: number;
  tool: string;
  description: string;
  output: Record<string, any>;
  duration_ms: number;
}

export interface AgentTimings {
  classification_ms: number;
  planning_ms: number;
  tool_execution_ms: number;
  summarization_ms: number;
  total_ms: number;
}

export interface AgentRunResult {
  query: string;
  intent: string;
  confidence: number;
  plan: { step: number; tool: string; description: string }[];
  step_results: AgentStepResult[];
  final_answer: string;
  total_duration_ms: number;
  timings?: AgentTimings;
}

export interface AgentQueryResponse {
  success: boolean;
  result?: AgentRunResult;
  error?: string;
}

export interface SystemMetricsSnapshot {
  cpuUsage?: number;
  memoryUsage?: number;
  diskUsage?: number;
  networkConnected?: boolean;
}

export async function askAgent(query: string, confirmed: boolean = false): Promise<AgentQueryResponse> {
  try {
    const res = await fetch(`${API_BASE}/api/agent/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, confirmed }),
    });
    if (!res.ok) {
      return { success: false, error: `HTTP ${res.status}: ${res.statusText}` };
    }
    return (await res.json()) as AgentQueryResponse;
  } catch (err: any) {
    return { success: false, error: err.message || "Failed to connect to backend." };
  }
}

export async function getHistory(limit: number = 10): Promise<any[]> {
  try {
    const res = await fetch(`${API_BASE}/api/agent/history?limit=${limit}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.history || [];
  } catch {
    return [];
  }
}

export async function getSystemMetrics(): Promise<SystemMetricsSnapshot> {
  const snapshot: SystemMetricsSnapshot = {};
  try {
    const [cpuRes, memRes, diskRes, netRes] = await Promise.allSettled([
      fetch(`${API_BASE}/api/diagnostics/cpu?sample_seconds=0.2`).then(r => r.json()),
      fetch(`${API_BASE}/api/diagnostics/memory`).then(r => r.json()),
      fetch(`${API_BASE}/api/diagnostics/disk`).then(r => r.json()),
      fetch(`${API_BASE}/api/diagnostics/network`).then(r => r.json()),
    ]);

    if (cpuRes.status === "fulfilled" && cpuRes.value?.data) {
      snapshot.cpuUsage = cpuRes.value.data.usage_percent;
    }
    if (memRes.status === "fulfilled" && memRes.value?.data) {
      snapshot.memoryUsage = memRes.value.data.used_percent;
    }
    if (diskRes.status === "fulfilled" && diskRes.value?.data) {
      snapshot.diskUsage = diskRes.value.data.used_percent;
    }
    if (netRes.status === "fulfilled" && netRes.value?.data) {
      snapshot.networkConnected = netRes.value.data.internet_connected;
    }
  } catch {
    // Graceful fallback
  }
  return snapshot;
}
