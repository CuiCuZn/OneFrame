import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArrowRight,
  BookOpen,
  Brush,
  Check,
  ChevronDown,
  Clipboard,
  Clapperboard,
  Clock,
  Combine,
  Download,
  Expand,
  GitCompare,
  Grid2X2,
  ImagePlus,
  Images,
  Link2,
  Loader2,
  Lock,
  Maximize2,
  Palette,
  Plus,
  RotateCcw,
  Shirt,
  Shuffle,
  Sparkles,
  Star,
  Trash2,
  Unlock,
  Upload,
  UserRound,
  Wand2,
  X,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import {
  formatDurationMs,
  formatRelative,
  money,
  useCopy,
  useInterval,
  usePersistentState,
} from "../lib/hooks";
import type {
  Asset,
  Catalog,
  Job,
  JobAsset,
  LibraryFacets,
  LibraryItem,
  LibraryTree,
  Model,
  RefInput,
} from "../lib/types";
import CompareModal, { type CompareSource } from "../components/CompareModal";
import CompositeRefModal from "../components/CompositeRefModal";
import CostumeExtractModal from "../components/CostumeExtractModal";
import CharacterToolsModal from "../components/CharacterToolsModal";
import GridSplitModal from "../components/GridSplitModal";
import InpaintModal from "../components/InpaintModal";
import MatrixModal from "../components/MatrixModal";
import PromptLibraryDrawer from "../components/PromptLibraryDrawer";
import EnhanceModal from "../components/EnhanceModal";
import RefineModal from "../components/RefineModal";
import VersionStrip from "../components/VersionStrip";
import { Badge, Button, EmptyState, IconButton, Modal, Segmented, Toggle } from "../components/ui";

interface Props {
  onGoModels: () => void;
}

interface RefSlot {
  key: string;
  role: string;
  name: string;
  thumb: string;
  asset_id?: string;
  library_id?: string;
  variant?: "base" | "depth";
  group_key?: string;
}

const ROLE_ORDER = ["character", "costume", "pose", "style", "reference"];
const ACTIVE_JOBS_KEY = "of.activeJobIds";

function refFullUrl(ref: RefSlot): string {
  if (ref.library_id) return `/api/library/${ref.library_id}/file`;
  if (ref.asset_id) return `/api/assets/${ref.asset_id}/file`;
  return ref.thumb;
}

