import { useCallback, useEffect, useState } from "react";
import {
  History,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  XCircle,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import { formatDurationMs, formatRelative, useInterval } from "../lib/hooks";
import type { Job } from "../lib/types";
import {
  Badge,
  Button,
  Chip,
  EmptyState,
  Modal,
  PageHead,
} from "../components/ui";

const STATUS_LABEL: Record<Job["status"], string> = {
  queued: "排队中",
  submitting: "提交中",
  running: "生成中",
  succeeded: "成功",
  failed: "失败",
  canceled: "已取消",
  uncertain: "待核对",
};

const STATUS_TONE: Record<Job["status"], "ok" | "warn" | "error" | "accent" | "neutral"> = {
  queued: "neutral",
  submitting: "accent",
  running: "accent",
  succeeded: "ok",
  failed: "error",
  canceled: "neutral",
  uncertain: "warn",
};

const PAGE_SIZE = 30;

function isActive(status: Job["status"]): boolean {
  return status === "queued" || status === "submitting" || status === "running";
}

function elapsed(job: Job): string {
  const ms =
    job.duration_ms ??
    (job.started_at
      ? Math.max(0, Date.now() - new Date(job.started_at).getTime())
      : null);
  if (ms == null) return "—";
  if (ms < 1000) return "<1s";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function stamp(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export default function Records() {
  const { toast } = useStore();
  const [status, setStatus] = useState("");
  const [modality, setModality] = useState("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<Job | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);

  const load = useCallback(
    async (nextOffset = 0, silent = false) => {
      if (!silent) setLoading(true);
      try {
        const data = await api.jobs.list({
          status,
          modality,
          q: query,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setItems((current) => (nextOffset === 0 ? data.items : [...current, ...data.items]));
        setTotal(data.total);
        setOffset(nextOffset);
        setDetail((current) => {
          if (!current) return current;
          const row = data.items.find((job) => job.id === current.id);
          // Keep the detail-only fields (request/attempts) while refreshing status.
          return row ? { ...current, ...row, request: current.request, attempts: current.attempts } : current;
        });
      } catch (error) {
        if (!silent) {
          toast(error instanceof ApiError ? error.message : "读取生成记录失败", "error");
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [status, modality, query, toast],
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  useInterval(() => void load(0, true), 5000);

  const openDetail = async (job: Job) => {
    try {
      setDetail(await api.jobs.get(job.id));
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "读取任务详情失败", "error");
    }
  };

  const act = async (action: "cancel" | "retry" | "delete") => {
    if (!detail) return;
    setDetailBusy(true);
    try {
      if (action === "cancel") await api.jobs.cancel(detail.id);
      if (action === "retry") await api.jobs.retry(detail.id);
      if (action === "delete") await api.jobs.remove(detail.id);
      toast(
        action === "cancel" ? "已请求取消" : action === "retry" ? "已重新排队" : "记录已删除",
        "success",
      );
      if (action === "delete") setDetail(null);
      await load(0, true);
      if (action !== "delete") {
        setDetail(await api.jobs.get(detail.id).catch(() => null));
      }
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "操作失败", "error");
    } finally {
      setDetailBusy(false);
    }
  };

  const hasActive = items.some((job) => isActive(job.status));

  return (
    <>
      <PageHead
        eyebrow="Jobs"
        title="生成记录"
        description="每一次提交都在本地留档：模型、时间、耗时、价格、参数与失败原因；不只是成功的作品。"
        actions={
          <Button
            variant="soft"
            icon={<RefreshCw size={15} />}
            onClick={() => void load(0)}
          >
            刷新
          </Button>
        }
      />

      <div className="filter-bar">
        <Chip active={!status} onClick={() => setStatus("")}>
          全部 <span className="faint">{total}</span>
        </Chip>
        <Chip active={status === "active"} onClick={() => setStatus(status === "active" ? "" : "active")}>
          进行中
        </Chip>
        <Chip active={status === "succeeded"} onClick={() => setStatus(status === "succeeded" ? "" : "succeeded")}>
          成功
        </Chip>
        <Chip active={status === "failed"} onClick={() => setStatus(status === "failed" ? "" : "failed")}>
          失败
        </Chip>
        <Chip active={status === "canceled"} onClick={() => setStatus(status === "canceled" ? "" : "canceled")}>
          已取消
        </Chip>
        <Chip active={status === "uncertain"} onClick={() => setStatus(status === "uncertain" ? "" : "uncertain")}>
          待核对
        </Chip>
        <div className="spacer" />
        <Chip active={modality === "image"} onClick={() => setModality(modality === "image" ? "" : "image")}>
          图像
        </Chip>
        <Chip active={modality === "video"} onClick={() => setModality(modality === "video" ? "" : "video")}>
          视频
        </Chip>
        <div className="search">
          <Search size={15} />
          <input
            className="input"
            placeholder="搜索厂商、模型或提示词"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      {loading && items.length === 0 ? (
        <div className="loading-row">
          <Loader2 size={16} className="spin" /> 正在读取生成记录…
        </div>
      ) : items.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<History size={20} />}
            title="还没有生成记录"
            description="去创作台提交一次生成；任务成功、失败或被取消都会记录在这里。"
            action={
              <Button variant="primary" onClick={() => (window.location.hash = "#/studio")}>
                去创作
              </Button>
            }
          />
        </div>
      ) : (
        <>
          <div className="records panel">
            <div className="record-row record-head">
              <span />
              <span>任务</span>
              <span>状态</span>
              <span>时间</span>
              <span>耗时</span>
              <span>结果</span>
            </div>
            {items.map((job) => (
              <button className="record-row" key={job.id} onClick={() => void openDetail(job)}>
                <span className={`job-dot ${job.status}`} />
                <span className="record-main">
                  <strong>
                    {job.channel_name && (
                      <span className="record-vendor-badge" title={`厂商：${job.channel_name}`}>
                        {job.channel_name}
                      </span>
                    )}
                    <span className="record-model-name">{job.model_name || "未命名模型"}</span>
                    <em>{job.modality === "video" ? "视频" : "图像"}</em>
                  </strong>
                  <span className={job.error ? "record-error" : "record-prompt"}>
                    {job.error || job.prompt || "（无提示词）"}
                  </span>
                </span>
                <span>
                  <Badge tone={STATUS_TONE[job.status]} dot={isActive(job.status)}>
                    {STATUS_LABEL[job.status]}
                  </Badge>
                </span>
                <span className="record-cell">{formatRelative(job.created_at)}</span>
                <span className="record-cell">{elapsed(job)}</span>
                <span className="record-cell">{job.asset_count} 个</span>
              </button>
            ))}
          </div>
          {items.length < total && (
            <div style={{ display: "flex", justifyContent: "center", marginTop: 20 }}>
              <Button variant="soft" loading={loading} onClick={() => void load(offset + PAGE_SIZE)}>
                加载更多（{items.length}/{total}）
              </Button>
            </div>
          )}
        </>
      )}

      {detail && (
        <Modal
          open
          title={`生成记录 · ${detail.channel_name ? `${detail.channel_name} · ` : ""}${detail.model_name || "未命名模型"}`}
          subtitle={`${STATUS_LABEL[detail.status]} · ${stamp(detail.created_at)}`}
          onClose={() => setDetail(null)}
          width={780}
          footer={
            <>
              {isActive(detail.status) ? (
                <Button variant="danger" icon={<XCircle size={15} />} loading={detailBusy} onClick={() => void act("cancel")}>
                  取消任务
                </Button>
              ) : null}
              {["failed", "canceled", "uncertain"].includes(detail.status) ? (
                <Button variant="soft" icon={<RotateCcw size={15} />} loading={detailBusy} onClick={() => void act("retry")}>
                  重试
                </Button>
              ) : null}
              {!isActive(detail.status) ? (
                <Button variant="ghost" icon={<Trash2 size={15} />} loading={detailBusy} onClick={() => void act("delete")}>
                  删除记录
                </Button>
              ) : null}
              <span className="grow" />
              <Button variant="ghost" onClick={() => setDetail(null)}>
                关闭
              </Button>
            </>
          }
        >
          <div className="kv">
            <b>任务 ID</b>
            <span className="mono">{detail.id.slice(0, 12)}</span>
            <b>厂商</b>
            <span>{detail.channel_name || "—"}</span>
            <b>模型</b>
            <span>{detail.model_name || "—"}</span>
            <b>类型</b>
            <span>{detail.modality === "video" ? "视频" : "图像"}</span>
            <b>状态</b>
            <span>
              {STATUS_LABEL[detail.status]}
              {detail.stage ? ` · ${detail.stage}` : ""}
            </span>
            <b>创建</b>
            <span>{stamp(detail.created_at)}</span>
            <b>开始</b>
            <span>{stamp(detail.started_at)}</span>
            <b>结束</b>
            <span>{stamp(detail.finished_at)}</span>
            <b>耗时</b>
            <span>{elapsed(detail)}</span>
            <b>耗时明细</b>
            <span className="mono">
              {detail.duration_ms != null ? formatDurationMs(detail.duration_ms) : "—"}
            </span>
            <b>结果</b>
            <span>{detail.asset_count} 个文件</span>
            <b>费用</b>
            <span>
              {detail.price ? `${detail.price} ${detail.currency}` : "未记账"}
            </span>
          </div>

          {detail.error && (
            <div>
              <h3>失败原因</h3>
              <div className="lb-prompt record-fail">{detail.error}</div>
            </div>
          )}

          {detail.request?.prompt && (
            <div>
              <h3>提示词</h3>
              <div className="lb-prompt">{detail.request.prompt}</div>
            </div>
          )}

          {detail.request?.negative && (
            <div>
              <h3>反向词</h3>
              <div className="lb-prompt">{detail.request.negative}</div>
            </div>
          )}

          {detail.attempts && detail.attempts.length > 0 && (
            <div>
              <h3>线路记录</h3>
              <div className="job-attempts">
                {detail.attempts.map((attempt, index) => (
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
            </div>
          )}

          {detail.assets.length > 0 && (
            <div>
              <h3>结果</h3>
              <div className="records-assets">
                {detail.assets.map((asset) =>
                  asset.kind === "video" ? (
                    <a key={asset.id} className="records-asset" href={asset.url} target="_blank" rel="noreferrer">
                      <img src={asset.thumb_url} alt="" />
                      <span>视频</span>
                    </a>
                  ) : (
                    <a key={asset.id} className="records-asset" href={asset.url} target="_blank" rel="noreferrer">
                      <img src={asset.thumb_url} alt="" />
                    </a>
                  ),
                )}
              </div>
            </div>
          )}

          {hasActive && isActive(detail.status) && (
            <p className="hint-block">任务还在进行中，页面每 5 秒自动刷新一次。</p>
          )}
        </Modal>
      )}
    </>
  );
}
