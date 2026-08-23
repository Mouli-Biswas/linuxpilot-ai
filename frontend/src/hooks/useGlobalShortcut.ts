/**
 * useGlobalShortcut.ts
 * --------------------
 * Registers the Super+Space global shortcut via Tauri's global-shortcut
 * plugin so LinuxPilot AI can be summoned from anywhere on the desktop,
 * not just when the window already has focus. No-ops gracefully when
 * running outside Tauri (e.g. `vite dev` in a plain browser tab).
 */

import { useEffect } from "react";

const SHORTCUT = "Super+Space";

export function useGlobalShortcut(onTrigger: () => void) {
  useEffect(() => {
    let unregister: (() => void) | undefined;
    let cancelled = false;

    async function register() {
      try {
        const { register: registerShortcut, unregisterAll } = await import(
          "@tauri-apps/api/globalShortcut"
        );
        await unregisterAll();
        await registerShortcut(SHORTCUT, () => {
          if (!cancelled) onTrigger();
        });
        unregister = () => {
          unregisterAll().catch(() => void 0);
        };
      } catch {
        // Not running inside the Tauri shell (e.g. plain browser dev mode).
        // Silently skip — this is expected during `vite dev`.
      }
    }

    register();
    return () => {
      cancelled = true;
      unregister?.();
    };
  }, [onTrigger]);
}
