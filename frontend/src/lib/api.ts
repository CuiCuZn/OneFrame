import type {
  Asset,
  AssetList,
  Caps,
  Catalog,
  Channel,
  GenerateRequest,
  GenerateResult,
  Job,
  JobList,
  LibraryFacets,
  LibraryItem,
  Model,
  Modality,
  Price,
  Stats,
  SystemInfo,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status = 0, code = "error") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    throw new ApiError("无法连接本地服务，请确认后端已启动", 0, "network");
  }
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    let code = "http_error";
    try {
      const payload = await response.json();
      message = payload.detail || message;
      code = payload.code || code;
    } catch {
      /* ignore */
    }
    throw new ApiError(message, response.status, code);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const put = (body: unknown): RequestInit => ({ ...json(body), method: "PUT" });
const patch = (body: unknown): RequestInit => ({ ...json(body), method: "PATCH" });

export const api = {
  catalog: () => request<Catalog>("/api/catalog"),

  channels: {
    list: () => request<Channel[]>("/api/channels"),
    create: (body: {
      name: string;
      protocol: string;
      base_url: string;
      note?: string;
      enabled?: boolean;
      headers?: Record<string, string>;
      keys?: { label: string; secret: string; enabled?: boolean }[];
    }) => request<Channel>("/api/channels", json(body)),
    update: (id: string, body: Record<string, unknown>) =>
      request<Channel>(`/api/channels/${id}`, put(body)),
    remove: (id: string) => request<{ ok: boolean }>(`/api/channels/${id}`, { method: "DELETE" }),
    addKey: (id: string, body: { label: string; secret: string; enabled?: boolean }) =>
      request(`/api/channels/${id}/keys`, json(body)),
    updateKey: (id: string, keyId: string, body: Record<string, unknown>) =>
      request(`/api/channels/${id}/keys/${keyId}`, put(body)),
    removeKey: (id: string, keyId: string) =>
      request(`/api/channels/${id}/keys/${keyId}`, { method: "DELETE" }),
    resetKey: (id: string, keyId: string) =>
      request(`/api/channels/${id}/keys/${keyId}/reset`, { method: "POST" }),
    test: (id: string) =>
      request<{ ok: boolean; message: string; models: string[] }>(`/api/channels/${id}/test`, {
        method: "POST",
      }),
    discover: (id: string) =>
      request<{ ok: boolean; message: string; models: string[] }>(`/api/channels/${id}/discover`, {
        method: "POST",
      }),
  },

  models: {
    list: () => request<Model[]>("/api/models"),
    create: (body: ModelPayload) => request<Model>("/api/models", json(body)),
    update: (id: string, body: ModelPayload) => request<Model>(`/api/models/${id}`, put(body)),
    remove: (id: string) => request<{ ok: boolean }>(`/api/models/${id}`, { method: "DELETE" }),
  },

  generate: (body: GenerateRequest) => request<GenerateResult>("/api/generate", json(body)),
  compilePrompt: (body: Record<string, unknown>) =>
    request<{ prompt: string; negative: string; refs: { index: number; role: string; title: string }[] }>(
      "/api/prompt/compile",
      json(body),
    ),

  jobs: {
    list: (params: { status?: string; modality?: string; q?: string; limit?: number; offset?: number } = {}) => {
      const query = new URLSearchParams();
      if (params.status) query.set("status", params.status);
      if (params.modality) query.set("modality", params.modality);
      if (params.q) query.set("q", params.q);
      query.set("limit", String(params.limit ?? 30));
      query.set("offset", String(params.offset ?? 0));
      return request<JobList>(`/api/jobs?${query.toString()}`);
    },
    get: (id: string) => request<Job>(`/api/jobs/${id}`),
    cancel: (id: string) => request<{ ok: boolean; message: string }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
    retry: (id: string) => request<{ ok: boolean }>(`/api/jobs/${id}/retry`, { method: "POST" }),
    remove: (id: string) => request<{ ok: boolean }>(`/api/jobs/${id}`, { method: "DELETE" }),
  },

  assets: {
    list: (params: { kind?: string; favorite?: boolean; q?: string; limit?: number; offset?: number } = {}) => {
      const query = new URLSearchParams();
      if (params.kind) query.set("kind", params.kind);
      if (params.favorite !== undefined) query.set("favorite", String(params.favorite));
      if (params.q) query.set("q", params.q);
      query.set("limit", String(params.limit ?? 40));
      query.set("offset", String(params.offset ?? 0));
      return request<AssetList>(`/api/assets?${query.toString()}`);
    },
    patch: (id: string, body: { favorite?: boolean; tags?: string }) =>
      request<Asset>(`/api/assets/${id}`, patch(body)),
    remove: (id: string) => request<{ ok: boolean }>(`/api/assets/${id}`, { method: "DELETE" }),
    draft: (id: string) => request<{ prompt: string; negative: string; model_id: string | null; params: Record<string, unknown>; refs: unknown[] }>(`/api/assets/${id}/draft`),
    upload: async (files: File[]) => {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      return request<{ items: Asset[] }>("/api/assets/upload", { method: "POST", body: form });
    },
  },

  library: {
    list: (params: {
      kind?: string;
      q?: string;
      category?: string;
      facets?: string[];
      favorite?: boolean;
      limit?: number;
      offset?: number;
    } = {}) => {
      const query = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === "" || value === false) return;
        if (key === "facets" && Array.isArray(value)) {
          value.forEach((facet) => query.append("facet", facet));
          return;
        }
        query.set(key, String(value));
      });
      return request<{ items: LibraryItem[]; total: number }>(`/api/library?${query.toString()}`);
    },
    facets: (params: { kind?: string; q?: string; favorite?: boolean; facets?: string[] } = {}) => {
      const query = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === "" || value === false) return;
        if (key === "facets" && Array.isArray(value)) {
          value.forEach((facet) => query.append("facet", facet));
          return;
        }
        query.set(key, String(value));
      });
      return request<LibraryFacets>(`/api/library/facets?${query.toString()}`);
    },
    reclassify: () => request<{ items: number; facets: number }>("/api/library/reclassify", { method: "POST" }),
    fromAsset: (assetId: string) =>
      request<{ item: LibraryItem; created: boolean }>(`/api/library/assets/${assetId}`, { method: "POST" }),
    import: (mode: "folder" | "pose_gallery", path: string, kind: string) =>
      request<{ added: number; scanned: number; root: string }>("/api/library/import", json({ mode, path, kind })),
    patch: (id: string, body: { favorite?: boolean; tags?: string }) =>
      request<LibraryItem>(`/api/library/${id}`, patch(body)),
    remove: (id: string) => request<{ ok: boolean }>(`/api/library/${id}`, { method: "DELETE" }),
    upload: async (files: File[], kind = "custom") => {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      return request<{ items: LibraryItem[] }>(`/api/library/upload?kind=${kind}`, {
        method: "POST",
        body: form,
      });
    },
  },

  stats: () => request<Stats>("/api/stats"),
  system: () => request<SystemInfo>("/api/system"),
  settings: {
    get: () => request<Record<string, string>>("/api/settings"),
    save: (values: Record<string, string>) => request<Record<string, string>>("/api/settings", put({ values })),
  },
};

export interface ModelPayload {
  name: string;
  modality: Modality;
  channel_id: string;
  upstream_model: string;
  description: string;
  enabled: boolean;
  caps: Caps;
  params: Record<string, string[]>;
  price: Price;
  overrides: Record<string, unknown>;
}
