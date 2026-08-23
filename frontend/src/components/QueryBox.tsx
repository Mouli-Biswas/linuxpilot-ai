import { useEffect, useState, type FormEvent } from "react";


interface Props {
  onSubmit: (query: string) => void;
  loading: boolean;
  initialValue?: string;
}

export default function QueryBox({ onSubmit, loading, initialValue = "" }: Props) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    if (initialValue) {
      setValue(initialValue);
    }
  }, [initialValue]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim() || loading) return;
    onSubmit(value.trim());
  }


  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 p-3.5 border-b border-gray-800 bg-pilot-bg">
      <div className="relative flex-1">
        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-500 font-mono text-sm">
          &gt;
        </div>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask LinuxPilot AI... e.g. 'Why is my system slow?' or 'Find large files'"
          className="w-full bg-pilot-panel text-gray-100 placeholder-gray-500 rounded-lg pl-8 pr-9 py-2.5 outline-none border border-gray-800 focus:border-pilot-accent focus:ring-1 focus:ring-pilot-accent text-sm transition"
          disabled={loading}
        />
        {value && !loading && (
          <button
            type="button"
            onClick={() => setValue("")}
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-300 text-xs"
          >
            ✕
          </button>
        )}
      </div>

      <button
        type="submit"
        disabled={loading || !value.trim()}
        className="px-5 py-2.5 rounded-lg bg-pilot-accent hover:bg-sky-400 text-black font-semibold text-sm transition flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-sky-500/10"
      >
        {loading ? (
          <>
            <span className="w-3.5 h-3.5 rounded-full border-2 border-black border-t-transparent animate-spin"></span>
            <span>Analyzing...</span>
          </>
        ) : (
          <span>Execute</span>
        )}
      </button>
    </form>
  );
}
