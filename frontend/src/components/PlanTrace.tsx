import type { AgentRunResult } from "../services/agentApi";
import MarkdownView from "./MarkdownView";

interface Props {
  result: AgentRunResult;
  onConfirmCommand?: (query: string, operationId?: string) => void;
  confirming?: boolean;
}

export default function PlanTrace({ result, onConfirmCommand, confirming }: Props) {
  const isModifyingConfirmation =
    Boolean(result.pending_authorization) &&
    result.pending_authorization?.status !== "CONSUMED";

  const getIntentBadge = (intent: string) => {
    switch (intent) {
      case "DIAGNOSTICS":
        return "bg-blue-900/40 text-blue-300 border-blue-700/60";
      case "FILE_SEARCH":
        return "bg-purple-900/40 text-purple-300 border-purple-700/60";
      case "SERVICE_MANAGEMENT":
        return "bg-emerald-900/40 text-emerald-300 border-emerald-700/60";
      case "LOG_ANALYSIS":
        return "bg-yellow-900/40 text-yellow-300 border-yellow-700/60";
      case "COMMAND_EXECUTION":
        return "bg-amber-900/40 text-amber-300 border-amber-700/60";
      case "LEARNING_MODE":
        return "bg-cyan-900/40 text-cyan-300 border-cyan-700/60";
      default:
        return "bg-gray-800 text-gray-300 border-gray-700";
    }
  };

  return (
    <div className="p-4 space-y-4 max-w-full overflow-hidden">
      {/* Top Intent & Timing Badge Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2">
          <span className={`px-2.5 py-1 rounded-md border font-semibold tracking-wide ${getIntentBadge(result.intent)}`}>
            {result.intent}
          </span>
          <span className="text-gray-400">
            Confidence: <strong className="text-gray-200">{(result.confidence * 100).toFixed(0)}%</strong>
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-gray-400 bg-gray-900/80 px-2.5 py-1 rounded-md border border-gray-800 font-mono">
          <span>Total:</span>
          <strong className="text-pilot-accent font-mono">{result.total_duration_ms}ms</strong>
        </div>
      </div>

      {/* Execution Pipeline Steps */}
      {result.plan && result.plan.length > 0 && (
        <div className="bg-pilot-panel/80 rounded-lg p-3 border border-gray-800 space-y-2">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Agent Execution Plan
          </div>
          <ol className="space-y-1.5">
            {result.plan.map((step) => {
              const executed = result.step_results?.find((s) => s.step === step.step);
              return (
                <li key={step.step} className="text-xs flex items-center justify-between gap-2 text-gray-300">
                  <div className="flex items-center gap-2 truncate min-w-0">
                    <span className="w-5 h-5 rounded-full bg-gray-800 flex items-center justify-center text-pilot-accent font-mono text-[10px] font-bold border border-gray-700 shrink-0">
                      {step.step}
                    </span>
                    <span className="font-mono text-gray-400 shrink-0">[{step.tool}]</span>
                    <span className="truncate text-gray-200">{step.description}</span>
                  </div>
                  {executed && (
                    <span className="text-[11px] font-mono text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-800/60 shrink-0">
                      ✓ {executed.duration_ms}ms
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {/* Final Answer Display with Clean Markdown Rendering */}
      <div className="p-4 rounded-lg bg-pilot-panel border border-gray-700/80 text-gray-100 space-y-3 overflow-x-auto">
        <MarkdownView content={result.final_answer} />

        {/* Action-Bound Authorization Card */}
        {result.pending_authorization && (
          <div className="p-3.5 rounded-lg bg-amber-950/40 border border-amber-600/50 text-amber-200 text-xs space-y-2">
            <div className="flex items-center justify-between font-semibold text-amber-400">
              <span className="flex items-center gap-1.5">
                🛡️ Action-Bound Security Authorization
              </span>
              <span className="font-mono text-[11px] bg-amber-900/60 px-2 py-0.5 rounded border border-amber-700/50">
                TTL: {result.pending_authorization.ttl_seconds}s
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] font-mono bg-black/50 p-2.5 rounded border border-amber-800/40">
              <div>
                <span className="text-gray-400">Action: </span>
                <span className="text-amber-300 font-bold">{result.pending_authorization.action}</span>
              </div>
              <div>
                <span className="text-gray-400">Target: </span>
                <span className="text-amber-300">{result.pending_authorization.target_resource}</span>
              </div>
              <div className="sm:col-span-2 truncate">
                <span className="text-gray-400">Parameters: </span>
                <span className="text-gray-300">{JSON.stringify(result.pending_authorization.parameters)}</span>
              </div>
              <div className="sm:col-span-2 truncate">
                <span className="text-gray-400">Expected Result: </span>
                <span className="text-emerald-400 font-semibold">{JSON.stringify(result.pending_authorization.expected_postconditions)}</span>
              </div>
              <div>
                <span className="text-gray-400">Status: </span>
                <span className="text-amber-400 font-bold px-1.5 py-0.2 rounded bg-amber-950 border border-amber-700/40">
                  {result.pending_authorization.status || "PENDING"}
                </span>
              </div>
              <div className="truncate">
                <span className="text-gray-400">Expires: </span>
                <span className="text-gray-300">{result.pending_authorization.expires_at}</span>
              </div>
              <div className="sm:col-span-2 truncate">
                <span className="text-gray-400">Ticket ID: </span>
                <span className="text-amber-400">{result.pending_authorization.operation_id}</span>
              </div>
            </div>
          </div>
        )}

        {/* Confirmation Dialog Button for Modifying Commands */}
        {isModifyingConfirmation && onConfirmCommand && (
          <div className="pt-3 border-t border-gray-800 flex flex-wrap items-center gap-3">
            <button
              onClick={() => onConfirmCommand(result.query, result.pending_authorization?.operation_id)}
              disabled={confirming}
              className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-black font-semibold text-xs flex items-center gap-2 transition disabled:opacity-50"
            >
              {confirming ? (
                <>
                  <span className="w-3 h-3 rounded-full border-2 border-black border-t-transparent animate-spin"></span>
                  Approving & Executing...
                </>
              ) : (
                <>⚠️ Explicitly Approve & Execute</>
              )}
            </button>
            <span className="text-xs text-gray-400">
              {result.pending_authorization
                ? "Click to grant explicit user approval and atomically execute this action."
                : "Click to confirm execution."}
            </span>
          </div>
        )}
      </div>

      {/* Granular Timings Breakdown Bar */}
      {result.timings && (
        <div className="flex flex-wrap gap-2 text-[11px] text-gray-400 pt-1">
          <span className="bg-gray-900 px-2 py-0.5 rounded border border-gray-800 font-mono">
            Classify: <strong className="text-gray-200">{result.timings.classification_ms}ms</strong>
          </span>
          <span className="bg-gray-900 px-2 py-0.5 rounded border border-gray-800 font-mono">
            Plan: <strong className="text-gray-200">{result.timings.planning_ms}ms</strong>
          </span>
          <span className="bg-gray-900 px-2 py-0.5 rounded border border-gray-800 font-mono">
            Tools: <strong className="text-gray-200">{result.timings.tool_execution_ms}ms</strong>
          </span>
          <span className="bg-gray-900 px-2 py-0.5 rounded border border-gray-800 font-mono">
            Synthesis: <strong className="text-gray-200">{result.timings.summarization_ms}ms</strong>
          </span>
        </div>
      )}
    </div>
  );
}
