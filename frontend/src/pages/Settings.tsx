import { useEffect, useState } from "react";
import {
  Check,
  Clipboard,
  Cpu,
  Database,
  Eye,
  FolderOpen,
  FolderPlus,
  HardDrive,
  KeyRound,
  MonitorSmartphone,
  Moon,
  Plus,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
} from "lucide-react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import { formatBytes, useCopy } from "../lib/hooks";
import type { SystemInfo } from "../lib/types";
import { Badge, Field, PageHead, Segmented, Spinner, Toggle } from "../components/ui";

export default function SettingsPage() {
  const { models, settings, saveSetting, toast, theme, resolvedTheme, setTheme } = useStore();
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [newRoot, setNewRoot] = useState("");
  const { copied, copy } = useCopy();

  const extraRoots = (system?.library_roots ?? []).filter((root) => root !== system?.data_dir);

  const saveRoots = async (roots: string[]) => {
    await saveSetting("library_roots", roots.join(";"));
    setSystem(await api.system());
    toast("参考库目录已更新", "success");
  };

  const addRoot = async () => {
    const value = newRoot.trim();
    if (!value) return;
    if (extraRoots.includes(value)) return toast("这个目录已经在列表里了");
    await saveRoots([...extraRoots, value]);
    setNewRoot("");
  };

  useEffect(() => {
    api
      .system()
      .then(setSystem)
      .catch(() => toast("系统信息读取失败", "error"));
  }, [toast]);

  const imageModels = models.filter((model) => model.modality === "image");
  const videoModels = models.filter((model) => model.modality === "video");
  const nsfw = settings.library_nsfw === "1";

  return (
    <>
      <PageHead
        eyebrow="Preferences"
        title="设置"
        description="默认模型、并发与本地数据位置。所有配置都保存在本机 data/oneframe.db。"
      />

      <div className="settings-grid">
        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <Sun size={15} /> 外观
            </span>
            <Badge tone="neutral">{resolvedTheme === "light" ? "浅色" : "深色"}</Badge>
          </div>
          <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Segmented
              value={theme}
              onChange={setTheme}
              options={[
                { value: "dark", label: (<><Moon size={13} /> 深色</>) },
                { value: "light", label: (<><Sun size={13} /> 浅色</>) },
                { value: "auto", label: (<><MonitorSmartphone size={13} /> 跟随系统</>) },
              ]}
            />
            <p className="hint-block">
              深色适合长时间看图与剪辑，浅色在白天更省眼；右上角的太阳/月亮按钮可随时切换，滚动条与原生控件会一起跟随主题。
            </p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <Sparkles size={15} /> 创作默认
            </span>
          </div>
          <div className="panel-pad">
            <Field label="默认图像模型">
              <select
                className="select"
                value={settings.default_image_model ?? ""}
                onChange={(event) => void saveSetting("default_image_model", event.target.value)}
              >
                <option value="">自动选择第一个可用模型</option>
                {imageModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </Field>
            <div className="setting-row">
              <div>
                <strong>默认视频模型</strong>
                <em>打开创作台并切到视频时使用</em>
              </div>
              <select
                className="select"
                value={settings.default_video_model ?? ""}
                onChange={(event) => void saveSetting("default_video_model", event.target.value)}
              >
                <option value="">自动</option>
                {videoModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="setting-row">
              <div>
                <strong>提示词语言</strong>
                <em>参考编排时生成中文或英文指令</em>
              </div>
              <select
                className="select"
                value={settings.prompt_language ?? "zh"}
                onChange={(event) => void saveSetting("prompt_language", event.target.value)}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </div>

          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <Eye size={15} /> 内容与显示
            </span>
            <Badge tone={nsfw ? "warn" : "neutral"}>{nsfw ? "已显示" : "默认隐藏"}</Badge>
          </div>
          <div className="panel-pad">
            <div className="setting-row">
              <div>
                <strong>显示 NSFW 参考素材</strong>
                <em>性感姿势、内衣 / 性感穿搭与泳装等素材</em>
              </div>
              <Toggle
                checked={nsfw}
                label="显示 NSFW 参考素材"
                onChange={(value) => void saveSetting("library_nsfw", value ? "1" : "0")}
              />
            </div>
            <p className="hint-block">
              默认关闭。关闭时只是不在参考库里展示这些素材，磁盘上的文件不会被删除；开启后立即生效，参考库与创作台的「从参考库选择」都会一起变化。
            </p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <Cpu size={15} /> 运行
            </span>
          </div>
          <div className="panel-pad">
            {!system ? (
              <Spinner label="读取中…" />
            ) : (
              <>
                <div className="setting-row">
                  <div>
                    <strong>图像并发</strong>
                    <em>同时提交的上游图像任务数</em>
                  </div>
                  <Badge tone="neutral">{system.workers.image}</Badge>
                </div>
                <div className="setting-row">
                  <div>
                    <strong>视频并发</strong>
                    <em>同时轮询的视频任务数</em>
                  </div>
                  <Badge tone="neutral">{system.workers.video}</Badge>
                </div>
                <div className="setting-row">
                  <div>
                    <strong>ffmpeg</strong>
                    <em>用于视频封面与时长探测</em>
                  </div>
                  <Badge tone={system.ffmpeg ? "ok" : "warn"} dot>
                    {system.ffmpeg ? "已就绪" : "未检测到"}
                  </Badge>
                </div>
                <div className="setting-row">
                  <div>
                    <strong>服务地址</strong>
                    <em>默认只监听本机回环地址</em>
                  </div>
                  <span className="mono faint" style={{ fontSize: 11 }}>
                    127.0.0.1:8787
                  </span>
                </div>
                <p className="hint-block">
                  修改并发或监听地址：设置环境变量 ONEFRAME_IMAGE_WORKERS / ONEFRAME_VIDEO_WORKERS /
                  ONEFRAME_HOST 后重启。
                </p>
              </>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <Database size={15} /> 本地数据
            </span>
          </div>
          <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {system ? (
              <>
                <div className="setting-row">
                  <div>
                    <strong>数据目录</strong>
                    <em>数据库、密钥、媒体与缩略图</em>
                  </div>
                </div>
                <div className="code-block">{system.data_dir}</div>
                <div className="setting-row">
                  <div>
                    <strong>数据库</strong>
                    <em>SQLite · WAL</em>
                  </div>
                </div>
                <div className="code-block">{system.db_path}</div>
                <div className="setting-row">
                  <div>
                    <strong>媒体目录</strong>
                    <em>数据目录共占用 {formatBytes(system.data_bytes)}</em>
                  </div>
                </div>
                <div className="code-block">{system.media_dir}</div>
                <div className="setting-row">
                  <div>
                    <strong>参考库允许目录</strong>
                    <em>只读索引，不复制文件</em>
                  </div>
                </div>
                <div className="code-block">{system.library_roots.join("\n")}</div>
                <button
                  className="btn btn-soft btn-sm"
                  onClick={() => void copy(system.data_dir)}
                  style={{ alignSelf: "flex-start" }}
                >
                  {copied ? <Check size={14} /> : <Clipboard size={14} />}
                  {copied ? "已复制" : "复制数据目录"}
                </button>
              </>
            ) : (
              <Spinner label="读取中…" />
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <FolderPlus size={15} /> 参考库目录
            </span>
          </div>
          <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p className="hint-block">
              参考库只索引这些目录里的图片，不复制、不上传。默认允许 data 目录；把姿势图库所在磁盘加进来即可直接导入。
            </p>
            <div className="code-block">{system?.data_dir ?? "data"}（内置）</div>
            {extraRoots.map((root) => (
              <div className="row" key={root}>
                <div className="code-block grow">{root}</div>
                <button
                  className="icon-btn"
                  title="移除该目录"
                  onClick={() => void saveRoots(extraRoots.filter((item) => item !== root))}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <div className="row">
              <input
                className="input"
                placeholder="D:\\refs\\ai-pose-gallery-zh"
                value={newRoot}
                onChange={(event) => setNewRoot(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void addRoot();
                }}
              />
              <button className="btn btn-soft" onClick={() => void addRoot()}>
                <Plus size={14} /> 添加
              </button>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <ShieldCheck size={15} /> 安全与备份
            </span>
          </div>
          <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="setting-row">
              <div>
                <strong>密钥加密</strong>
                <em>Fernet 对称加密，主密钥在 data/secret.key</em>
              </div>
              <Badge tone="ok" dot>
                本地加密
              </Badge>
            </div>
            <div className="setting-row">
              <div>
                <strong>密钥回显</strong>
                <em>接口只返回前后各四位</em>
              </div>
              <Badge tone="ok" dot>
                已脱敏
              </Badge>
            </div>
            <p className="hint-block">
              备份：复制整个 data 目录即可。secret.key 与数据库必须一起备份，否则已保存的 API Key
              无法解密。不要把 data 目录提交到公开仓库。
            </p>
            <p className="hint-block">
              本平台默认只监听 127.0.0.1，不做登录鉴权；如果要放到局域网或公网，请在前面加一层反向代理与访问控制。
            </p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <KeyRound size={15} /> 快捷键
            </span>
          </div>
          <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">提交生成</span>
              <span className="badge">Ctrl / ⌘ + Enter</span>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">关闭弹窗</span>
              <span className="badge">Esc</span>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted">打开接口文档</span>
              <a className="badge" href="/docs" target="_blank" rel="noreferrer">
                /docs
              </a>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <span className="panel-title">
              <FolderOpen size={15} /> 关于
            </span>
          </div>
          <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="row">
              <span className="brand-mark" style={{ width: 34, height: 34 }}>
                <svg viewBox="0 0 28 28">
                  <rect x="3.5" y="3.5" width="21" height="21" rx="6" />
                  <rect x="10" y="10" width="8" height="8" rx="2.4" />
                  <circle cx="21.4" cy="6.6" r="1.5" />
                </svg>
              </span>
              <div>
                <strong style={{ fontSize: 14 }}>一格 OneFrame</strong>
                <div className="faint" style={{ fontSize: 11 }}>
                  v{system?.version ?? "1.0.0"} · 本地优先的 AI 图像工作台
                </div>
              </div>
            </div>
            <p className="hint-block">
              一个入口接所有图像与视频模型：渠道池、加权线路、失败切换、参考图编排与本地作品库，全部离线可控。
            </p>
            <div className="row">
              <HardDrive size={13} className="faint" />
              <span className="faint" style={{ fontSize: 11 }}>
                数据不会离开这台机器
              </span>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}


