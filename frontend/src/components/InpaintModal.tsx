import { useEffect, useMemo, useRef, useState } from "react";
import { Eraser, Loader2, Paintbrush, RotateCcw, Undo2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Asset, Job, JobAsset } from "../lib/types";
import { Badge, Button, Modal } from "./ui";

type Stroke = { points: { x: number; y: number }[]; radius: number; erase: boolean };

interface Props {
  open: boolean;
  asset: Asset | JobAsset | null;
  onClose: () => void;
}

export default function InpaintModal({ open, asset, onClose }: Props) {
  const { models, toast } = useStore();
  const [modelId, setModelId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [brush, setBrush] = useState(42);
  const [erase, setErase] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [strokeCount, setStrokeCount] = useState(0);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const strokesRef = useRef<Stroke[]>([]);
  const currentRef = useRef<Stroke | null>(null);

  const candidates = useMemo(
    () =>
      models.filter(
        (model) =>
          model.modality === "image" &&
          model.available &&
          model.protocol === "openai_image" &&
          model.caps.features.includes("inpaint"),
      ),
    [models],
  );

  useEffect(() => {
    if (!open || !asset) return;
    if (!modelId || !candidates.some((model) => model.id === modelId)) {
      setModelId(candidates[0]?.id ?? "");
    }
  }, [open, asset, modelId, candidates]);

  useEffect(() => {
    if (!open || !asset) return;
    let alive = true;
    setReady(false);
    setJob(null);
    setPrompt("");
    setErase(false);
    strokesRef.current = [];
    currentRef.current = null;
    setStrokeCount(0);
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      if (!alive) return;
      const scale = Math.min(1, 2048 / Math.max(image.width, image.height));
      const width = Math.max(1, Math.round(image.width * scale));
      const height = Math.max(1, Math.round(image.height * scale));
      sizeRef.current = { width, height };
      const canvas = overlayRef.current;
      if (!canvas) return;
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (context) {
        context.clearRect(0, 0, width, height);
      }
      setReady(true);
    };
    image.onerror = () => {
      if (alive) toast("源图加载失败", "error");
    };
    image.src = asset.url;
    return () => {
      alive = false;
    };
  }, [open, asset, toast]);

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

  const render = () => {
    const canvas = overlayRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.lineCap = "round";
    context.lineJoin = "round";
    for (const stroke of strokesRef.current) {
      context.save();
      context.globalCompositeOperation = stroke.erase ? "destination-out" : "source-over";
      context.strokeStyle = stroke.erase ? "rgba(0,0,0,1)" : "rgba(255,70,70,0.45)";
      context.fillStyle = stroke.erase ? "rgba(0,0,0,1)" : "rgba(255,70,70,0.45)";
      context.lineWidth = stroke.radius * 2;
      const points = stroke.points;
      if (points.length === 1) {
        context.beginPath();
        context.arc(points[0].x, points[0].y, stroke.radius, 0, Math.PI * 2);
        context.fill();
      } else {
        context.beginPath();
        context.moveTo(points[0].x, points[0].y);
        for (const point of points.slice(1)) context.lineTo(point.x, point.y);
        context.stroke();
      }
      context.restore();
    }
  };

  const pointAt = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = overlayRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) * canvas.width) / rect.width,
      y: ((event.clientY - rect.top) * canvas.height) / rect.height,
    };
  };

  const start = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!ready) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const stroke: Stroke = { points: [pointAt(event)], radius: brush, erase };
    currentRef.current = stroke;
    strokesRef.current = [...strokesRef.current, stroke];
    render();
  };

  const move = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!currentRef.current) return;
    currentRef.current.points.push(pointAt(event));
    render();
  };

  const end = () => {
    if (!currentRef.current) return;
    currentRef.current = null;
    setStrokeCount(strokesRef.current.length);
  };

  const undo = () => {
    strokesRef.current = strokesRef.current.slice(0, -1);
    setStrokeCount(strokesRef.current.length);
    render();
  };

  const clear = () => {
    strokesRef.current = [];
    setStrokeCount(0);
    render();
  };

  const maskData = () => {
    const { width, height } = sizeRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) return "";
    context.fillStyle = "#fff";
    context.fillRect(0, 0, width, height);
    context.lineCap = "round";
    context.lineJoin = "round";
    for (const stroke of strokesRef.current) {
      context.save();
      context.globalCompositeOperation = stroke.erase ? "source-over" : "destination-out";
      context.strokeStyle = "#fff";
      context.fillStyle = "#fff";
      context.lineWidth = stroke.radius * 2;
      const points = stroke.points;
      if (points.length === 1) {
        context.beginPath();
        context.arc(points[0].x, points[0].y, stroke.radius, 0, Math.PI * 2);
        context.fill();
      } else {
        context.beginPath();
        context.moveTo(points[0].x, points[0].y);
        for (const point of points.slice(1)) context.lineTo(point.x, point.y);
        context.stroke();
      }
      context.restore();
    }
    return canvas.toDataURL("image/png");
  };

  const submit = async () => {
    if (!asset) return;
    if (!prompt.trim()) return toast("描述要修改的内容", "error");
    if (!modelId) return toast("先选择一个支持局部重绘的模型", "error");
    if (!strokesRef.current.some((stroke) => !stroke.erase)) return toast("先在图上涂抹要修改的区域", "error");
    setBusy(true);
    try {
      const result = await api.generate({
        model_id: modelId,
        prompt: prompt.trim(),
        negative: "",
        count: 1,
        params: {},
        refs: [{ asset_id: asset.id, role: "reference", name: "源图" }],
        tool: "inpaint",
        options: { source_asset_id: asset.id },
        mask: maskData(),
        source: "tool:inpaint",
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
      title="局部重绘"
      subtitle="涂抹要修改的区域，写下改成什么；只支持 OpenAI 兼容 /images/edits 模型"
      onClose={onClose}
      width={1000}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <span className="grow" />
          {!result && (
            <Button variant="primary" loading={busy || Boolean(running)} onClick={() => void submit()}>
              开始重绘
            </Button>
          )}
        </>
      }
    >
      {!asset ? null : (
        <div className="inpaint-layout">
          <div className="inpaint-stage">
            <img src={asset.url} alt="" className="inpaint-image" />
            <canvas
              ref={overlayRef}
              className="inpaint-overlay"
              onPointerDown={start}
              onPointerMove={move}
              onPointerUp={end}
              onPointerCancel={end}
            />
            {!ready && (
              <div className="inpaint-loading">
                <Loader2 size={16} className="spin" /> 读取源图…
              </div>
            )}
          </div>
          <div className="inpaint-side">
            <div className="inpaint-tools">
              <Button
                size="sm"
                variant={erase ? "soft" : "ghost"}
                icon={<Eraser size={14} />}
                onClick={() => setErase((value) => !value)}
              >
                橡皮
              </Button>
              <Button size="sm" variant="ghost" icon={<Paintbrush size={14} />} onClick={() => setErase(false)}>
                画笔
              </Button>
              <Button size="sm" variant="ghost" icon={<Undo2 size={14} />} onClick={undo} disabled={!strokeCount}>
                撤销
              </Button>
              <Button size="sm" variant="ghost" icon={<RotateCcw size={14} />} onClick={clear} disabled={!strokeCount}>
                清空
              </Button>
            </div>
            <label className="inpaint-range">
              笔刷 <input type="range" min={12} max={120} value={brush} onChange={(event) => setBrush(Number(event.target.value))} />
              <span>{brush}px</span>
            </label>
            <span className="tool-label">修改描述</span>
            <textarea
              className="input"
              rows={4}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="例如：把外套换成红色针织开衫，保持姿势和背景不变"
            />
            <span className="tool-label">使用模型</span>
            <select className="select" value={modelId} onChange={(event) => setModelId(event.target.value)}>
              {candidates.length === 0 && <option value="">没有开启局部重绘的模型</option>}
              {candidates.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} · {model.channel_name}
                </option>
              ))}
            </select>
            {candidates.length === 0 && (
              <p className="hint-block">
                请到「模型与密钥」编辑一个 OpenAI 兼容模型，勾选「局部重绘」能力。
              </p>
            )}
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
