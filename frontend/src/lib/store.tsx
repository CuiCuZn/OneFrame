import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "./api";
import { applyTheme, persistTheme, resolveTheme, storedTheme, type ResolvedTheme, type ThemeMode } from "./theme";
import type { Catalog, Channel, Model } from "./types";

export interface Toast {
  id: number;
  message: string;
  kind: "info" | "success" | "error";
}

interface StoreValue {
  catalog: Catalog | null;
  models: Model[];
  channels: Channel[];
  settings: Record<string, string>;
  loading: boolean;
  error: string | null;
  toasts: Toast[];
  toast: (message: string, kind?: Toast["kind"]) => void;
  dismiss: (id: number) => void;
  refresh: () => Promise<void>;
  refreshModels: () => Promise<void>;
  refreshChannels: () => Promise<void>;
  saveSetting: (key: string, value: string) => Promise<void>;
  theme: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setTheme: (mode: ThemeMode) => void;
}

const StoreContext = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [theme, setThemeState] = useState<ThemeMode>(() => storedTheme() ?? "auto");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() =>
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  const counter = useRef(0);
  const timers = useRef<number[]>([]);

  const setTheme = useCallback((mode: ThemeMode) => {
    setThemeState(mode);
    persistTheme(mode);
    setResolvedTheme(applyTheme(mode));
    void api.settings.save({ theme: mode }).catch(() => {
      /* the preference still applies locally */
    });
  }, []);

  useEffect(() => {
    setResolvedTheme(applyTheme(theme));
    if (theme !== "auto") return;
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => setResolvedTheme(applyTheme("auto"));
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [theme]);

  const toast = useCallback((message: string, kind: Toast["kind"] = "info") => {
    counter.current += 1;
    const id = counter.current;
    setToasts((current) => [...current.slice(-3), { id, message, kind }]);
    const timer = window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, kind === "error" ? 5200 : 3200);
    timers.current.push(timer);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  useEffect(() => () => timers.current.forEach((timer) => window.clearTimeout(timer)), []);

  const refreshModels = useCallback(async () => {
    setModels(await api.models.list());
  }, []);

  const refreshChannels = useCallback(async () => {
    setChannels(await api.channels.list());
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextCatalog, nextModels, nextChannels, nextSettings] = await Promise.all([
        api.catalog(),
        api.models.list(),
        api.channels.list(),
        api.settings.get(),
      ]);
      setCatalog(nextCatalog);
      setModels(nextModels);
      setChannels(nextChannels);
      setSettings(nextSettings);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "初始化失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const saveSetting = useCallback(async (key: string, value: string) => {
    const next = await api.settings.save({ [key]: value });
    setSettings(next);
  }, []);

  const value = useMemo<StoreValue>(
    () => ({
      catalog,
      models,
      channels,
      settings,
      loading,
      error,
      toasts,
      toast,
      dismiss,
      refresh,
      refreshModels,
      refreshChannels,
      saveSetting,
      theme,
      resolvedTheme,
      setTheme,
    }),
    [
      catalog,
      models,
      channels,
      settings,
      loading,
      error,
      toasts,
      toast,
      dismiss,
      refresh,
      refreshModels,
      refreshChannels,
      saveSetting,
      theme,
      resolvedTheme,
      setTheme,
    ],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const value = useContext(StoreContext);
  if (!value) throw new Error("useStore must be used inside StoreProvider");
  return value;
}
