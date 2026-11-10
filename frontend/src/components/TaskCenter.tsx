import { useCallback, useEffect, useMemo, useState } from "react";
import { Ban, ExternalLink, ListTodo, Loader2, RefreshCw } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { formatRelative, money } from "../lib/hooks";
import { useStore } from "../lib/store";
import type { Job } from "../lib/types";
import { Badge, Button, EmptyState, Modal } from "./ui";

const ACTIVE = new Set(["queued", "submitting", "running"]);
const STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  submitting: "提交中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  canceled: "已取消",
  uncertain: "待核对",
};

function elapsed(job: Job): string {
  const start = job.started_at || job.created_at;
  const end = job.finished_at || new Date().toISOString();
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export default function TaskCenter({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { toast } = useStore();
  const [active, setActive] = useState<Job[]>([]);
  const [recent, setRecent] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [live, latest] = await Promise.all([
        api.jobs.list({ status: "active", limit: 50 }),
        api.jobs.list({ limit: 10 }),
      ]);
      setActive(live.items);
      setRecent(latest.items.filter((job) => !ACTIVE.has(job.status)).slice(0, 8));
    } catch (error) {
      if (open) toast(error instanceof ApiError ? error.message : "任务读取失败", "error");
    }
  }, [open, toast]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    void refresh().finally(() => setLoading(false));
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [open, refresh]);

  const cancel = async (job: Job) => {
    setBusyId(job.id);
    try {
      const result = await api.jobs.cancel(job.id);
      toast(result.message);
      await refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "取消失败", "error");
    } finally {
      setBusyId("");
    }
  };

  const activeCount = useMemo(() => active.length, [active]);

  return (
    <Modal
      open={open}
      title="任务中心"
      subtitle={activeCount ? `${activeCount} 个任务进行中` : "当前没有进行中的任务"}
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="ghost" icon={<RefreshCw size={14} />} loading={loading} onClick={() => void refresh()}>
            刷新
          </Button>
          <span className="grow" />
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
        </>
      }
    >
      <div className="task-section-title">进行中</div>
      {active.length === 0 ? (
        <EmptyState compact icon={<ListTodo size={18} />} title="没有进行中的任务" description="提交生成后，进度会在这里跨页面持续显示。" />
      ) : (
        <div className="task-list">
          {active.map((job) => (
            <div className="task-row" key={job.id}>
              <div className="task-main">
                <div className="task-title">
                  <strong>{job.model_name || "未命名模型"}</strong>
                  <Badge tone="neutral">{job.modality === "video" ? "视频" : "图像"}</Badge>
                  <span>{STATUS_LABEL[job.status] ?? job.status}</span>
                </div>
                <div className="task-meta">
                  <span>{job.channel_name || "—"}</span>
                  <span>{job.stage || "—"}</span>
                  <span>{elapsed(job)}</span>
                  {job.price ? <span>{money(job.price, job.currency)}</span> : null}
                </div>
                <div className="task-progress">
                  <i style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                icon={busyId === job.id ? <Loader2 size={13} className="spin" /> : <Ban size={13} />}
                loading={busyId === job.id}
                onClick={() => void cancel(job)}
              >
                取消
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="task-section-title">最近任务</div>
      {recent.length === 0 ? (
        <p className="hint-block">还没有已结束的任务。</p>
      ) : (
        <div className="task-list">
          {recent.map((job) => (
            <div className="task-row is-done" key={job.id}>
              <div className="task-main">
                <div className="task-title">
                  <strong>{job.model_name || "未命名模型"}</strong>
                  <Badge tone={job.status === "failed" ? "error" : job.status === "succeeded" ? "accent" : "neutral"}>
                    {STATUS_LABEL[job.status] ?? job.status}
                  </Badge>
                  <span>{formatRelative(job.finished_at || job.created_at)}</span>
                </div>
                <div className="task-meta">
                  <span>{job.channel_name || "—"}</span>
                  <span>{job.prompt?.slice(0, 60) || "—"}</span>
                  {job.error ? <span className="task-error">{job.error}</span> : null}
                </div>
              </div>
              {job.assets.length > 0 ? (
                <div className="task-thumbs">
                  {job.assets.slice(0, 3).map((asset) => (
                    <a key={asset.id} href={asset.url} target="_blank" rel="noreferrer" title="查看结果">
                      <img src={asset.thumb_url} alt="" loading="lazy" />
                    </a>
                  ))}
                </div>
              ) : (
                <a className="btn btn-ghost btn-sm" href="#/records">
                  <ExternalLink size={13} /> 记录
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
