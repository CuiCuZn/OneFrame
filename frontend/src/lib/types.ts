export type Modality = "image" | "video";

export interface KeyInfo {
  id: string;
  label: string;
  masked: string;
  enabled: boolean;
  status: "ok" | "error" | "untested";
  cooldown_until: string | null;
  fail_count: number;
  ok_count: number;
  last_used_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface Channel {
  id: string;
  name: string;
  protocol: string;
  protocol_label: string;
  base_url: string;
  headers: Record<string, string>;
  note: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  key_count: number;
  healthy_keys: number;
  keys: KeyInfo[];
  models_count: number;
}

export interface Caps {
  max_refs: number;
  max_count: number;
  features: string[];
  sizes: string[];
  aspects: string[];
}

export interface Price {
  mode: "unconfigured" | "per_image" | "per_request" | "per_second";
  amount: number;
  currency: string;
}

export interface Model {
  id: string;
  name: string;
  modality: Modality;
  channel_id: string;
  channel_name: string;
  protocol: string;
  upstream_model: string;
  description: string;
  enabled: boolean;
  caps: Caps;
  params: Record<string, string[]>;
  price: Price;
  overrides: Record<string, unknown>;
  available: boolean;
  reason: string;
  created_at: string;
  updated_at: string;
}

export interface JobAsset {
  id: string;
  kind: Modality;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  bytes: number | null;
  favorite: number | boolean;
  tags: string;
  prompt?: string;
  negative?: string;
  model_name?: string;
  params?: Record<string, unknown>;
  created_at?: string;
  url: string;
  thumb_url: string;
  download_url?: string;
}

export interface Attempt {
  at: string;
  phase: string;
  route?: string;
  channel?: string;
  message?: string;
  kind?: string;
  model?: string;
  key?: string;
  assets?: number;
}

export interface Job {
  id: string;
  model_id: string;
  model_name: string;
  channel_id?: string;
  channel_name?: string;
  modality: Modality;
  status: "queued" | "submitting" | "running" | "succeeded" | "failed" | "canceled" | "uncertain";
  stage: string;
  progress: number;
  error: string | null;
  price: number;
  currency: string;
  external_url: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  prompt: string;
  canceled: boolean;
  assets: JobAsset[];
  asset_count: number;
  request?: GenerateRequest & { model_name?: string; modality?: Modality };
  attempts?: Attempt[];
}

export interface Asset {
  id: string;
  kind: Modality;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  bytes: number | null;
  prompt: string;
  negative: string;
  model_id: string | null;
  model_name: string;
  params: Record<string, unknown>;
  favorite: boolean;
  tags: string;
  origin: "generated" | "upload";
  job_id: string | null;
  created_at: string;
  meta: Record<string, unknown>;
  url: string;
  thumb_url: string;
  download_url: string;
}

export interface LibraryItem {
  id: string;
  source: string;
  external_id: string | null;
  kind: string;
  title: string;
  subtitle: string;
  category: string;
  category_path: string;
  tags: string;
  image_path: string;
  thumb_path: string | null;
  width: number | null;
  height: number | null;
  favorite: number;
  nsfw: number;
  meta: Record<string, unknown>;
  facets: Record<string, string[]>;
  created_at: string;
  url: string;
  thumb_url: string;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface LibraryTreeNode {
  value: string;
  count: number;
  children: FacetValue[];
}

export interface LibraryTree {
  kind: string;
  label: string;
  count: number;
  fields: { level1: string; level2: string };
  children: LibraryTreeNode[];
}

export interface LibraryDim {
  field: string;
  values: FacetValue[];
}

export interface LibraryFacets {
  kinds: { kind: string; label: string; count: number }[];
  tree: LibraryTree[];
  dims: LibraryDim[];
  total: number;
  grand_total: number;
  visible_total: number;
  favorite: number;
  nsfw_hidden: number;
  roots: string[];
}

export interface ProtocolDoc {
  id: string;
  label: string;
  modalities: string[];
  supports_reference: boolean;
  supports_video: boolean;
  params: string[];
  about: string;
  base_url?: string;
  key_hint?: string;
  docs?: string;
  template?: Record<string, unknown>;
}

export interface StylePreset {
  id: string;
  name: string;
  zh: string;
  en: string;
}

export interface Catalog {
  protocols: ProtocolDoc[];
  styles: StylePreset[];
  sizes: string[];
  aspects: string[];
  image_resolutions: string[];
  durations: number[];
  resolutions: string[];
  roles: { id: string; name: string; hint: string }[];
  features: Record<string, string>;
  defaults: { negative: string; image_model: string; video_model: string };
}

export interface RefInput {
  asset_id?: string;
  library_id?: string;
  role: string;
  name?: string;
}

export interface GenerateRequest {
  model_id: string;
  prompt: string;
  negative: string;
  count: number;
  params: Record<string, string | number>;
  refs: RefInput[];
  style?: string;
  source?: string;
}

export interface GenerateResult {
  job_id: string;
  estimate: { known: boolean; amount: number; min: number; max: number; currency: string; channel: string };
  modality: Modality;
  target: {
    model_id: string;
    model_name: string;
    modality: Modality;
    channel_id: string;
    channel_name: string;
    protocol: string;
    upstream_model: string;
  };
}

export interface Stats {
  assets: { total: number; by_kind: Record<string, number>; favorite: number };
  jobs: { total: number; today: number; succeeded: number; failed: number; success_rate: number };
  spend: { total: number; last_30d: number };
  series: { day: string; jobs: number; ok: number; spend: number }[];
  top_models: { model_name: string; count: number }[];
  channels: {
    id: string;
    name: string;
    protocol: string;
    keys: number;
    ok_keys: number;
    jobs: number;
    spend: number;
  }[];
  disk: { total: number; media: number };
}

export interface SystemInfo {
  name: string;
  version: string;
  data_dir: string;
  db_path: string;
  media_dir: string;
  free_bytes: number;
  total_bytes: number;
  data_bytes: number;
  media_bytes: number;
  ffmpeg: string;
  library_roots: string[];
  workers: { image: number; video: number };
}

export interface JobList {
  items: Job[];
  total: number;
}

export interface AssetList {
  items: Asset[];
  total: number;
}
