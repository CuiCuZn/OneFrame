import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  Braces,
  Clapperboard,
  FlaskConical,
  Gem,
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Zap,
} from "lucide-react";
import { api, ApiError, type ModelPayload } from "../lib/api";
import { useStore } from "../lib/store";
import { money } from "../lib/hooks";
import type { Channel, Model, Modality, ProtocolDoc } from "../lib/types";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  IconButton,
  Modal,
  PageHead,
  Toggle,
} from "../components/ui";

const ICONS: Record<string, typeof Sparkles> = {
  openai_image: Sparkles,
  openai_video: Clapperboard,
  gemini_image: Gem,
  gemini_video: Gem,
  generic: Braces,
  mock: FlaskConical,
};

const FEATURES = [
  { id: "reference", label: "参考图" },
  { id: "first_frame", label: "首帧" },
  { id: "seed", label: "随机种子" },
  { id: "negative", label: "反向提示词" },
  { id: "img2img", label: "图生图" },
];

const EMPTY_MODEL: ModelPayload = {
  name: "",
  modality: "image",
  channel_id: "",
  upstream_model: "",
  description: "",
  enabled: true,
  caps: { max_refs: 4, max_count: 1, features: ["reference"], sizes: [], aspects: [] },
  params: {},
  price: { mode: "per_image", amount: 0.04, currency: "CNY" },
  overrides: {},
};

