import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setSession, hasSession } from "../lib/api";
import { rawInitData } from "../lib/telegram";
import type { AuthResult, UserProfile } from "../lib/types";

interface SessionState {
  user: UserProfile | null;
  ready: boolean;
  error: string | null;
  login: (initDataOverride?: string) => Promise<void>;
  refresh: () => Promise<void>;
  acceptRules: () => Promise<void>;
  logout: () => void;
}

/**
 * Session context.
 *
 * Exported so that components can be rendered with a prepared session
 * (tests and previews) without going through the Telegram handshake.
 */
export const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = useCallback(async (initDataOverride?: string) => {
    setError(null);
    const initData = initDataOverride ?? rawInitData();
    if (!initData) {
      setError("Открой BONVERA через Telegram-бота, чтобы авторизоваться.");
      setReady(true);
      return;
    }
    try {
      const res = await api.post<AuthResult>("/auth/telegram", { initData });
      setSession(res.token);
      setUser(res.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось авторизоваться.");
    } finally {
      setReady(true);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<UserProfile>("/me");
      setUser(me);
    } catch {
      // session expired; gate will re-login
      setUser(null);
      setSession(null);
    }
  }, []);

  const acceptRules = useCallback(async () => {
    const me = await api.post<UserProfile>("/me/accept");
    setUser(me);
  }, []);

  const logout = useCallback(() => {
    // Revoke the server-side session before clearing the local bearer token.
    void api.post<{ logged_out: boolean }>("/auth/logout").catch(() => undefined).finally(() => {
      setSession(null);
      setUser(null);
      void login();
    });
  }, [login]);

  useEffect(() => {
    if (hasSession()) {
      refresh().finally(() => setReady(true));
    } else {
      void login();
    }
  }, [login, refresh]);

  return (
    <SessionContext.Provider value={{ user, ready, error, login, refresh, acceptRules, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}