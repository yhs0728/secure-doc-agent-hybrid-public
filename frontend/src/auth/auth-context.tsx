import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, type CurrentUser, getAccessToken, setAccessToken } from "@/api/client";

interface AuthValue {
  user: CurrentUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(Boolean(getAccessToken()));

  const logout = useCallback(() => {
    setAccessToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    const unauthorized = () => logout();
    window.addEventListener("securedoc:unauthorized", unauthorized);
    return () => window.removeEventListener("securedoc:unauthorized", unauthorized);
  }, [logout]);

  useEffect(() => {
    if (!getAccessToken()) {
      setLoading(false);
      return;
    }
    api.me().then(setUser).catch(logout).finally(() => setLoading(false));
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const token = await api.login(email, password);
    setAccessToken(token.access_token);
    try {
      setUser(await api.me());
    } catch (error) {
      setAccessToken(null);
      throw error;
    }
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
