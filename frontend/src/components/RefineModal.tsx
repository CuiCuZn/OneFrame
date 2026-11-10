import { useEffect, useMemo, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Asset, Job, JobAsset } from "../lib/types";
import { Badge, Button, Modal } from "./ui";

export default function RefineModal({
  open,
  asset,
  onClose,
}: {
  open: boolean;
  asset: Asset | JobAsset | null;
  onClose: () => void;
}) {
  const { models, toast } = useStore();
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
        refs: [{ asset_id: asset.id, role: "reference", name: "源图" }],
        tool: "refine",
        options: { source_asset_id: asset.id },
        source: "tool:refine",
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
      title="精修"
      subtitle="保持人物、姿势、服装和构图，只提升细节、光影与清晰度"
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <span className="grow" />
          {!result && (
            <Button variant="primary" loading={busy || Boolean(running)} onClick={() => void submit()}>
              开始精修
            </Button>
          )}
        </>
      }
    >
      {!asset ? null : (
        <div className="tool-form-grid">
          <div className="tool-panel">
            <span className="tool-label">源图</span>
            <div className="tool-source">
              <img src={asset.url} alt="" />
            </div>
          </div>
          <div className="tool-panel">
            <span className="tool-label">补充要求（可选）</span>
            <textarea
              className="input"
              rows={4}
              value={extra}
              onChange={(event) => setExtra(event.target.value)}
              placeholder="例如：更有电影感，皮肤更自然，背景不要变"
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
                  下载精修结果
                </a>
                <span className="hint-block">
                  <Sparkles size={12} /> 精修结果已按版本血缘关联到源图
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
