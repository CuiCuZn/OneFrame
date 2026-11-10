import { useEffect, useMemo, useRef, useState } from "react";
import { Download, ImagePlus, Loader2, Shirt, Upload } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Asset, Job } from "../lib/types";
import { Badge, Button, Modal } from "./ui";

interface Props {
  open: boolean;
  onClose: () => void;
  onUse: (asset: Pick<Asset, "id" | "thumb_url" | "url" | "prompt">) => void;
}

export default function CostumeExtractModal({ open, onClose, onUse }: Props) {
  const { models, toast } = useStore();
  const [source, setSource] = useState<Asset | null>(null);
  const [modelId, setModelId] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

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

  const reset = () => {
    setSource(null);
    setExtra("");
    setJob(null);
    setBusy(false);
  };

  const uploadSource = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    try {
      const data = await api.assets.upload(Array.from(files).slice(0, 1));
      setSource(data.items[0] ?? null);
      setJob(null);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "上传失败", "error");
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    if (!source) return toast("先上传一张穿搭照片", "error");
    if (!modelId) return toast("先选择一个图像模型", "error");
    setBusy(true);
    try {
      const result = await api.generate({
        model_id: modelId,
        prompt: extra.trim(),
        negative: "",
        count: 1,
        params: { aspect_ratio: "1:1", resolution: "1K" },
        refs: [{ asset_id: source.id, role: "reference", name: "穿搭原图" }],
        tool: "extract_costume",
        options: { source_asset_id: source.id },
        source: "tool:extract_costume",
      });
      setJob(await api.jobs.get(result.job_id));
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "提交失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const saveToLibrary = async (assetId: string) => {
    try {
      const result = await api.library.fromAsset(assetId);
      toast(result.created ? "已存入参考库" : "已经在参考库里了", result.created ? "success" : "info");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "存入参考库失败", "error");
    }
  };

  const result = job?.assets?.[0] ?? null;
  const running = job && ["queued", "submitting", "running"].includes(job.status);

  return (
    <Modal
      open={open}
      title="从穿搭图提取服饰"
      subtitle="用当前可用的图像编辑模型，把人物身上的整套服装提取成白底单品图"
      onClose={() => {
        reset();
        onClose();
      }}
      width={720}
      footer={
        <>
          <Button variant="ghost" onClick={() => { reset(); onClose(); }}>
            关闭
          </Button>
          <span className="grow" />
          {!result && (
            <Button variant="primary" loading={busy || Boolean(running)} onClick={() => void submit()}>
              开始提取
            </Button>
          )}
        </>
      }
    >
      <div className="tool-form-grid">
        <div className="tool-panel">
          <span className="tool-label">穿搭照片</span>
          {source ? (
            <div className="tool-source">
              <img src={source.url} alt="" />
              <button className="btn btn-ghost btn-sm" onClick={() => setSource(null)}>
                换一张
              </button>
            </div>
          ) : (
            <label className="tool-drop">
              {uploading ? <Loader2 size={18} className="spin" /> : <Upload size={18} />}
              <span>上传一张带人物的穿搭图</span>
              <input
                ref={fileInput}
                type="file"
                accept="image/*"
                hidden
                onChange={(event) => void uploadSource(event.target.files)}
              />
            </label>
          )}
          <span className="tool-label">补充要求（可选）</span>
          <textarea
            className="input"
            rows={3}
            value={extra}
            onChange={(event) => setExtra(event.target.value)}
            placeholder="例如：只保留连衣裙和鞋，不要配饰"
          />
        </div>
        <div className="tool-panel">
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
            <Shirt size={14} /> 提取会发起一次真实的图像生成请求，费用以所选模型为准。
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
                <Download size={14} /> 下载
              </a>
              <Button
                variant="primary"
                size="sm"
                icon={<ImagePlus size={14} />}
                onClick={() => {
                  onUse({
                    id: result.id,
                    thumb_url: result.thumb_url,
                    url: result.url,
                    prompt: (result as Asset).prompt ?? "",
                  });
                  reset();
                  onClose();
                }}
              >
                用作服装参考
              </Button>
              <Button variant="ghost" size="sm" onClick={() => void saveToLibrary(result.id)}>
                存入参考库
              </Button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