export default function Studio({ onGoModels }: Props) {
  const { catalog, models, settings, toast } = useStore();
  const [modality, setModality] = usePersistentState<"image" | "video">("of.modality", "image");
  const [modelId, setModelId] = useState("");
  const [prompt, setPrompt] = usePersistentState("of.prompt", "");
  const [negative, setNegative] = usePersistentState("of.negative", "");
  const [negativeOpen, setNegativeOpen] = useState(false);
  const [style, setStyle] = usePersistentState("of.style", "none");
  const [count, setCount] = usePersistentState("of.count", 1);
  const [aspect, setAspect] = usePersistentState("of.aspect", "1:1");
  const [duration, setDuration] = usePersistentState("of.duration", "5");
  const [resolution, setResolution] = usePersistentState("of.resolution", "1K");
  const [videoResolution, setVideoResolution] = usePersistentState("of.vres", "720p");
  const [seed, setSeed] = useState("");
  const [refs, setRefs] = usePersistentState<RefSlot[]>("of.refs", []);
  const [recentOpen, setRecentOpen] = usePersistentState<boolean>("of.studioRecentOpen", true);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerRole, setPickerRole] = useState("character");
  const [submitting, setSubmitting] = useState(false);
  const [sessionAssets, setSessionAssets] = useState<JobAsset[]>([]);
  const [activeJobs, setActiveJobs] = useState<Job[]>([]);
  const [jobsRestored, setJobsRestored] = useState(false);
  const [recent, setRecent] = useState<Asset[]>([]);
  const [lightbox, setLightbox] = useState<JobAsset | Asset | null>(null);
  const [refPreview, setRefPreview] = useState<RefSlot | null>(null);
  const [compare, setCompare] = useState<{
    left: CompareSource;
    right: CompareSource;
    alternatives?: CompareSource[];
    mode: "fidelity" | "selection";
  } | null>(null);
  const [urlOpen, setUrlOpen] = useState(false);
  const [urlValue, setUrlValue] = useState("");
  const [urlBusy, setUrlBusy] = useState(false);
  const [costumeOpen, setCostumeOpen] = useState(false);
  const [compositeOpen, setCompositeOpen] = useState(false);
  const [locks, setLocks] = useState<Record<string, boolean>>({});
  const [randomBusy, setRandomBusy] = useState(false);
  const [matrixOpen, setMatrixOpen] = useState(false);
  const [inpaintAsset, setInpaintAsset] = useState<JobAsset | Asset | null>(null);
  const [refineAsset, setRefineAsset] = useState<JobAsset | Asset | null>(null);
  const [splitAsset, setSplitAsset] = useState<JobAsset | Asset | null>(null);
  const [characterAsset, setCharacterAsset] = useState<JobAsset | Asset | null>(null);
  const [promptLibraryOpen, setPromptLibraryOpen] = useState(false);
  const [enhanceOpen, setEnhanceOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const restoredJobs = useRef(false);

  const pool = useMemo(
    () => models.filter((model) => model.modality === modality),
    [models, modality],
  );
  const model = useMemo(
    () => pool.find((item) => item.id === modelId) ?? pool.find((item) => item.available) ?? pool[0],
    [pool, modelId],
  );
  const slots = catalog?.roles ?? [];
  const features = model?.caps.features ?? [];
  const showRefs = (model?.caps.max_refs ?? 0) > 0;
  const showNegative = features.includes("negative");
  const showSeed = features.includes("seed");
  const showCount = (model?.caps.max_count ?? 1) > 1;

  useEffect(() => {
    if (!pool.length) {
      setModelId("");
      return;
    }
    if (!pool.some((item) => item.id === modelId)) {
      const preferred = modality === "image" ? settings.default_image_model : settings.default_video_model;
      const next =
        pool.find((item) => item.id === preferred && item.available) ??
        pool.find((item) => item.available) ??
        pool[0];
      setModelId(next.id);
    }
  }, [pool, modelId, modality, settings.default_image_model, settings.default_video_model]);

  useEffect(() => {
    if (!model) return;
    const aspects = catalog?.aspects ?? ["1:1"];
    if (modality === "image" && !aspects.includes(aspect)) setAspect(aspects[0]);
    const imageRes = catalog?.image_resolutions ?? ["1K", "2K", "4K"];
    if (modality === "image" && !imageRes.includes(resolution)) setResolution(imageRes[0]);
    const durations = model.params.duration ?? [];
    if (durations.length && !durations.map(String).includes(String(duration))) {
      setDuration(String(durations[0]));
    }
    const videoRes = model.params.resolution ?? [];
    if (videoRes.length && !videoRes.includes(videoResolution)) setVideoResolution(videoRes[0]);
    if (count > model.caps.max_count) setCount(model.caps.max_count);
  }, [model, modality, catalog, aspect, resolution, duration, videoResolution, count, setAspect, setResolution, setDuration, setVideoResolution, setCount]);

  const loadRecent = useCallback(async () => {
    try {
      const data = await api.assets.list({ limit: 8 });
      setRecent(data.items);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void loadRecent();
  }, [loadRecent]);

  // Receiving a reference from the library page.
  useEffect(() => {
    const raw = window.localStorage.getItem("of.pendingRef");
    if (!raw) return;
    window.localStorage.removeItem("of.pendingRef");
    try {
      const parsed = JSON.parse(raw) as { item?: LibraryItem; role?: string; variant?: string } | LibraryItem;
      const item = "item" in parsed && parsed.item ? parsed.item : (parsed as LibraryItem);
      const role = ("role" in parsed && parsed.role) || "reference";
      const variant: "base" | "depth" =
        "variant" in parsed && parsed.variant === "depth" ? "depth" : "base";
      setRefs((current) => {
        if (current.some((ref) => ref.library_id === item.id && (ref.variant ?? "base") === variant)) return current;
        const next = [
          ...current.filter((ref) => ref.role !== role),
          {
            key: `lib-${item.id}-${variant}`,
            role,
            name: item.title || item.category || "参考素材",
            thumb:
              variant === "depth" && item.depth_thumb_url
                ? item.depth_thumb_url
                : item.thumb_url,
            library_id: item.id,
            variant,
            group_key: item.group_key,
          },
        ];
        return next.slice(-6);
      });
    } catch {
      /* ignore */
    }
  }, [setRefs, toast]);

  // Reusing a work from the gallery: restore prompt, params and (optionally) the reference.
  useEffect(() => {
    const raw = window.localStorage.getItem("of.pendingDraft");
    if (!raw) return;
    window.localStorage.removeItem("of.pendingDraft");
    try {
      const draft = JSON.parse(raw) as {
        prompt?: string;
        negative?: string;
        model_id?: string | null;
        params?: Record<string, unknown>;
        refs?: { asset_id?: string; role?: string; name?: string }[];
      };
      if (draft.prompt) setPrompt(draft.prompt);
      if (draft.negative) {
        setNegative(draft.negative);
        setNegativeOpen(true);
      }
      if (draft.model_id) {
        const target = models.find((item) => item.id === draft.model_id);
        if (target) {
          setModality(target.modality);
          setModelId(target.id);
        }
      }
      const params = draft.params ?? {};
      if (params.aspect_ratio) setAspect(String(params.aspect_ratio));
      if (params.duration) setDuration(String(params.duration));
      if (params.resolution) {
        const value = String(params.resolution);
        if (["1K", "2K", "4K"].includes(value)) setResolution(value);
        else setVideoResolution(value);
      }
      if (draft.refs?.length) {
        setRefs(
          draft.refs
            .filter((ref) => ref.asset_id)
            .map((ref) => ({
              key: `asset-${ref.asset_id}`,
              role: ref.role || "reference",
              name: ref.name || "上一版结果",
              thumb: `/api/assets/${ref.asset_id}/file?size=thumb`,
              asset_id: ref.asset_id,
            })),
        );
      }
      toast("已恢复上一次的参数", "success");
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep in-flight jobs across page switches: ids live in localStorage and are
  // re-fetched when the studio mounts again.
  useEffect(() => {
    if (restoredJobs.current) return;
    restoredJobs.current = true;
    let ids: string[] = [];
    try {
      const raw = JSON.parse(window.localStorage.getItem(ACTIVE_JOBS_KEY) || "[]");
      if (Array.isArray(raw)) ids = raw.filter((item): item is string => typeof item === "string");
    } catch {
      ids = [];
    }
    if (!ids.length) {
      setJobsRestored(true);
      return;
    }
    void Promise.all(
      ids.map(async (id) => {
        try {
          return await api.jobs.get(id);
        } catch {
          return null;
        }
      }),
    ).then((jobs) => {
      const valid = jobs.filter(Boolean) as Job[];
      if (!valid.length) return;
      const fresh = valid
        .filter((job) => job.status === "succeeded")
        .flatMap((job) => job.assets);
      if (fresh.length) {
        setSessionAssets((current) => {
          const known = new Set(current.map((asset) => asset.id));
          return [...fresh.filter((asset) => !known.has(asset.id)), ...current];
        });
      }
      setActiveJobs(valid.filter((job) => !isTerminal(job.status)));
    }).finally(() => setJobsRestored(true));
  }, []);

  useEffect(() => {
    if (!jobsRestored) return;
    const ids = activeJobs.filter((job) => !isTerminal(job.status)).map((job) => job.id);
    try {
      window.localStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify(ids));
    } catch {
      /* storage may be disabled */
    }
  }, [activeJobs, jobsRestored]);

  useEffect(() => {
    const element = promptRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 280)}px`;
  }, [prompt]);

  const activeIds = activeJobs.filter((job) => !isTerminal(job.status)).map((job) => job.id);
  const poll = useCallback(async () => {
    if (!activeIds.length) return;
    const results = await Promise.all(
      activeIds.map(async (id) => {
        try {
          return await api.jobs.get(id);
        } catch {
          return null;
        }
      }),
    );
    const updated = results.filter(Boolean) as Job[];
    if (!updated.length) return;
    setActiveJobs((current) =>
      current.map((job) => updated.find((item) => item.id === job.id) ?? job),
    );
    const finished = updated.filter((job) => isTerminal(job.status));
    if (finished.length) {
      const fresh = finished.flatMap((job) => job.assets);
      if (fresh.length) {
        setSessionAssets((current) => {
          const known = new Set(current.map((asset) => asset.id));
          return [...fresh.filter((asset) => !known.has(asset.id)), ...current];
        });
        void loadRecent();
      }
      for (const job of finished) {
        if (job.status === "failed") toast(job.error || "生成失败", "error");
        if (job.status === "succeeded") {
          toast(`生成完成 · ${job.asset_count} 个结果`, "success");
          window.setTimeout(() => {
            setActiveJobs((current) =>
              current.filter((item) => !(item.id === job.id && item.status === "succeeded")),
            );
          }, 6000);
        }
      }
    }
  }, [activeIds.join(","), loadRecent, toast]);

  useInterval(() => void poll(), activeIds.length ? 1200 : null);

  const estimate = useMemo(() => {
    if (!model) return { text: "—", hint: "" };
    const price = model.price;
    if (price.mode === "unconfigured") {
      return { text: "未配置价格", hint: "以上游账单为准" };
    }
    if (!price.amount) {
      return { text: "免费", hint: `${model.channel_name} · ${model.upstream_model}` };
    }
    const quantity =
      price.mode === "per_second"
        ? model.modality === "video"
          ? Number(duration)
          : 1
        : model.modality === "video"
          ? 1
          : showCount
            ? count
            : 1;
    return {
      text: money(price.amount * quantity, price.currency),
      hint: `${model.channel_name} · ${model.upstream_model}`,
    };
  }, [model, count, duration, showCount]);

  const params = useMemo(() => {
    const result: Record<string, string | number> = {};
    if (!model) return result;
    if (model.modality === "image") {
      result.aspect_ratio = aspect;
      result.resolution = resolution;
    } else {
      const allowed = model.params;
      if (allowed.duration?.length) result.duration = duration;
      if (allowed.resolution?.length) result.resolution = videoResolution;
      if (allowed.aspect_ratio?.length) result.aspect_ratio = aspect;
    }
    if (showSeed && seed.trim()) result.seed = Number(seed.trim()) || seed.trim();
    return result;
  }, [model, aspect, resolution, duration, videoResolution, seed, showSeed]);

  const addRef = (ref: RefSlot) => {
    setRefs((current) => [...current.filter((item) => item.role !== ref.role || ref.role === "reference"), ref].slice(-6));
  };

  const removeRef = (key: string) => setRefs((current) => current.filter((item) => item.key !== key));

  const changeRole = (key: string, role: string) => {
    setRefs((current) =>
      current.map((item) => (item.key === key ? { ...item, role } : item)),
    );
  };

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      try {
        const data = await api.assets.upload(files.slice(0, 4));
        const added: RefSlot[] = data.items.map((asset) => ({
          key: `asset-${asset.id}`,
          role: "reference",
          name: "上传参考",
          thumb: asset.thumb_url,
          asset_id: asset.id,
        }));
        setRefs((current) => [...current, ...added].slice(-6));
        toast(`已上传 ${added.length} 张参考图`, "success");
      } catch (error) {
        toast(error instanceof ApiError ? error.message : "上传失败", "error");
      }
    },
    [setRefs, toast],
  );

  const uploadRefs = (files: FileList | null) => {
    if (!files?.length) return;
    void uploadFiles(Array.from(files).slice(0, 4));
  };

  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      const files = Array.from(event.clipboardData?.items ?? [])
        .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter((file): file is File => Boolean(file));
      if (!files.length) return;
      event.preventDefault();
      void uploadFiles(files.slice(0, 4));
    };
    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, [uploadFiles]);

  const addAssetRef = (asset: Asset) => {
    setRefs((current) =>
      [
        ...current,
        {
          key: `asset-${asset.id}`,
          role: "reference",
          name: asset.prompt ? asset.prompt.slice(0, 40) : "参考图",
          thumb: asset.thumb_url,
          asset_id: asset.id,
        },
      ].slice(-6),
    );
  };

  const addExtractedCostume = (asset: Pick<Asset, "id" | "thumb_url" | "url" | "prompt">) => {
    setRefs((current) =>
      [
        ...current.filter((ref) => ref.role !== "costume"),
        {
          key: `asset-${asset.id}`,
          role: "costume",
          name: "提取服饰",
          thumb: asset.thumb_url,
          asset_id: asset.id,
        },
      ].slice(-6),
    );
    toast("已作为服装参考加入", "success");
  };

  const addComposite = (asset: Pick<Asset, "id" | "thumb_url" | "url" | "prompt">) => {
    setRefs((current) => {
      const entry: RefSlot = {
        key: `asset-${asset.id}`,
        role: "reference",
        name: "参考拼图",
        thumb: asset.thumb_url,
        asset_id: asset.id,
      };
      if ((model?.caps.max_refs ?? 1) <= 1) return [entry];
      return [...current, entry].slice(-6);
    });
  };

  const randomizeRefs = async () => {
    setRandomBusy(true);
    try {
      const targets = [
        { kind: "pose", role: "pose" },
        { kind: "costume", role: "costume" },
        { kind: "portrait", role: "character" },
      ];
      let next = [...refs];
      for (const target of targets) {
        if (locks[target.role]) continue;
        const item = await api.library.random({ kind: target.kind });
        next = [
          ...next.filter((ref) => ref.role !== target.role),
          {
            key: `lib-${item.id}-base`,
            role: target.role,
            name: item.title || item.category || "随机素材",
            thumb: item.thumb_url,
            library_id: item.id,
            variant: "base" as const,
            group_key: item.group_key,
          },
        ];
      }
      setRefs(next.slice(-6));
      toast("已随机搭配，锁定的槽位保持不变", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "随机搭配失败", "error");
    } finally {
      setRandomBusy(false);
    }
  };

  const changePose = async (asset: JobAsset | Asset) => {
    try {
      const data = await api.assets.refs(asset.id);
      const pose = data.items.find((item) => item.role === "pose" && item.source === "library");
      let picked: LibraryItem | null = null;
      if (pose) {
        const variants = await api.library.variants(pose.id);
        picked = variants.items.find((item) => item.id !== pose.id) ?? null;
      }
      if (!picked) {
        picked = await api.library.random({ kind: "pose", exclude: pose ? [pose.id] : [] });
      }
      if (!picked) {
        toast("没有找到可替换的姿势", "error");
        return;
      }
      setRefs((current) =>
        [
          ...current.filter((ref) => ref.role !== "pose"),
          {
            key: `lib-${picked!.id}-base`,
            role: "pose",
            name: picked!.title || picked!.category || "随机姿势",
            thumb: picked!.thumb_url,
            library_id: picked!.id,
            variant: "base" as const,
            group_key: picked!.group_key,
          },
        ].slice(-6),
      );
      toast("已换一个姿势，其他参考和参数保持不变", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "换姿势失败", "error");
    }
  };

  const upscaleAsset = async (asset: JobAsset | Asset) => {
    if (!window.confirm("本地放大只提升分辨率，不会补充 AI 细节。继续放大 2 倍？")) return;
    try {
      const result = await api.assets.upscale(asset.id, 2);
      setLightbox(result);
      toast("已生成 2x 放大版本", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "放大失败", "error");
    }
  };

  const importUrl = async () => {
    const value = urlValue.trim();
    if (!value) return toast("先填写图片地址", "error");
    setUrlBusy(true);
    try {
      const asset = await api.assets.importUrl(value);
      addAssetRef(asset);
      setUrlOpen(false);
      setUrlValue("");
      toast("已从 URL 添加参考图", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "导入失败", "error");
    } finally {
      setUrlBusy(false);
    }
  };

  const compareAsset = async (asset: JobAsset | Asset) => {
    if (asset.kind !== "image") {
      toast("视频暂不支持对比", "error");
      return;
    }
    try {
      const data = await api.assets.refs(asset.id);
      const refs = data.items
        .filter((item) => !item.missing)
        .map((item) => ({
          url: item.url,
          label: `参考 · ${item.name || item.role}`,
          kind: "reference" as const,
          missing: item.missing,
        }));
      if (!refs.length) {
        toast("这条结果没有可用的参考图", "error");
        return;
      }
      setCompare({
        left: { url: asset.url, label: "生成结果", kind: "generated" },
        right: refs[0],
        alternatives: refs,
        mode: "fidelity",
      });
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "读取参考图失败", "error");
    }
  };

  const compilePrompt = async () => {
    if (!refs.length) {
      toast("先添加参考图，再编排提示词");
      return;
    }
    try {
      const result = await api.compilePrompt({
        refs: refs.map((ref) => ({ role: ref.role, title: ref.name })),
        style,
        extra: prompt,
        language: settings.prompt_language === "en" ? "en" : "zh",
        quality: true,
        negative,
      });
      setPrompt(result.prompt);
      if (showNegative && result.negative && !negative) setNegative(result.negative);
      promptRef.current?.focus();
      toast("已按参考图编排提示词", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "编排失败", "error");
    }
  };

  const submit = async () => {
    if (!model) {
      toast("请先在「模型与密钥」接入一个模型", "error");
      return;
    }
    if (!model.available) {
      toast("该模型当前不可用，请检查渠道与密钥", "error");
      return;
    }
    if (!prompt.trim()) {
      promptRef.current?.focus();
      toast("先写下你想生成的画面");
      return;
    }
    setSubmitting(true);
    try {
      const refInputs: RefInput[] = refs.map((ref) => ({
        role: ref.role,
        name: ref.name,
        ...(ref.asset_id ? { asset_id: ref.asset_id } : {}),
        ...(ref.library_id ? { library_id: ref.library_id } : {}),
        ...(ref.variant && ref.variant !== "base" ? { variant: ref.variant } : {}),
      }));
      const result = await api.generate({
        model_id: model.id,
        prompt: prompt.trim(),
        negative: showNegative ? negative.trim() : "",
        count: model.modality === "video" || !showCount ? 1 : count,
        params,
        refs: showRefs ? refInputs : [],
        style,
      });
      const job = await api.jobs.get(result.job_id);
      // Persist right away: the user may leave this page before React flushes.
      try {
        const saved = JSON.parse(window.localStorage.getItem(ACTIVE_JOBS_KEY) || "[]") as string[];
        if (!saved.includes(job.id)) {
          window.localStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify([...saved, job.id]));
        }
      } catch {
        /* ignore */
      }
      setActiveJobs((current) => [job, ...current].slice(0, 6));
      toast(`已进入队列 · ${result.target?.channel_name ?? ""}`, "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "提交失败", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const cancelJob = async (id: string) => {
    try {
      const result = await api.jobs.cancel(id);
      toast(result.message);
      const job = await api.jobs.get(id);
      setActiveJobs((current) => current.map((item) => (item.id === id ? job : item)));
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "取消失败", "error");
    }
  };

  const retryJob = async (id: string) => {
    try {
      await api.jobs.retry(id);
      const job = await api.jobs.get(id);
      setActiveJobs((current) => current.map((item) => (item.id === id ? job : item)));
      toast("已重新排队");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "重试失败", "error");
    }
  };

  if (!catalog) return null;

  const availableModels = pool.filter((item) => item.available);
  const onlyMock = models.length > 0 && models.every((item) => item.protocol === "mock");

  return (
    <div className="studio">
      <section className="studio-main" style={{ position: "relative" }}>
        {onlyMock && (
          <div className="banner">
            <Sparkles size={18} style={{ color: "var(--accent)" }} />
            <div>
              <strong>现在用的是离线演示模型</strong>
              <p>接入你的第一个 API，就能在这里切换真实模型出图。</p>
            </div>
            <Button size="sm" variant="primary" onClick={onGoModels}>
              接入服务
            </Button>
          </div>
        )}

        {!pool.length && (
          <div className="panel">
            <EmptyState
              icon={<Sparkles size={20} />}
              title="还没有可用的创作模型"
              description="先在「模型与密钥」里接入一个 OpenAI 兼容、Gemini 或自定义接口，然后回来开始创作。"
              action={
                <Button variant="primary" onClick={onGoModels} icon={<ArrowRight size={15} />}>
                  去接入
                </Button>
              }
            />
          </div>
        )}

        {pool.length > 0 && (
          <div className="composer">
            <div className="composer-top">
              <Segmented
                size="sm"
                value={modality}
                onChange={(value) => setModality(value)}
                options={[
                  { value: "image", label: "图像" },
                  { value: "video", label: "视频" },
                ]}
              />
              <div className="model-select-wrap">
                <button className="model-select" onClick={() => setMenuOpen((open) => !open)}>
                  {modality === "video" ? <Clapperboard size={15} /> : <Sparkles size={15} />}
                  <span>{model?.name ?? "选择模型"}</span>
                  <ChevronDown size={14} style={{ color: "var(--faint)" }} />
                </button>
                {menuOpen && (
                  <>
                    <div className="model-menu">
                      {pool.map((item) => (
                        <button
                          key={item.id}
                          className={`model-option ${item.id === model?.id ? "is-active" : ""}`}
                          onClick={() => {
                            setModelId(item.id);
                            setMenuOpen(false);
                          }}
                        >
                          <div className="model-option-main">
                            <strong>{item.name}</strong>
                            <em>
                              {item.channel_name} · {item.upstream_model}
                            </em>
                          </div>
                          {item.available ? (
                            <Badge tone="ok" dot>
                              可用
                            </Badge>
                          ) : (
                            <Badge tone="error">不可用</Badge>
                          )}
                        </button>
                      ))}
                      <button
                        className="model-option"
                        onClick={() => {
                          setMenuOpen(false);
                          onGoModels();
                        }}
                      >
                        <div className="model-option-main">
                          <strong>管理模型…</strong>
                          <em>添加厂商、密钥与模型</em>
                        </div>
                        <Plus size={15} />
                      </button>
                    </div>
                    <div className="menu-scrim" onClick={() => setMenuOpen(false)} />
                  </>
                )}
              </div>
              {model && !model.available && <Badge tone="error">{model.reason || "不可用"}</Badge>}
              {model && model.available && availableModels.length > 0 && (
                <Badge tone="neutral">{model.channel_name}</Badge>
              )}
            </div>

            {showRefs && (
              <div className="composer-refs">
                <div className="composer-refs-head">
                  <div className="composer-refs-title">
                    <Images size={14} />
                    <span>参考图</span>
                    <span className="composer-refs-count">{refs.length}/{model?.caps.max_refs ?? 6}</span>
                  </div>
                  <div className="composer-refs-actions">
                    <Button
                      size="sm"
                      variant="outline"
                      icon={<Upload size={13} />}
                      onClick={() => fileInput.current?.click()}
                    >
                      上传
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      icon={<Images size={13} />}
                      onClick={() => setPickerOpen(true)}
                    >
                      参考库
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      icon={<Link2 size={13} />}
                      onClick={() => setUrlOpen(true)}
                      title="从图片 URL 添加参考"
                    >
                      URL
                    </Button>
                    {modality === "image" && (
                      <Button
                        size="sm"
                        variant="outline"
                        icon={<Shirt size={13} />}
                        onClick={() => setCostumeOpen(true)}
                        title="从穿搭照片提取服装单品"
                      >
                        提取服饰
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      icon={<Combine size={13} />}
                      onClick={() => setCompositeOpen(true)}
                      disabled={refs.length < 2}
                      title="把多张参考合成一张"
                    >
                      合成参考
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      icon={<Shuffle size={13} />}
                      onClick={() => void randomizeRefs()}
                      loading={randomBusy}
                      title="随机搭配姿势、服装、人像；锁定的槽位不变"
                    >
                      随机搭配
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Wand2 size={13} />}
                      onClick={() => void compilePrompt()}
                      disabled={!refs.length}
                      title="给每张参考图指定角色并编排进提示词"
                    >
                      编排提示词
                    </Button>
                  </div>
                </div>

                <div className="composer-refs-body">
                  {refs.length === 0 ? (
                    <div
                      className="composer-refs-empty"
                      onClick={() => fileInput.current?.click()}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        if (e.dataTransfer.files?.length) {
                          void uploadRefs(e.dataTransfer.files);
                        }
                      }}
                    >
                      <ImagePlus size={16} style={{ color: "var(--faint)" }} />
                      <span>点击上传或拖入参考图，也可从参考库选择（支持指定人物、服装、姿势、风格）</span>
                    </div>
                  ) : (
                    <div className="composer-refs-list">
                      {refs.map((ref) => (
                        <div className="composer-ref-card" key={ref.key}>
                          <button
                            type="button"
                            className="ref-open"
                            title="查看大图"
                            onClick={() => setRefPreview(ref)}
                          >
                            <img className="ref-thumb" src={ref.thumb} alt={ref.name} loading="lazy" />
                          </button>
                          <div className="composer-ref-meta">
                            <select
                              className="ref-role"
                              value={ref.role}
                              onChange={(event) => changeRole(ref.key, event.target.value)}
                            >
                              {ROLE_ORDER.map((role) => (
                                <option key={role} value={role}>
                                  {slots.find((item) => item.id === role)?.name ?? role}
                                </option>
                              ))}
                            </select>
                            <span className="ref-name" title={ref.name}>{ref.name}</span>
                          </div>
                          <button
                            type="button"
                            className={`ref-lock ${locks[ref.role] ? "is-on" : ""}`}
                            onClick={() =>
                              setLocks((current) => ({ ...current, [ref.role]: !current[ref.role] }))
                            }
                            title={locks[ref.role] ? "解锁槽位" : "锁定槽位（随机搭配时不变）"}
                          >
                            {locks[ref.role] ? <Lock size={11} /> : <Unlock size={11} />}
                          </button>
                          <button
                            type="button"
                            className="composer-ref-remove"
                            onClick={() => removeRef(ref.key)}
                            title="移除"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ))}

                      {refs.length < (model?.caps.max_refs ?? 6) && (
                        <button
                          type="button"
                          className="composer-ref-add"
                          onClick={() => fileInput.current?.click()}
                          title="添加更多参考图"
                        >
                          <Plus size={14} />
                          <span>添加</span>
                        </button>
                      )}
                    </div>
                  )}
                </div>

                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(event) => void uploadRefs(event.target.files)}
                />
              </div>
            )}

            <textarea
              ref={promptRef}
              className="prompt-area"
              placeholder={
                modality === "video"
                  ? "描述镜头：主体、动作、环境、机位与运动方式…（Ctrl + Enter 生成）"
                  : "描述画面：主体、服装、光线、构图与氛围…（Ctrl + Enter 生成）"
              }
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.preventDefault();
                  void submit();
                }
              }}
              rows={3}
            />

            <div className="prompt-toolbar">
              <Button
                size="sm"
                variant="ghost"
                icon={<BookOpen size={13} />}
                onClick={() => setPromptLibraryOpen(true)}
              >
                提示词库
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon={<Sparkles size={13} />}
                onClick={() => setEnhanceOpen(true)}
                disabled={!prompt.trim()}
              >
                增强
              </Button>
            </div>

            {showNegative && negativeOpen && (
              <div className="negative-row">
                <textarea
                  className="textarea"
                  placeholder="反向提示词：不希望出现的元素"
                  value={negative}
                  onChange={(event) => setNegative(event.target.value)}
                />
              </div>
            )}

            <div className="composer-params">
              {modality === "image" ? (
                <>
                  <div className="composer-param-item">
                    <label className="composer-param-label">画幅</label>
                    <select
                      className="select composer-param-select"
                      value={aspect}
                      onChange={(event) => setAspect(event.target.value)}
                    >
                      {(catalog.aspects ?? ["1:1"]).map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="composer-param-item">
                    <label className="composer-param-label">清晰度</label>
                    <select
                      className="select composer-param-select"
                      value={resolution}
                      onChange={(event) => setResolution(event.target.value)}
                    >
                      {(catalog.image_resolutions ?? ["1K", "2K", "4K"]).map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </div>

                  {showCount && (
                    <div className="composer-param-item">
                      <label className="composer-param-label">数量</label>
                      <select
                        className="select composer-param-select"
                        value={count}
                        onChange={(event) => setCount(Number(event.target.value))}
                      >
                        {Array.from({ length: model?.caps.max_count ?? 4 }, (_, i) => i + 1).map((n) => (
                          <option key={n} value={n}>
                            {n} 张
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </>
              ) : (
                <>
                  {model?.params.duration?.length ? (
                    <div className="composer-param-item">
                      <label className="composer-param-label">时长</label>
                      <select
                        className="select composer-param-select"
                        value={String(duration)}
                        onChange={(event) => setDuration(event.target.value)}
                      >
                        {model.params.duration.map((value) => (
                          <option key={value} value={String(value)}>
                            {value} 秒
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : null}

                  {model?.params.resolution?.length ? (
                    <div className="composer-param-item">
                      <label className="composer-param-label">清晰度</label>
                      <select
                        className="select composer-param-select"
                        value={videoResolution}
                        onChange={(event) => setVideoResolution(event.target.value)}
                      >
                        {model.params.resolution.map((value) => (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : null}

                  {model?.params.aspect_ratio?.length ? (
                    <div className="composer-param-item">
                      <label className="composer-param-label">画幅</label>
                      <select
                        className="select composer-param-select"
                        value={aspect}
                        onChange={(event) => setAspect(event.target.value)}
                      >
                        {model.params.aspect_ratio.map((value) => (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : null}
                </>
              )}

              {showSeed && (
                <div className="composer-param-item">
                  <label className="composer-param-label">随机种子</label>
                  <div className="composer-param-seed-wrap">
                    <input
                      className="input composer-param-seed-input"
                      placeholder="留空随机"
                      value={seed}
                      onChange={(event) => setSeed(event.target.value.replace(/[^0-9]/g, ""))}
                    />
                    {seed && (
                      <button
                        type="button"
                        className="composer-param-seed-clear"
                        title="重置种子"
                        onClick={() => setSeed("")}
                      >
                        <RotateCcw size={12} />
                      </button>
                    )}
                  </div>
                </div>
              )}

              {(features.length > 0 || (model?.caps.max_refs ?? 0) > 0) && (
                <div className="composer-param-badges">
                  {features.map((feature) => (
                    <Badge key={feature} tone="neutral">
                      {catalog.features[feature] ?? feature}
                    </Badge>
                  ))}
                  {(model?.caps.max_refs ?? 0) > 0 && (
                    <Badge tone="neutral">参考 ≤ {model?.caps.max_refs}</Badge>
                  )}
                </div>
              )}
            </div>

            <div className="composer-tools">
              <span className="composer-tools-label">
                <Palette size={13} style={{ opacity: 0.7 }} />
                <span>预设风格</span>
              </span>
              <div className="style-strip">
                {(catalog.styles ?? []).map((item) => (
                  <button
                    key={item.id}
                    className={`chip ${style === item.id ? "is-active" : ""}`}
                    onClick={() => setStyle(item.id)}
                    title={item.zh || "不加预设风格"}
                  >
                    {item.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="composer-foot">
              <div className="composer-meta">
                {showNegative && (
                  <button className="chip" onClick={() => setNegativeOpen((value) => !value)}>
                    {negativeOpen ? "收起反向词" : "反向词"}
                  </button>
                )}
                {showRefs && refs.length > 0 && (
                  <span>
                    {refs.length} 张参考 · {refs.map((ref) => slots.find((r) => r.id === ref.role)?.name).join(" / ")}
                  </span>
                )}
              </div>
              <div className="row">
                <span className="cost">
                  预计 <strong>{estimate.text}</strong>
                </span>
                {modality === "image" && (
                  <Button
                    variant="soft"
                    size="lg"
                    icon={<GitCompare size={16} />}
                    disabled={!prompt.trim()}
                    onClick={() => setMatrixOpen(true)}
                    title="同一提示词发给多个模型，结果分列对比"
                  >
                    对比生成
                  </Button>
                )}
                <Button
                  variant="primary"
                  size="lg"
                  icon={submitting ? undefined : <Sparkles size={16} />}
                  loading={submitting}
                  onClick={() => void submit()}
                >
                  {modality === "video" ? "生成视频" : "生成"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {activeJobs.length > 0 && (
          <div className="result-section" style={{ marginTop: 16 }}>
            <div className="section-bar">
              <h2>
                生成任务 <span className="count">{activeJobs.length}</span>
              </h2>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() =>
                  setActiveJobs((current) => current.filter((job) => !isTerminal(job.status)))
                }
              >
                清理已完成
              </button>
            </div>
            <div className="job-list">
              {activeJobs.map((job) => (
                <JobRow key={job.id} job={job} onCancel={cancelJob} onRetry={retryJob} />
              ))}
            </div>
          </div>
        )}

        <div className="result-section" style={{ marginTop: 16 }}>
          <div className="section-bar section-collapsible">
            <button
              type="button"
              className="section-collapse-btn"
              onClick={() => setRecentOpen((open) => !open)}
              title={recentOpen ? "点击折叠隐藏" : "点击展开显示"}
            >
              <ChevronDown
                size={16}
                className={`collapse-chevron ${recentOpen ? "is-open" : ""}`}
              />
              <h2>
                {sessionAssets.length ? "本次结果" : "最近作品"}
                <span className="count">{sessionAssets.length || recent.length}</span>
              </h2>
            </button>
            <div className="row" style={{ gap: 8 }}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setRecentOpen((open) => !open)}
              >
                {recentOpen ? "收起" : "展开"}
              </button>
              <a className="btn btn-ghost btn-sm" href="#/gallery">
                作品库 <ArrowRight size={14} />
              </a>
            </div>
          </div>
          {recentOpen && (
            (sessionAssets.length ? sessionAssets : recent).length === 0 ? (
              <EmptyState
                compact
                icon={<ImagePlus size={18} />}
                title="还没有作品"
                description="写下第一句提示词，或者从参考图库挑一张姿势开始。"
              />
            ) : (
              <div className="result-grid">
                {(sessionAssets.length ? sessionAssets : recent).map((asset) => (
                  <ResultTile
                    key={asset.id}
                    asset={asset as JobAsset}
                    onOpen={() => setLightbox(asset as JobAsset)}
                    onFavorite={async () => {
                      await api.assets.patch(asset.id, { favorite: true });
                      toast("已收藏", "success");
                    }}
                  />
                ))}
              </div>
            )
          )}
        </div>
      </section>



      <RefPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        role={pickerRole}
        onRole={setPickerRole}
        onPick={(item, variant) => {
          const autoRole = (item.kind && ROLE_ORDER.includes(item.kind)) ? item.kind : pickerRole;
          addRef({
            key: `lib-${item.id}-${variant ?? "base"}`,
            role: autoRole,
            name: item.title || item.category || "参考素材",
            thumb:
              variant === "depth" && item.depth_thumb_url
                ? item.depth_thumb_url
                : item.thumb_url,
            library_id: item.id,
            variant: variant ?? "base",
            group_key: item.group_key,
          });
          setPickerOpen(false);
          toast(variant === "depth" ? "已加入深度图参考" : "已加入参考图", "success");
        }}
      />

      {refPreview && (
        <div className="lightbox" onClick={() => setRefPreview(null)}>
          <div className="lb-stage" onClick={(event) => event.stopPropagation()}>
            <button
              className="icon-btn lb-close"
              onClick={() => setRefPreview(null)}
              title="关闭"
            >
              <X size={18} />
            </button>
            <img src={refFullUrl(refPreview)} alt={refPreview.name} />
          </div>
          <aside className="lb-side" onClick={(event) => event.stopPropagation()}>
            <div>
              <h3>参考图</h3>
              <div className="kv">
                <b>用途</b>
                <span>{slots.find((item) => item.id === refPreview.role)?.name ?? refPreview.role}</span>
                <b>名称</b>
                <span>{refPreview.name || "—"}</span>
              </div>
            </div>
            <div className="lb-actions">
              <a className="btn btn-soft" href={refFullUrl(refPreview)} download>
                <Download size={15} /> 下载原图
              </a>
              <button
                className="btn btn-ghost"
                onClick={() => {
                  removeRef(refPreview.key);
                  setRefPreview(null);
                }}
              >
                <Trash2 size={15} /> 从参考图移除
              </button>
            </div>
          </aside>
        </div>
      )}

      <Lightbox
        asset={lightbox}
        onClose={() => setLightbox(null)}
        onCompare={(asset) => void compareAsset(asset)}
        onChangePose={(asset) => void changePose(asset)}
        onTool={(tool, asset) => {
          if (tool === "inpaint") setInpaintAsset(asset);
          else if (tool === "refine") setRefineAsset(asset);
          else if (tool === "split") setSplitAsset(asset);
          else setCharacterAsset(asset);
        }}
        onUpscale={(asset) => void upscaleAsset(asset)}
        onVersionSelect={(asset) => setLightbox(asset)}
        onVersionCompare={(asset) => {
          if (!lightbox) return;
          setCompare({
            left: { url: asset.url, label: `v${asset.version}`, kind: "asset" },
            right: { url: lightbox.url, label: "当前版本", kind: "asset" },
            mode: "selection",
          });
        }}
      />

      <InpaintModal open={Boolean(inpaintAsset)} asset={inpaintAsset} onClose={() => setInpaintAsset(null)} />
      <RefineModal open={Boolean(refineAsset)} asset={refineAsset} onClose={() => setRefineAsset(null)} />
      <GridSplitModal
        open={Boolean(splitAsset)}
        asset={splitAsset}
        onClose={() => setSplitAsset(null)}
      />
      <CharacterToolsModal
        open={Boolean(characterAsset)}
        asset={characterAsset}
        onClose={() => setCharacterAsset(null)}
      />

      <PromptLibraryDrawer
        open={promptLibraryOpen}
        onClose={() => setPromptLibraryOpen(false)}
        currentPrompt={prompt}
        onInsert={(text) => {
          setPrompt((current) => (current.trim() ? `${current}\n${text}` : text));
          setPromptLibraryOpen(false);
        }}
      />

      <EnhanceModal
        open={enhanceOpen}
        onClose={() => setEnhanceOpen(false)}
        prompt={prompt}
        negative={negative}
        style={style}
        modality={modality}
        hasRefs={refs.length > 0}
        onApply={(nextPrompt, nextNegative) => {
          setPrompt(nextPrompt);
          if (showNegative && nextNegative) setNegative(nextNegative);
        }}
      />

      <Modal
        open={urlOpen}
        title="从 URL 添加参考"
        subtitle="只支持 http/https 图片，单张不超过 25MB；内网地址会被拒绝"
        onClose={() => setUrlOpen(false)}
        width={520}
        footer={
          <>
            <Button variant="ghost" onClick={() => setUrlOpen(false)}>
              取消
            </Button>
            <Button variant="primary" loading={urlBusy} onClick={() => void importUrl()}>
              添加
            </Button>
          </>
        }
      >
        <input
          className="input"
          value={urlValue}
          onChange={(event) => setUrlValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void importUrl();
          }}
          placeholder="https://example.com/reference.png"
          autoFocus
        />
      </Modal>

      <CompositeRefModal
        open={compositeOpen}
        sources={refs.map((ref) => ({
          role: ref.role,
          label: slots.find((slot) => slot.id === ref.role)?.name ?? ref.role,
          url: refFullUrl(ref),
        }))}
        onClose={() => setCompositeOpen(false)}
        onUse={addComposite}
      />

      <MatrixModal
        open={matrixOpen}
        onClose={() => setMatrixOpen(false)}
        base={{
          prompt: prompt.trim(),
          negative: showNegative ? negative.trim() : "",
          params,
          refs: refs.map((ref) => ({
            role: ref.role,
            name: ref.name,
            ...(ref.asset_id ? { asset_id: ref.asset_id } : {}),
            ...(ref.library_id ? { library_id: ref.library_id } : {}),
            ...(ref.variant && ref.variant !== "base" ? { variant: ref.variant } : {}),
          })),
          style,
        }}
      />

      <CostumeExtractModal
        open={costumeOpen}
        onClose={() => setCostumeOpen(false)}
        onUse={addExtractedCostume}
      />

      <CompareModal
        open={Boolean(compare)}
        onClose={() => setCompare(null)}
        left={compare?.left ?? null}
        right={compare?.right ?? null}
        alternatives={compare?.alternatives}
        initialMode={compare?.mode === "fidelity" ? "overlay" : "side"}
      />
    </div>
  );
}

function isTerminal(status: string): boolean {
  return ["succeeded", "failed", "canceled", "uncertain"].includes(status);
}

function JobRow({
  job,
  onCancel,
  onRetry,
}: {
  job: Job;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const done = isTerminal(job.status);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (done) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 40);
    return () => window.clearInterval(timer);
  }, [done]);

  const elapsedMs = useMemo(() => {
    if (done) {
      if (job.duration_ms != null) return job.duration_ms;
      if (job.finished_at && (job.started_at || job.created_at)) {
        return Math.max(0, new Date(job.finished_at).getTime() - new Date(job.started_at || job.created_at).getTime());
      }
      return null;
    }
    const start = job.started_at || job.created_at;
    if (!start) return 0;
    return Math.max(0, now - new Date(start).getTime());
  }, [done, job.duration_ms, job.finished_at, job.started_at, job.created_at, now]);

  const attempts = (job.attempts ?? []).slice(-4).reverse();
  return (
    <div className="job-card">
      <div className="job-card-head">
        <span className={`job-dot ${job.status}`} />
        <span className="job-model" title={`${job.channel_name ? `${job.channel_name} · ` : ""}${job.model_name}`}>
          {job.channel_name && <span className="job-channel-badge">{job.channel_name}</span>}
          {job.model_name}
        </span>
        <Badge
          tone={
            job.status === "succeeded"
              ? "ok"
              : job.status === "failed" || job.status === "uncertain"
                ? "error"
                : "accent"
          }
        >
          {statusLabel(job.status)}
        </Badge>
        {!done ? (
          <span className="job-timer-badge running mono" title="生成中，实时耗时">
            <Clock size={11} className="spin-slow" />
            <span>{formatDurationMs(elapsedMs)}</span>
          </span>
        ) : elapsedMs != null ? (
          <span className="job-timer-badge done mono" title="生成总耗时">
            <span>耗时 {formatDurationMs(elapsedMs)}</span>
          </span>
        ) : null}
        <span className="job-stage">{job.stage || formatRelative(job.created_at)}</span>
      </div>
      {!done && (
        <div className="job-bar">
          <i style={{ width: `${Math.max(6, Math.min(100, job.progress * 100))}%` }} />
        </div>
      )}
      {job.error && <p className="job-error">{job.error}</p>}
      <div className="job-actions">
        {!done ? (
          <button className="btn btn-ghost btn-sm" onClick={() => onCancel(job.id)}>
            取消
          </button>
        ) : job.status === "failed" || job.status === "uncertain" ? (
          <button className="btn btn-soft btn-sm" onClick={() => onRetry(job.id)}>
            重试
          </button>
        ) : null}
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen((value) => !value)}>
          {open ? "收起" : "详情"}
        </button>
      </div>
      {open && (
        <div className="job-attempts">
          {attempts.length === 0 && <span className="faint">还没有线路记录</span>}
          {attempts.map((attempt, index) => (
            <div className="job-attempt" key={`${attempt.at}-${index}`}>
              <em>{attempt.phase}</em>
              <span>
                {[attempt.channel, attempt.key, attempt.message].filter(Boolean).join(" · ") ||
                  attempt.model ||
                  "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function statusLabel(status: Job["status"]): string {
  return (
    {
      queued: "排队中",
      submitting: "提交中",
      running: "生成中",
      succeeded: "完成",
      failed: "失败",
      canceled: "已取消",
      uncertain: "待核对",
    } as const
  )[status];
}

function ResultTile({
  asset,
  onOpen,
  onFavorite,
}: {
  asset: JobAsset;
  onOpen: () => void;
  onFavorite: () => void;
}) {
  return (
    <div className={`tile ${asset.kind === "video" ? "is-video" : ""}`} onClick={onOpen}>
      <img src={asset.thumb_url} alt="" loading="lazy" />
      {asset.kind === "video" && (
        <div className="tile-play">
          <span>
            <Clapperboard size={18} />
          </span>
        </div>
      )}
      <div className="tile-overlay">
        <div className="tile-actions">
          <button
            className="tile-action"
            title="收藏"
            onClick={(event) => {
              event.stopPropagation();
              onFavorite();
            }}
          >
            <Star size={14} />
          </button>
          <a
            className="tile-action"
            title="下载"
            href={`/api/assets/${asset.id}/file?dl=1`}
            onClick={(event) => event.stopPropagation()}
          >
            <Download size={14} />
          </a>
          <button className="tile-action" title="查看" onClick={onOpen}>
            <Expand size={14} />
          </button>
        </div>
        <span className="tile-caption">
          {asset.width && asset.height ? `${asset.width} × ${asset.height}` : ""}
        </span>
      </div>
    </div>
  );
}

function RefPicker({
  open,
  onClose,
  role: _role,
  onRole: _onRole,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  role?: string;
  onRole?: (role: string) => void;
  onPick: (item: LibraryItem, variant?: "base" | "depth") => void;
}) {
  const { toast } = useStore();
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [facets, setFacets] = useState<LibraryFacets | null>(null);
  const [kind, setKind] = useState("");
  const [level1, setLevel1] = useState("");
  const [level2, setLevel2] = useState("");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialLoaded, setInitialLoaded] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 160);
    return () => clearTimeout(timer);
  }, [query]);

  const tree = facets?.tree.find((entry) => entry.kind === kind);
  const level1Node = tree?.children.find((entry) => entry.value === level1);
  const level1Field = tree?.fields.level1 ?? "";
  const level2Field = tree?.fields.level2 ?? "";

  useEffect(() => {
    if (!open) return;
    let alive = true;
    api.library
      .facets({ q: debouncedQuery })
      .then((data) => {
        if (alive) setFacets(data);
      })
      .catch(() => {
        /* the grid still works without facets */
      });
    return () => {
      alive = false;
    };
  }, [open, debouncedQuery]);

  useEffect(() => {
    if (!open) return;
    const filters: string[] = [];
    if (level1Field && level1) filters.push(`${level1Field}:${level1}`);
    if (level2Field && level2) filters.push(`${level2Field}:${level2}`);
    let alive = true;
    setLoading(true);
    api.library
      .list({ kind, q: debouncedQuery, facets: filters, limit: 60 })
      .then((data) => {
        if (alive) {
          setItems(data.items);
          setInitialLoaded(true);
        }
      })
      .catch(() => toast("参考库读取失败", "error"))
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open, kind, level1, level2, debouncedQuery, level1Field, level2Field, toast]);

  const pickKind = (value: string) => {
    setKind(value);
    setLevel1("");
    setLevel2("");
    if (gridRef.current) gridRef.current.scrollTop = 0;
  };

  const breadcrumb = [tree?.label, level1, level2].filter(Boolean).join(" · ");

  return (
    <Modal
      open={open}
      title="从参考库选择"
      subtitle={breadcrumb || "选中后自动带入创作台"}
      onClose={onClose}
      width={860}
    >
      <div className="picker-filter">
        <div className="picker-filter-row picker-filter-row-top">
          <span className="facet-label">类型</span>
          <div className="facet-values">
            <button className={`chip ${!kind ? "is-active" : ""}`} onClick={() => pickKind("")}>
              全部 {facets ? <span className="faint">{facets.total}</span> : null}
            </button>
            {(facets?.tree ?? []).map((entry) => (
              <button
                key={entry.kind}
                className={`chip ${kind === entry.kind ? "is-active" : ""}`}
                onClick={() => pickKind(entry.kind)}
              >
                {entry.label} <span className="faint">{entry.count}</span>
              </button>
            ))}
          </div>
          <div className="picker-search-wrap">
            <input
              className="input picker-search-input"
              placeholder="搜索素材"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>

        {tree && (
          <div className="picker-filter-row">
            <span className="facet-label">{level1Field}</span>
            <div className="facet-values">
              {tree.children.map((entry) => (
                <button
                  key={entry.value}
                  className={`chip ${level1 === entry.value ? "is-active" : ""}`}
                  onClick={() => {
                    setLevel1(level1 === entry.value ? "" : entry.value);
                    setLevel2("");
                    if (gridRef.current) gridRef.current.scrollTop = 0;
                  }}
                >
                  {entry.value} <span className="faint">{entry.count}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {level1Node && level1Node.children.length > 0 && (
          <div className="picker-filter-row">
            <span className="facet-label">{level2Field}</span>
            <div className="facet-values">
              {level1Node.children.map((entry) => (
                <button
                  key={entry.value}
                  className={`chip ${level2 === entry.value ? "is-active" : ""}`}
                  onClick={() => {
                    setLevel2(level2 === entry.value ? "" : entry.value);
                    if (gridRef.current) gridRef.current.scrollTop = 0;
                  }}
                >
                  {entry.value} <span className="faint">{entry.count}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="picker-body-wrap">
        {!initialLoaded && loading ? (
          <div className="loading-row picker-loading-placeholder">
            <Loader2 size={16} className="spin" /> 正在读取素材库…
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            compact
            icon={<Images size={18} />}
            title="没有匹配的素材"
            description="换个分类或关键词；也可以去「参考库」导入本地文件夹。"
          />
        ) : (
          <div
            ref={gridRef}
            className={`picker-grid ${loading ? "is-loading" : ""}`}
          >
            {items.map((item) => (
              <div className="picker-item-wrap" key={item.id}>
                <button className="picker-item" onClick={() => onPick(item)}>
                  <img src={item.thumb_url} alt="" loading="lazy" />
                  {Boolean(item.has_depth) && <span className="picker-depth-badge">深度</span>}
                  <span>{item.title || item.category_path || item.category}</span>
                </button>
                {Boolean(item.has_depth) && (
                  <button
                    type="button"
                    className="picker-depth-use"
                    title="以深度图作为参考"
                    onClick={() => onPick(item, "depth")}
                  >
                    用深度图
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {initialLoaded && loading && (
          <div className="picker-loading-badge">
            <Loader2 size={12} className="spin" />
            <span>加载中…</span>
          </div>
        )}
      </div>
    </Modal>
  );
}

function Lightbox({
  asset,
  onClose,
  onCompare,
  onChangePose,
  onTool,
  onUpscale,
  onVersionSelect,
  onVersionCompare,
}: {
  asset: JobAsset | Asset | null;
  onClose: () => void;
  onCompare: (asset: JobAsset | Asset) => void;
  onChangePose: (asset: JobAsset | Asset) => void;
  onTool: (tool: "inpaint" | "refine" | "split" | "character", asset: JobAsset | Asset) => void;
  onUpscale: (asset: JobAsset | Asset) => void;
  onVersionSelect: (asset: Asset) => void;
  onVersionCompare: (asset: Asset) => void;
}) {
  const { copied, copy } = useCopy();
  if (!asset) return null;
  const prompt = (asset as Asset).prompt;
  const negative = (asset as Asset).negative;
  const modelName = (asset as Asset).model_name;
  const createdAt = (asset as Asset).created_at;
  const params = ((asset as Asset).params ?? {}) as Record<string, unknown>;
  return (
    <div className="lightbox" onClick={onClose}>
      <div className="lb-stage" onClick={(event) => event.stopPropagation()}>
        <button className="icon-btn lb-close" onClick={onClose} title="关闭">
          <X size={18} />
        </button>
        {asset.kind === "video" ? (
          <video src={asset.url} controls autoPlay loop playsInline poster={asset.thumb_url} />
        ) : (
          <img src={asset.url} alt="" />
        )}
      </div>
      <aside className="lb-side" onClick={(event) => event.stopPropagation()}>
        <div>
          <h3>生成信息</h3>
          <div className="kv">
            <b>模型</b>
            <span>{modelName || "—"}</span>
            <b>尺寸</b>
            <span>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "—"}</span>
            <b>时间</b>
            <span>{formatRelative(createdAt ?? null)}</span>
            {params.aspect_ratio || params.resolution ? (
              <>
                <b>参数</b>
                <span>
                  {String(params.aspect_ratio ?? "")}
                  {params.aspect_ratio && params.resolution ? " · " : ""}
                  {String(params.resolution ?? "")}
                  {params.seed ? ` · seed ${params.seed}` : ""}
                </span>
              </>
            ) : null}
          </div>
        </div>
        {prompt && (
          <div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3>提示词</h3>
              <button className="btn btn-ghost btn-sm" onClick={() => void copy(prompt)}>
                {copied ? <Check size={13} /> : <Clipboard size={13} />}
                {copied ? "已复制" : "复制"}
              </button>
            </div>
            <div className="lb-prompt">{prompt}</div>
          </div>
        )}
        {negative && (
          <div>
            <h3>反向词</h3>
            <div className="lb-prompt">{negative}</div>
          </div>
        )}
        <div className="lb-actions">
          <a className="btn btn-soft" href={`/api/assets/${asset.id}/file?dl=1`}>
            <Download size={15} /> 下载原文件
          </a>
          <button
            className="btn btn-ghost"
            onClick={async () => {
              await api.assets.patch(asset.id, { favorite: true });
            }}
          >
            <Star size={15} /> 收藏
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              window.localStorage.setItem(
                "of.pendingDraft",
                JSON.stringify({
                  prompt,
                  negative,
                  model_id: (asset as Asset).model_id,
                  params,
                  refs: [],
                }),
              );
              window.location.hash = "#/studio";
              onClose();
            }}
          >
            <Wand2 size={15} /> 复用参数
          </button>
          {asset.kind === "image" && (
            <button className="btn btn-ghost" onClick={() => onCompare(asset)}>
              <GitCompare size={15} /> 对比参考
            </button>
          )}
          {asset.kind === "image" && (
            <button className="btn btn-ghost" onClick={() => onChangePose(asset)}>
              <Shuffle size={15} /> 换个姿势
            </button>
          )}
          {asset.kind === "image" && (
            <a className="btn btn-ghost" href={api.assets.referenceZipUrl(asset.id)}>
              <Archive size={15} /> 参考图 ZIP
            </a>
          )}
          {asset.kind === "image" && (
            <>
              <button className="btn btn-soft" onClick={() => onTool("inpaint", asset)}>
                <Brush size={15} /> 局部重绘
              </button>
              <button className="btn btn-soft" onClick={() => onTool("refine", asset)}>
                <Sparkles size={15} /> 精修
              </button>
              <button className="btn btn-ghost" onClick={() => onUpscale(asset)}>
                <Maximize2 size={15} /> 本地放大 2x
              </button>
              <button className="btn btn-ghost" onClick={() => onTool("split", asset)}>
                <Grid2X2 size={15} /> 宫格拆分
              </button>
              <button className="btn btn-ghost" onClick={() => onTool("character", asset)}>
                <UserRound size={15} /> 角色工具
              </button>
            </>
          )}
          {asset.kind === "image" && (
            <VersionStrip
              assetId={asset.id}
              currentId={asset.id}
              onSelect={onVersionSelect}
              onCompare={onVersionCompare}
            />
          )}
        </div>
      </aside>
    </div>
  );
}
export function useModelDefaults(catalog: Catalog | null, models: Model[]) {
  return { catalog, models };
}