export default function Models() {
  const { catalog, models, channels, refreshModels, refreshChannels, toast } = useStore();
  const [channelModal, setChannelModal] = useState<{ open: boolean; channel?: Channel }>({ open: false });
  const [modelModal, setModelModal] = useState<{ open: boolean; model?: Model }>({ open: false });
  const [keyChannel, setKeyChannel] = useState<Channel | null>(null);
  const [busy, setBusy] = useState("");
  const protocols = catalog?.protocols ?? [];

  const testChannel = async (channel: Channel) => {
    setBusy(channel.id);
    try {
      const result = await api.channels.test(channel.id);
      toast(result.message, result.ok ? "success" : "error");
      await refreshChannels();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "测试失败", "error");
    } finally {
      setBusy("");
    }
  };

  const removeChannel = async (channel: Channel) => {
    if (!window.confirm(`删除「${channel.name}」？其下 ${channel.models_count} 个模型也会一起删除。`)) return;
    try {
      await api.channels.remove(channel.id);
      await Promise.all([refreshChannels(), refreshModels()]);
      toast("渠道已删除", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "删除失败", "error");
    }
  };

  const removeModel = async (model: Model) => {
    if (!window.confirm(`删除模型「${model.name}」？`)) return;
    try {
      await api.models.remove(model.id);
      await refreshModels();
      toast("模型已删除", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "删除失败", "error");
    }
  };

  const realChannels = channels.filter((channel) => channel.protocol !== "mock");

  return (
    <>
      <PageHead
        eyebrow="Providers"
        title="模型与密钥"
        description="每个「厂商 × 模型」都是独立入口：A 厂的 a 模型与 C 厂的 a 模型互不相干，失败不会互相兜底。"
        actions={
          <>
            <Button variant="soft" icon={<Plus size={15} />} onClick={() => setModelModal({ open: true })}>
              添加模型
            </Button>
            <Button variant="primary" icon={<Zap size={15} />} onClick={() => setChannelModal({ open: true })}>
              接入服务
            </Button>
          </>
        }
      />

      <div className="section-bar" style={{ marginBottom: 12 }}>
        <h2>
          服务渠道 <span className="count">{channels.length}</span>
        </h2>
        <span className="panel-hint">一个渠道 = 一个地址 + 一组密钥</span>
      </div>

      {channels.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<KeyRound size={20} />}
            title="还没有接入任何服务"
            description="支持 OpenAI Images/Videos 兼容中转、Google Gemini/Imagen/Veo，以及自定义 JSON 接口。"
            action={
              <Button variant="primary" onClick={() => setChannelModal({ open: true })} icon={<Zap size={15} />}>
                接入第一个服务
              </Button>
            }
          />
        </div>
      ) : (
        <div className="channel-grid">
          {channels.map((channel) => {
            const Icon = ICONS[channel.protocol] ?? Boxes;
            return (
              <article className="channel-card" key={channel.id}>
                <div className="channel-top">
                  <span className="channel-icon">
                    <Icon size={18} />
                  </span>
                  <div className="channel-name">
                    <strong>{channel.name}</strong>
                    <em>{channel.protocol_label}</em>
                  </div>
                  {channel.enabled ? <Badge tone="ok" dot>启用</Badge> : <Badge tone="warn">停用</Badge>}
                  <IconButton label="编辑渠道" onClick={() => setChannelModal({ open: true, channel })}>
                    <Pencil size={15} />
                  </IconButton>
                </div>

                {channel.base_url ? <div className="channel-url">{channel.base_url}</div> : null}

                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {channel.keys.length === 0 && channel.protocol !== "mock" && (
                    <div className="key-row" style={{ color: "var(--warn)" }}>
                      <AlertTriangle size={14} /> 还没有密钥，生成会失败
                    </div>
                  )}
                  {channel.keys.map((key) => (
                    <div className="key-row" key={key.id}>
                      <span
                        className={`key-dot ${key.status === "ok" ? "ok" : key.status === "error" ? "error" : ""}`}
                      />
                      <span className="key-label">{key.label}</span>
                      <span className="key-mask">{key.masked}</span>
                      <span className="faint" style={{ fontSize: 10 }}>
                        {key.ok_count > 0 ? `${key.ok_count} 次成功` : key.status === "error" ? "异常" : "未测试"}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="channel-foot">
                  <span className="panel-hint">{channel.models_count} 个模型</span>
                  <span className="spacer" />
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<RefreshCw size={13} />}
                    loading={busy === channel.id}
                    onClick={() => void testChannel(channel)}
                  >
                    测试
                  </Button>
                  {channel.protocol !== "mock" && (
                    <Button size="sm" variant="ghost" icon={<KeyRound size={13} />} onClick={() => setKeyChannel(channel)}>
                      密钥
                    </Button>
                  )}
                  <IconButton label="删除渠道" onClick={() => void removeChannel(channel)}>
                    <Trash2 size={15} />
                  </IconButton>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {realChannels.length === 0 && channels.length > 0 && (
        <div className="banner" style={{ marginTop: 16 }}>
          <Sparkles size={18} style={{ color: "var(--accent)" }} />
          <div>
            <strong>目前只有离线演示渠道</strong>
            <p>接入真实供应商后，每个「厂商 × 模型」都会单独出现在创作台的下拉里。</p>
          </div>
          <Button size="sm" variant="primary" onClick={() => setChannelModal({ open: true })}>
            接入
          </Button>
        </div>
      )}

      <div className="section-bar" style={{ margin: "28px 0 12px" }}>
        <h2>
          创作模型 <span className="count">{models.length}</span>
        </h2>
        <span className="panel-hint">下拉里会出现 {models.length} 个独立选项，失败即失败</span>
      </div>

      {models.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<Boxes size={20} />}
            title="还没有可用模型"
            description="先接入服务渠道，再为每个厂商的每个模型建一条记录；它们会分别出现在创作台。"
            action={
              <Button variant="primary" onClick={() => setModelModal({ open: true })} icon={<Plus size={15} />}>
                添加模型
              </Button>
            }
          />
        </div>
      ) : (
        <div className="model-table">
          {models.map((model) => (
            <div className="model-row" key={model.id}>
              <div className="model-row-main">
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <strong>{model.name}</strong>
                  <Badge tone={model.modality === "video" ? "accent" : "neutral"}>
                    {model.modality === "video" ? "视频" : "图像"}
                  </Badge>
                  {model.available ? (
                    <Badge tone="ok" dot>
                      可用
                    </Badge>
                  ) : (
                    <Badge tone="error">{model.reason || "不可用"}</Badge>
                  )}
                </div>
                <em>
                  {model.channel_name || "未绑定渠道"} · {model.upstream_model || "未填上游模型"}
                </em>
              </div>
              <div className="price-tag">
                <b>
                  {model.price.mode === "unconfigured"
                    ? "未定价"
                    : model.price.amount
                      ? money(model.price.amount, model.price.currency)
                      : "免费"}
                </b>
                <div className="faint">
                  {model.price.mode === "per_second" ? "每秒" : model.price.mode === "per_request" ? "每次" : "每张"}
                </div>
              </div>
              <div className="faint" style={{ fontSize: 11 }}>
                {model.caps.max_refs} 参考 · 最多 {model.caps.max_count}
              </div>
              <div className="row">
                <IconButton label="编辑模型" onClick={() => setModelModal({ open: true, model })}>
                  <Pencil size={15} />
                </IconButton>
                <IconButton label="删除模型" onClick={() => void removeModel(model)}>
                  <Trash2 size={15} />
                </IconButton>
              </div>
            </div>
          ))}
        </div>
      )}

      <ChannelModal
        open={channelModal.open}
        channel={channelModal.channel}
        protocols={protocols}
        onClose={() => setChannelModal({ open: false })}
        onSaved={async () => {
          setChannelModal({ open: false });
          await Promise.all([refreshChannels(), refreshModels()]);
          toast("已保存渠道", "success");
        }}
      />

      <ModelModal
        open={modelModal.open}
        model={modelModal.model}
        channels={channels}
        protocols={protocols}
        onClose={() => setModelModal({ open: false })}
        onSaved={async () => {
          setModelModal({ open: false });
          await Promise.all([refreshModels(), refreshChannels()]);
          toast("已保存模型", "success");
        }}
      />

      <KeysModal
        channel={keyChannel}
        onClose={() => setKeyChannel(null)}
        onChanged={async () => {
          await refreshChannels();
        }}
      />
    </>
  );
}

function ChannelModal({
  open,
  channel,
  protocols,
  onClose,
  onSaved,
}: {
  open: boolean;
  channel?: Channel;
  protocols: ProtocolDoc[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { toast } = useStore();
  const [name, setName] = useState("");
  const [protocol, setProtocol] = useState("openai_image");
  const [baseUrl, setBaseUrl] = useState("");
  const [note, setNote] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [keysText, setKeysText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (channel) {
      setName(channel.name);
      setProtocol(channel.protocol);
      setBaseUrl(channel.base_url);
      setNote(channel.note);
      setEnabled(channel.enabled);
      setKeysText("");
    } else {
      setName("");
      setProtocol("openai_image");
      setBaseUrl("https://api.openai.com/v1");
      setNote("");
      setEnabled(true);
      setKeysText("");
    }
  }, [open, channel]);

  const doc = protocols.find((item) => item.id === protocol);

  const pickProtocol = (item: ProtocolDoc) => {
    setProtocol(item.id);
    if (!channel) {
      setBaseUrl(item.base_url ?? "");
      if (!name) setName(item.label);
    }
  };

  const save = async () => {
    if (!name.trim()) return toast("请填写渠道名称", "error");
    setSaving(true);
    try {
      if (channel) {
        await api.channels.update(channel.id, {
          name: name.trim(),
          protocol,
          base_url: baseUrl.trim(),
          note,
          enabled,
        });
      } else {
        const keys = keysText
          .split(/\r?\n|,/)
          .map((line) => line.trim())
          .filter(Boolean)
          .map((secret, index) => ({ label: `密钥 ${index + 1}`, secret }));
        await api.channels.create({
          name: name.trim(),
          protocol,
          base_url: baseUrl.trim(),
          note,
          enabled,
          keys,
        });
      }
      await onSaved();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "保存失败", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title={channel ? "编辑服务渠道" : "接入服务"}
      subtitle="密钥只保存在本机，并使用 Fernet 加密存储"
      onClose={onClose}
      width={640}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" loading={saving} onClick={() => void save()}>
            保存
          </Button>
        </>
      }
    >
      {!channel && (
        <div className="protocol-grid">
          {protocols.map((item) => (
            <button
              key={item.id}
              className={`protocol-option ${protocol === item.id ? "is-active" : ""}`}
              onClick={() => pickProtocol(item)}
            >
              <strong>{item.label}</strong>
              <em>{item.about}</em>
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="渠道名称">
          <input className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 云雾中转站" />
        </Field>
        <Field label="协议">
          <select className="select" value={protocol} onChange={(event) => setProtocol(event.target.value)}>
            {protocols.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="服务地址" hint={protocol === "mock" ? "演示渠道不需要地址" : "包含 /v1 等版本前缀"}>
        <input
          className="input"
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
          placeholder={doc?.base_url || "https://your-gateway.example.com/v1"}
          disabled={protocol === "mock"}
        />
      </Field>

      {!channel && protocol !== "mock" && (
        <Field label="API Key" hint="每行一个，可一次粘贴多个密钥组成密钥池">
          <textarea
            className="textarea"
            rows={3}
            value={keysText}
            onChange={(event) => setKeysText(event.target.value)}
            placeholder={"sk-xxxx\nsk-yyyy"}
          />
        </Field>
      )}

      <Field label="备注">
        <input className="input" value={note} onChange={(event) => setNote(event.target.value)} placeholder="用途、计费方式等" />
      </Field>

      <div className="row">
        <Toggle checked={enabled} onChange={setEnabled} label="启用渠道" />
        <span className="muted" style={{ fontSize: 12 }}>
          启用该渠道
        </span>
        {doc?.docs && (
          <a className="btn btn-ghost btn-sm" href={doc.docs} target="_blank" rel="noreferrer" style={{ marginLeft: "auto" }}>
            接口文档
          </a>
        )}
      </div>
    </Modal>
  );
}

function KeysModal({
  channel,
  onClose,
  onChanged,
}: {
  channel: Channel | null;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const { toast } = useStore();
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);

  if (!channel) return null;

  const add = async () => {
    if (!secret.trim()) return toast("请粘贴密钥", "error");
    setBusy(true);
    try {
      await api.channels.addKey(channel.id, { label: label.trim() || "新密钥", secret: secret.trim() });
      setSecret("");
      setLabel("");
      await onChanged();
      toast("密钥已加密保存", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "保存失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    await api.channels.removeKey(channel.id, id);
    await onChanged();
    toast("已删除");
  };

  return (
    <Modal open title={`密钥池 · ${channel.name}`} subtitle="密钥用于分摊任务；401/429 时冷却，下次任务换用，当次不重试" onClose={onClose} width={560}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {channel.keys.map((key) => (
          <div className="key-row" key={key.id} style={{ padding: "9px 11px" }}>
            <span className={`key-dot ${key.status === "ok" ? "ok" : key.status === "error" ? "error" : ""}`} />
            <span className="key-label">{key.label}</span>
            <span className="key-mask">{key.masked}</span>
            {key.status === "error" && <span className="badge badge-error">异常</span>}
            <IconButton label="重置状态" onClick={() => void api.channels.resetKey(channel.id, key.id).then(onChanged)}>
              <RefreshCw size={14} />
            </IconButton>
            <IconButton label="删除密钥" onClick={() => void remove(key.id)}>
              <Trash2 size={14} />
            </IconButton>
          </div>
        ))}
        {channel.keys.length === 0 && <p className="faint">还没有密钥。</p>}
      </div>

      <div className="divider" />

      <div style={{ display: "grid", gridTemplateColumns: "160px 1fr auto", gap: 8, alignItems: "end" }}>
        <Field label="标签">
          <input className="input" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="主账号" />
        </Field>
        <Field label="新密钥">
          <input
            className="input"
            type="password"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
            placeholder="粘贴 API Key"
          />
        </Field>
        <Button variant="primary" loading={busy} onClick={() => void add()}>
          添加
        </Button>
      </div>
      <p className="hint-block">密钥不会回传浏览器，页面只显示前后各四位。401/429 的密钥会冷却，下一次任务自动换用同渠道其他密钥；当次任务失败，5xx 与超时也不重试。</p>
    </Modal>
  );
}

function ModelModal({
  open,
  model,
  channels,
  protocols,
  onClose,
  onSaved,
}: {
  open: boolean;
  model?: Model;
  channels: Channel[];
  protocols: ProtocolDoc[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { toast } = useStore();
  const [form, setForm] = useState<ModelPayload>(EMPTY_MODEL);
  const [saving, setSaving] = useState(false);
  const [aspectText, setAspectText] = useState("1:1, 3:4, 16:9");
  const [durationText, setDurationText] = useState("5, 8");
  const [resolutionText, setResolutionText] = useState("720p, 1080p");
  const [discover, setDiscover] = useState<{ channel: string; models: string[] } | null>(null);
  const [overridesText, setOverridesText] = useState("{}");
  const [responseFormat, setResponseFormat] = useState<"url" | "b64_json">("url");

  const channel = channels.find((item) => item.id === form.channel_id);
  const doc = protocols.find((item) => item.id === channel?.protocol);

  useEffect(() => {
    if (!open) return;
    if (model) {
      setForm({
        name: model.name,
        modality: model.modality,
        channel_id: model.channel_id,
        upstream_model: model.upstream_model,
        description: model.description,
        enabled: model.enabled,
        caps: { ...model.caps },
        params: { ...model.params },
        price: { ...model.price },
        overrides: model.overrides ?? {},
      });
      setAspectText((model.params.aspect_ratio ?? []).join(", "));
      setDurationText((model.params.duration ?? []).join(", "));
      setResolutionText((model.params.resolution ?? []).join(", "));
      setOverridesText(JSON.stringify(model.overrides ?? {}, null, 2));
      setResponseFormat(model.overrides?.response_format === "b64_json" ? "b64_json" : "url");
    } else {
      const first = channels[0];
      setForm({ ...EMPTY_MODEL, channel_id: first?.id ?? "", overrides: {} });
      setAspectText("1:1, 3:4, 16:9");
      setDurationText("5, 8");
      setResolutionText("720p, 1080p");
      setOverridesText("{}");
      setResponseFormat("url");
    }
    setDiscover(null);
  }, [open, model, channels]);

  useEffect(() => {
    if (!open || model) return;
    if (channel?.protocol === "generic" && Object.keys(form.overrides ?? {}).length === 0 && doc?.template) {
      const text = JSON.stringify(doc.template, null, 2);
      setOverridesText(text);
      setForm((current) => ({ ...current, overrides: doc.template as Record<string, unknown> }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel?.protocol, open]);

  const params = useMemo(() => {
    const next: Record<string, string[]> = {};
    const split = (text: string) => text.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean);
    if (form.modality === "image") {
      return next;
    } else {
      if (durationText.trim()) next.duration = split(durationText);
      if (resolutionText.trim()) next.resolution = split(resolutionText);
      if (aspectText.trim()) next.aspect_ratio = split(aspectText);
    }
    return next;
  }, [form.modality, aspectText, durationText, resolutionText]);

  const runDiscover = async () => {
    if (!form.channel_id) return;
    try {
      const result = await api.channels.discover(form.channel_id);
      setDiscover({ channel: form.channel_id, models: result.models });
      toast(result.message, result.ok ? "success" : "error");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "读取失败", "error");
    }
  };

  const save = async () => {
    if (!form.name.trim()) return toast("填写模型名称", "error");
    if (!form.channel_id) return toast("选择所属渠道", "error");
    if (!form.upstream_model.trim()) return toast("填写上游模型名", "error");
    let overrides: Record<string, unknown> = {};
    if (overridesText.trim()) {
      try {
        const parsed = JSON.parse(overridesText);
        if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) {
          return toast("自定义模板必须是 JSON 对象", "error");
        }
        overrides = parsed as Record<string, unknown>;
      } catch {
        return toast("自定义模板不是合法 JSON", "error");
      }
    }
    setSaving(true);
    try {
      if (channel?.protocol === "openai_image") {
        overrides = { ...overrides, response_format: responseFormat };
      }
      const payload: ModelPayload = {
        ...form,
        params,
        overrides,
        name: form.name.trim(),
        upstream_model: form.upstream_model.trim(),
      };
      if (model) await api.models.update(model.id, payload);
      else await api.models.create(payload);
      await onSaved();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "保存失败", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title={model ? "编辑模型" : "添加模型"}
      subtitle="一个模型 = 一个厂商 + 一个上游模型名；不会与其他厂商的同名模型合并"
      onClose={onClose}
      width={720}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" loading={saving} onClick={() => void save()}>
            保存模型
          </Button>
        </>
      }
    >
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 100px", gap: 12 }}>
        <Field label="显示名称" hint="创作台下拉里看到的名称">
          <input
            className="input"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            placeholder="例如 A厂 · a 模型"
          />
        </Field>
        <Field label="类型">
          <select
            className="select"
            value={form.modality}
            onChange={(event) => setForm({ ...form, modality: event.target.value as Modality })}
          >
            <option value="image">图像</option>
            <option value="video">视频</option>
          </select>
        </Field>
        <Field label="启用">
          <div style={{ height: 34, display: "flex", alignItems: "center" }}>
            <Toggle checked={form.enabled} onChange={(enabled) => setForm({ ...form, enabled })} />
          </div>
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.3fr auto", gap: 12, alignItems: "end" }}>
        <Field label="所属渠道（厂商）">
          <select
            className="select"
            value={form.channel_id}
            onChange={(event) => setForm({ ...form, channel_id: event.target.value })}
          >
            <option value="">选择渠道</option>
            {channels.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="上游模型名" hint="站点文档里的 model id">
          <input
            className="input"
            list="discovered-models"
            value={form.upstream_model}
            onChange={(event) => setForm({ ...form, upstream_model: event.target.value })}
            placeholder="gpt-image-1 / gemini-2.5-flash-image"
          />
          <datalist id="discovered-models">
            {(discover?.channel === form.channel_id ? discover.models : []).map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </Field>
        <Button variant="soft" icon={<RefreshCw size={14} />} onClick={() => void runDiscover()} disabled={!form.channel_id}>
          读取列表
        </Button>
      </div>

      <Field label="描述" hint="显示在创作台的参数面板">
        <input
          className="input"
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
          placeholder="例如 4K 细节，适合角色设定"
        />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="参考图上限">
          <input
            className="input"
            type="number"
            min={0}
            max={16}
            value={form.caps.max_refs}
            onChange={(event) =>
              setForm({ ...form, caps: { ...form.caps, max_refs: Number(event.target.value) } })
            }
          />
        </Field>
        <Field label={form.modality === "video" ? "单次数量（视频固定 1）" : "单次最多张数"}>
          <input
            className="input"
            type="number"
            min={1}
            max={16}
            value={form.caps.max_count}
            onChange={(event) =>
              setForm({ ...form, caps: { ...form.caps, max_count: Number(event.target.value) } })
            }
          />
        </Field>
      </div>

      <div>
        <div className="field-label" style={{ marginBottom: 7 }}>
          支持能力
        </div>
        <div className="check-grid">
          {FEATURES.map((feature) => {
            const on = form.caps.features.includes(feature.id);
            return (
              <label className={`check-pill ${on ? "is-on" : ""}`} key={feature.id}>
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() =>
                    setForm({
                      ...form,
                      caps: {
                        ...form.caps,
                        features: on
                          ? form.caps.features.filter((item) => item !== feature.id)
                          : [...form.caps.features, feature.id],
                      },
                    })
                  }
                />
                {feature.label}
              </label>
            );
          })}
        </div>
      </div>

      {form.modality === "image" ? (
        <p className="hint-block">
          画幅（1:1 / 4:3 / 3:4 / 16:9 / 9:16）与清晰度（1K / 2K / 4K）在创作台统一选择，这里无需配置尺寸。
        </p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="可选时长（秒）">
            <input className="input" value={durationText} onChange={(event) => setDurationText(event.target.value)} />
          </Field>
          <Field label="可选分辨率">
            <input className="input" value={resolutionText} onChange={(event) => setResolutionText(event.target.value)} />
          </Field>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <Field label="计费方式">
          <select
            className="select"
            value={form.price.mode}
            onChange={(event) =>
              setForm({ ...form, price: { ...form.price, mode: event.target.value as ModelPayload["price"]["mode"] } })
            }
          >
            <option value="per_image">每张</option>
            <option value="per_request">每次</option>
            <option value="per_second">每秒</option>
            <option value="unconfigured">不计价</option>
          </select>
        </Field>
        <Field label="单价">
          <input
            className="input"
            type="number"
            step="0.001"
            value={form.price.amount}
            onChange={(event) => setForm({ ...form, price: { ...form.price, amount: Number(event.target.value) } })}
          />
        </Field>
        <Field label="货币">
          <select
            className="select"
            value={form.price.currency}
            onChange={(event) => setForm({ ...form, price: { ...form.price, currency: event.target.value } })}
          >
            <option value="CNY">CNY</option>
            <option value="USD">USD</option>
          </select>
        </Field>
      </div>

      {channel?.protocol === "openai_image" && (
        <Field label="返回格式" hint="多数中转站只支持 URL；官方 OpenAI 两种都支持">
          <select
            className="select"
            value={responseFormat}
            onChange={(event) => setResponseFormat(event.target.value as "url" | "b64_json")}
          >
            <option value="url">URL（推荐）</option>
            <option value="b64_json">base64（b64_json）</option>
          </select>
        </Field>
      )}

      {(channel?.protocol === "generic" || Object.keys(form.overrides ?? {}).length > 0) && (
        <Field label="自定义接口模板（JSON）" hint="仅自定义 JSON 渠道需要">
          <textarea
            className="textarea code-textarea"
            rows={8}
            value={overridesText}
            onChange={(event) => setOverridesText(event.target.value)}
            spellCheck={false}
          />
        </Field>
      )}

      <p className="hint-block">
        这个模型只走「{channel?.name || "所选渠道"}」：失败直接失败，不会自动切到别家，也不会在同一任务里换 Key 重发。401/429 的 Key 会冷却，下一次任务换用同渠道其他 Key。
      </p>
    </Modal>
  );
}
