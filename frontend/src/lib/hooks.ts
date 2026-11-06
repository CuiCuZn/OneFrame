import { useCallback, useEffect, useRef, useState } from "react";

export const ROUTES = [
  { id: "studio", label: "创作台", hint: "提示词、参考图与生成" },
  { id: "models", label: "模型与密钥", hint: "接入厂商，管理模型" },
  { id: "library", label: "参考库", hint: "姿势、服装、人物与上传素材" },
  { id: "gallery", label: "作品库", hint: "历史结果、收藏与复用" },
  { id: "records", label: "生成记录", hint: "模型、耗时与失败原因" },
  { id: "insights", label: "用量洞察", hint: "花费、成功率与渠道健康" },
  { id: "settings", label: "设置", hint: "默认模型与本地数据" },
] as const;

export type RouteId = (typeof ROUTES)[number]["id"];

function parseHash(): RouteId {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const found = ROUTES.find((route) => route.id === raw);
  return found ? found.id : "studio";
}

export function useHashRoute(): [RouteId, (route: RouteId) => void] {
  const [route, setRoute] = useState<RouteId>(parseHash);
  useEffect(() => {
    const onChange = () => setRoute(parseHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = useCallback((next: RouteId) => {
    window.location.hash = `#/${next}`;
    window.scrollTo({ top: 0 });
  }, []);
  return [route, navigate];
}

export function useInterval(callback: () => void, delay: number | null) {
  const saved = useRef(callback);
  useEffect(() => {
    saved.current = callback;
  }, [callback]);
  useEffect(() => {
    if (delay === null) return;
    const id = window.setInterval(() => saved.current(), delay);
    return () => window.clearInterval(id);
  }, [delay]);
}

export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore */
    }
  }, [key, value]);
  return [value, setValue] as const;
}

export function useEsc(handler: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") handler();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handler, active]);
}

export function useCopy() {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }, []);
  return { copied, copy };
}

export function formatRelative(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  if (Number.isNaN(then)) return "";
  if (diff < 45_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return new Date(then).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms) || ms < 0) return "0.00 秒";
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(2)} 秒`;
  }
  const minutes = Math.floor(ms / 60_000);
  const seconds = ((ms % 60_000) / 1000).toFixed(2);
  return `${minutes}分 ${seconds.padStart(5, "0")}秒`;
}

export function formatDurationMsCompact(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms) || ms < 0) return "0.00s";
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(2)}s`;
  }
  const minutes = Math.floor(ms / 60_000);
  const seconds = ((ms % 60_000) / 1000).toFixed(2);
  return `${minutes}m ${seconds.padStart(5, "0")}s`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (!ms) return "";
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function money(amount: number, currency = "CNY"): string {
  const symbol = currency === "CNY" ? "¥" : currency === "USD" ? "$" : `${currency} `;
  const value = Number.isFinite(amount) ? amount : 0;
  return `${symbol}${value.toFixed(value > 0 && value < 1 ? 3 : 2)}`;
}
