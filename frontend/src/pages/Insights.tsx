import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  CircleDollarSign,
  Clapperboard,
  HardDrive,
  Image as ImageIcon,
  Loader2,
  Sparkles,
  Target,
} from "lucide-react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import { formatBytes, money } from "../lib/hooks";
import type { Stats } from "../lib/types";
import { Badge, PageHead } from "../components/ui";

export default function Insights() {
  const { toast } = useStore();
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    api
      .stats()
      .then(setStats)
      .catch(() => toast("统计读取失败", "error"));
  }, [toast]);

  const maxJobs = useMemo(
    () => Math.max(1, ...(stats?.series.map((row) => row.jobs) ?? [1])),
    [stats],
  );

  if (!stats) {
    return (
      <div className="loading-row">
        <Loader2 size={16} className="spin" /> 正在统计…
      </div>
    );
  }

  return (
    <>
      <PageHead
        eyebrow="Insights"
        title="用量洞察"
        description="谁在花钱、哪条线路稳定、最近生成什么，一页看清。所有数据来自本地任务记录。"
      />

      <div className="kpi-grid">
        <div className="kpi">
          <div className="kpi-label">
            <ImageIcon size={14} /> 作品总数
          </div>
          <div className="kpi-value">
            {stats.assets.total}
            <small>件</small>
          </div>
          <div className="kpi-foot">
            图像 {stats.assets.by_kind.image ?? 0} · 视频 {stats.assets.by_kind.video ?? 0} · 收藏{" "}
            {stats.assets.favorite}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">
            <Target size={14} /> 任务成功率
          </div>
          <div className="kpi-value">
            {stats.jobs.success_rate}
            <small>%</small>
          </div>
          <div className="kpi-foot">
            成功 {stats.jobs.succeeded} · 失败 {stats.jobs.failed}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">
            <CircleDollarSign size={14} /> 近 30 天花费
          </div>
          <div className="kpi-value">{money(stats.spend.last_30d)}</div>
          <div className="kpi-foot">累计 {money(stats.spend.total)}（按模型定价估算）</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">
            <Clapperboard size={14} /> 今日任务
          </div>
          <div className="kpi-value">
            {stats.jobs.today}
            <small>个</small>
          </div>
          <div className="kpi-foot">累计 {stats.jobs.total} 个任务</div>
        </div>
      </div>

      <div className="two-col">
        <section className="chart-box">
          <div className="section-bar">
            <h2>最近 14 天生成量</h2>
            <div className="chart-legend">
              <span>柱子高度 = 当日任务数</span>
            </div>
          </div>
          <div className="bars">
            {stats.series.map((row) => (
              <div className="bar-col" key={row.day} title={`${row.day} · ${row.jobs} 个任务 · ${money(row.spend)}`}>
                <div className="bar" style={{ height: `${Math.max(2, (row.jobs / maxJobs) * 100)}%` }} />
                <em>{row.day.slice(5)}</em>
              </div>
            ))}
          </div>
        </section>

        <section className="chart-box">
          <div className="section-bar">
            <h2>常用模型</h2>
            <Sparkles size={14} style={{ color: "var(--faint)" }} />
          </div>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
            {stats.top_models.length === 0 && <p className="faint">还没有生成记录。</p>}
            {stats.top_models.map((row) => {
              const max = Math.max(...stats.top_models.map((item) => item.count), 1);
              return (
                <div key={row.model_name}>
                  <div className="row" style={{ fontSize: 12, marginBottom: 4 }}>
                    <span style={{ color: "var(--text-2)" }}>{row.model_name}</span>
                    <span className="spacer" />
                    <span className="faint">{row.count}</span>
                  </div>
                  <div className="job-bar">
                    <i style={{ width: `${(row.count / max) * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      <div className="two-col" style={{ marginTop: 14 }}>
        <section className="chart-box">
          <div className="section-bar">
            <h2>渠道表现</h2>
            <Badge tone="neutral">
              <HardDrive size={12} /> {formatBytes(stats.disk.media)} 媒体
            </Badge>
          </div>
          <table className="data-table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>渠道</th>
                <th>协议</th>
                <th>密钥</th>
                <th>任务</th>
                <th>花费</th>
              </tr>
            </thead>
            <tbody>
              {stats.channels.map((channel) => (
                <tr key={channel.id}>
                  <td style={{ color: "var(--text)" }}>{channel.name}</td>
                  <td className="faint">{channel.protocol}</td>
                  <td>
                    <span className={`health ${channel.ok_keys > 0 ? "" : "faint"}`}>
                      <i className={`key-dot ${channel.ok_keys > 0 ? "ok" : ""}`} />
                      {channel.ok_keys}/{channel.keys}
                    </span>
                  </td>
                  <td>{channel.jobs}</td>
                  <td>{money(channel.spend)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="chart-box">
          <div className="section-bar">
            <h2>本地存储</h2>
          </div>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="kv">
              <b>媒体</b>
              <span>{formatBytes(stats.disk.media)}</span>
              <b>数据总量</b>
              <span>{formatBytes(stats.disk.total)}</span>
            </div>
            <div className="hint-block">
              作品保存在 data/media，缩略图在 data/thumbs。备份时直接复制 data 目录即可；密钥文件
              data/secret.key 一并备份才能解密。
            </div>
            <div className="row">
              <BarChart3 size={14} style={{ color: "var(--faint)" }} />
              <span className="faint" style={{ fontSize: 11 }}>
                所有统计均来自本地 SQLite，不上传任何遥测。
              </span>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
