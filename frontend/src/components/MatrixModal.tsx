import { useEffect, useMemo, useState } from "react";
import { GitCompare, Loader2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Job, RefInput } from "../lib/types";
import { Badge, Button, Modal } from "./ui";

export interface MatrixBase {
  prompt: string;
  negative: string;
  params: Record<string, string | number>;
  refs: RefInput[];
  style: string;
}

export default function MatrixModal({
  open,
  onClose,
  base,
}: {
  open: boolean;
  onClose: () => void;
  base: MatrixBase;
}) {
  const { models, toast } = useStore();
  const [selected, setSelected] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);

  const candidates = useMemo(
    () => models.filter((model) => model.modality === "image" && model.available),
    [models],
  );

  useEffect(() => {
    if (!open) return;
    setJobs([]);
    setSelected((current) => {
      const valid = current.filter((id) => candidates.some((model) => model.id === id));
      if (valid.length) return valid.slice(0, 4);
      return candidates.slice(0, 2).map((model) => model.id);
    });
  }, [open, candidates]);

  useEffect(() => {
    const active = jobs.filter((job) => ["queued", "submitting", "running"].includes(job.status));
    if (!active.length) return;
    let alive = true;
    const timer = window.setInterval(async () => {
      try {
        const next = await Promise.all(active.map((job) => api.jobs.get(job.id)));
        if (alive) {
          setJobs((current) =>
            current.map((job) => next.find((item) => item.id === job.id) ?? job),
          );
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [jobs]);

  const toggle = (id: string) => {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : current.length >= 4
          ? current
          : [...current, id],
    );
  };

  const submit = async () => {
    if (!base.prompt.trim()) return toast("先写好提示词", "error");
    if (selected.length < 2) return toast("至少选择两个模型", "error");
    setBusy(true);
    try {
      const matrixId = crypto.randomUUID();
      const created: Job[] = [];
      for (const modelId of selected) {
        const result = await api.generate({
          ...base,
          model_id: modelId,
          count: 1,
          matrix_id: matrixId,
          source: "matrix",
        });
        created.push(await api.jobs.get(result.job_id));
      }
      setJobs(created);
      toast(`已提交 ${created.length} 个对比任务`, "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "提交失败", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="批量矩阵"
      subtitle="同一提示词和参考，同时发给多个模型；结果按模型分列"
      onClose={onClose}
      width={960}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <span className="grow" />
          <Button variant="primary" icon={<GitCompare size={14} />} loading={busy} onClick={() => void submit()}>
            对比生成
          </Button>
        </>
      }
    >
      <div className="matrix-models">
        {candidates.length === 0 && <p className="hint-block">没有可用的图像模型。</p>}
        {candidates.map((model) => (
          <label key={model.id} className={`matrix-model ${selected.includes(model.id) ? "is-active" : ""}`}>
            <input
              type="checkbox"
              checked={selected.includes(model.id)}
              onChange={() => toggle(model.id)}
            />
            <span>
              <strong>{model.name}</strong>
              <em>{model.channel_name}</em>
            </span>
          </label>
        ))}
      </div>

      {jobs.length > 0 && (
        <div className="matrix-grid">
          {jobs.map((job) => (
            <div className="matrix-column" key={job.id}>
              <div className="matrix-head">
                <strong>{job.model_name}</strong>
                <Badge tone={job.status === "failed" ? "error" : job.status === "succeeded" ? "accent" : "neutral"}>
                  {job.status === "succeeded"
                    ? "完成"
                    : job.status === "failed"
                      ? "失败"
                      : job.status === "canceled"
                        ? "取消"
                        : "生成中"}
                </Badge>
              </div>
              {["queued", "submitting", "running"].includes(job.status) && (
                <div className="matrix-loading">
                  <Loader2 size={16} className="spin" />
                  <span>{job.stage || "排队中"}</span>
                </div>
              )}
              {job.error && <p className="tool-error">{job.error}</p>}
              <div className="matrix-results">
                {job.assets.map((asset) => (
                  <a key={asset.id} href={asset.url} target="_blank" rel="noreferrer">
                    <img src={asset.thumb_url} alt="" loading="lazy" />
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
