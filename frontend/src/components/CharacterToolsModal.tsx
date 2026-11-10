import { useEffect, useMemo, useState } from "react";
import { Loader2, UserRound } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Asset, Job, JobAsset } from "../lib/types";
import { Badge, Button, Modal, Segmented } from "./ui";

const VIEWS = [
  { id: "front", label: "正面" },
  { id: "three_quarter", label: "四分之三" },
  { id: "profile_left", label: "左侧面" },
  { id: "profile_right", label: "右侧面" },
  { id: "back", label: "背面" },
];

const EXPRESSIONS = [
  { id: "neutral", label: "平静" },
  { id: "happy", label: "微笑" },
  { id: "sad", label: "悲伤" },
  { id: "angry", label: "生气" },
  { id: "surprised", label: "惊讶" },
  { id: "serious", label: "严肃" },
];

export default function CharacterToolsModal({
  open,
  asset,
  onClose,
}: {
  open: boolean;
  asset: Asset | JobAsset | null;
  onClose: () => void;
}) {
  const { models, toast } = useStore();
  const [mode, setMode] = useState<"view" | "expression" | "sheet">("view");
  const [preset, setPreset] = useState("front");
  const [modelId, setModelId] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);

  const candidates = useMemo(
    () =>
      models.filter(
        (model) =>
          model.modality === "image" &&
          model.available &&
          model.caps.max_refs >= 1 &&
          model.protocol !== "mock",
      ),
    [models],
  );

  useEffect(() => {
    if (!open) return;
    setJob(null);
    setExtra("");
    setMode("view");
    setPreset("front");
    if (!modelId || !candidates.some((model) => model.id === modelId)) {
      setModelId(candidates[0]?.id ?? "");
    }
  }, [open, modelId, candidates]);

  useEffect(() => {
    if (!job || !["queued", "submitting", "running"].includes(job.status)) return;
    let alive = true;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.jobs.get(job.id);
        if (alive) setJob(next);
      } catch {
        /* keep polling */
      }
    }, 1200);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [job]);

  const submit = async () => {
    if (!asset) return;
    if (!modelId) return toast("先选择一个图像模型", "error");
    setBusy(true);
    try {
      const result = await api.generate({
        model_id: modelId,
        prompt: extra.trim(),
        negative: "",
        count: 1,
        params: {},
        refs: [{ asset_id: asset.id, role: "character", name: "角色源图" }],
        tool: "character",
        options: { mode, preset, source_asset_id: asset.id },
        source: "tool:character",
      });
      setJob(await api.jobs.get(result.job_id));
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "提交失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const running = job && ["queued", "submitting", "running"].includes(job.status);
  const result = job?.assets?.[0] ?? null;

  return (
    <Modal
      open={open}
      title="角色一致性工具"
      subtitle="基于同一张角色参考，生成不同视角、表情或角色设定集"
      onClose={onClose}
      width={780}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <span className="grow" />
          {!result && (
            <Button variant="primary" loading={busy || Boolean(running)} onClick={() => void submit()}>
              开始生成
            </Button>
          )}
        </>
      }
    >
      {!asset ? null : (
        <div className="tool-form-grid">
          <div className="tool-panel">
            <span className="tool-label">角色源图</span>
            <div className="tool-source">
              <img src={asset.url} alt="" />
            </div>
            <span className="tool-label">生成模式</span>
            <Segmented
              value={mode}
              onChange={(value) => {
                setMode(value);
                setPreset(value === "expression" ? "neutral" : "front");
              }}
              options={[
                { value: "view", label: "视角" },
                { value: "expression", label: "表情" },
                { value: "sheet", label: "设定集" },
              ]}
            />
            {mode !== "sheet" && (
              <div className="char-presets">
                {(mode === "view" ? VIEWS : EXPRESSIONS).map((item) => (
                  <button
                    key={item.id}
                    className={`chip ${preset === item.id ? "is-active" : ""}`}
                    onClick={() => setPreset(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="tool-panel">
            <span className="tool-label">补充要求（可选）</span>
            <textarea
              className="input"
              rows={4}
              value={extra}
              onChange={(event) => setExtra(event.target.value)}
              placeholder="例如：保持同一套服装，背景改成浅灰"
            />
            <span className="tool-label">使用模型</span>
            <select className="select" value={modelId} onChange={(event) => setModelId(event.target.value)}>
              {candidates.length === 0 && <option value="">没有支持参考图的可用模型</option>}
              {candidates.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} · {model.channel_name}
                </option>
              ))}
            </select>
            <div className="tool-hint">
              <UserRound size={14} /> 设定集会生成一张四视图角色表，可用「宫格拆分」拆成四张。
            </div>
            {job && (
              <div className="tool-job">
                <Badge tone={job.status === "failed" ? "error" : "neutral"}>
                  {job.status === "failed" ? "失败" : running ? "生成中" : "完成"}
                </Badge>
                <span>{job.stage}</span>
                {job.error && <p className="tool-error">{job.error}</p>}
              </div>
            )}
            {result && (
              <div className="tool-result">
                <img src={result.thumb_url} alt="" />
                <a className="btn btn-soft btn-sm" href={result.download_url ?? result.url}>
                  下载结果
                </a>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
