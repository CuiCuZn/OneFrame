import { useCallback, useEffect, useState } from "react";
import {
  Archive,
  Brush,
  Copy,
  Download,
  GitCompare,
  Grid2X2,
  ImageOff,
  Images,
  Loader2,
  Maximize2,
  Play,
  Search,
  Sparkles,
  Star,
  Trash2,
  UserRound,
  Wand2,
  X,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import { formatRelative, money } from "../lib/hooks";
import type { Asset } from "../lib/types";
import CompareModal, { type CompareSource } from "../components/CompareModal";
import CharacterToolsModal from "../components/CharacterToolsModal";
import GridSplitModal from "../components/GridSplitModal";
import InpaintModal from "../components/InpaintModal";
import RefineModal from "../components/RefineModal";
import VersionStrip from "../components/VersionStrip";
import {
  Badge,
  Button,
  Chip,
  EmptyState,
  IconButton,
  PageHead,
} from "../components/ui";

export default function Gallery() {
  const { toast } = useStore();
  const [kind, setKind] = useState("");
  const [favorite, setFavorite] = useState(false);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<Asset | null>(null);
  const [compare, setCompare] = useState<{
    left: CompareSource;
    right: CompareSource;
    alternatives?: CompareSource[];
    mode: "fidelity" | "selection";
  } | null>(null);
  const [comparePick, setComparePick] = useState<Asset | null>(null);
  const [inpaintAsset, setInpaintAsset] = useState<Asset | null>(null);
  const [refineAsset, setRefineAsset] = useState<Asset | null>(null);
  const [splitAsset, setSplitAsset] = useState<Asset | null>(null);
  const [characterAsset, setCharacterAsset] = useState<Asset | null>(null);

  const load = useCallback(
    async (nextOffset = 0) => {
      setLoading(true);
      try {
        const data = await api.assets.list({
          kind,
          q: query,
          favorite: favorite ? true : undefined,
          limit: 32,
          offset: nextOffset,
        });
        setItems((current) => (nextOffset === 0 ? data.items : [...current, ...data.items]));
        setTotal(data.total);
        setOffset(nextOffset);
      } catch (error) {
        toast(error instanceof ApiError ? error.message : "读取失败", "error");
      } finally {
        setLoading(false);
      }
    },
    [kind, query, favorite, toast],
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  const toggleFavorite = async (asset: Asset) => {
    const next = !asset.favorite;
    await api.assets.patch(asset.id, { favorite: next });
    setItems((current) => current.map((row) => (row.id === asset.id ? { ...row, favorite: next } : row)));
    if (detail?.id === asset.id) setDetail({ ...detail, favorite: next });
  };

  const remove = async (asset: Asset) => {
    if (!window.confirm("删除这张作品与本地文件？此操作不可撤销。")) return;
    await api.assets.remove(asset.id);
    setItems((current) => current.filter((row) => row.id !== asset.id));
    setDetail(null);
    toast("已删除");
  };

  const reuse = async (asset: Asset, asReference: boolean) => {
    const draft = {
      prompt: asset.prompt,
      negative: asset.negative,
      model_id: asset.model_id,
      params: asset.params,
      refs: asReference ? [{ asset_id: asset.id, role: "reference", name: "上一版结果" }] : [],
    };
    window.localStorage.setItem("of.pendingDraft", JSON.stringify(draft));
    window.location.hash = "#/studio";
  };

  const addToReferences = async (asset: Asset) => {
    if (asset.kind !== "image") {
      toast("只有图片作品可以加入参考库", "error");
      return;
    }
    try {
      const result = await api.library.fromAsset(asset.id);
      toast(
        result.created ? "已加入参考库「我的作品」" : "这张作品已经在参考库里了",
        result.created ? "success" : "info",
      );
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "加入参考库失败", "error");
    }
  };

  const compareWithRefs = async (asset: Asset) => {
    try {
      const data = await api.assets.refs(asset.id);
      const refs = data.items
        .filter((item) => !item.missing)
        .map((item) => ({
          url: item.url,
          label: `参考 · ${item.name || item.role}`,
          kind: "reference" as const,
          missing: item.missing,
        }));
      if (!refs.length) {
        toast("这条作品没有可用的参考图", "error");
        return;
      }
      setCompare({
        left: { url: asset.url, label: "生成结果", kind: "generated" },
        right: refs[0],
        alternatives: refs,
        mode: "fidelity",
      });
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "读取参考图失败", "error");
    }
  };

  const markCompareA = (asset: Asset) => {
    setComparePick(asset);
    toast("已选为对比 A，去另一张作品点「与 A 对比」", "success");
  };

  const compareWithA = (asset: Asset) => {
    if (!comparePick) return;
    setCompare({
      left: { url: comparePick.url, label: "作品 A", kind: "asset" },
      right: { url: asset.url, label: "作品 B", kind: "asset" },
      mode: "selection",
    });
  };

  const upscale = async (asset: Asset) => {
    if (!window.confirm("本地放大只提升分辨率，不会补充 AI 细节。继续放大 2 倍？")) return;
    try {
      const result = await api.assets.upscale(asset.id, 2);
      toast("已生成 2x 放大版本", "success");
      await load(0);
      setDetail(result);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "放大失败", "error");
    }
  };

  return (
    <>
      <PageHead
        eyebrow="Works"
        title="作品库"
        description="所有出图与视频都在本地；收藏、复用提示词、下载原文件，不依赖任何云端相册。"
        actions={
          <Button variant="soft" icon={<Wand2 size={15} />} onClick={() => (window.location.hash = "#/studio")}>
            去创作
          </Button>
        }
      />

      <div className="filter-bar">
        <Chip active={!kind && !favorite} onClick={() => { setKind(""); setFavorite(false); }}>
          全部 <span className="faint">{total}</span>
        </Chip>
        <Chip active={kind === "image"} onClick={() => setKind(kind === "image" ? "" : "image")}>
          <Images size={12} /> 图像
        </Chip>
        <Chip active={kind === "video"} onClick={() => setKind(kind === "video" ? "" : "video")}>
          <Play size={12} /> 视频
        </Chip>
        <Chip active={favorite} onClick={() => setFavorite((value) => !value)}>
          <Star size={12} /> 收藏
        </Chip>
        <div className="spacer" />
        <div className="search">
          <Search size={15} />
          <input
            className="input"
            placeholder="搜索提示词或标签"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      {loading && items.length === 0 ? (
        <div className="loading-row">
          <Loader2 size={16} className="spin" /> 正在整理作品…
        </div>
      ) : items.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<ImageOff size={20} />}
            title="还没有作品"
            description="去创作台生成第一张图，或者把已有素材上传到这里统一管理。"
            action={
              <Button variant="primary" onClick={() => (window.location.hash = "#/studio")}>
                开始创作
              </Button>
            }
          />
        </div>
      ) : (
        <>
          <div className="gallery-grid">
            {items.map((asset) => (
              <div
                className={`asset-card ${asset.kind === "video" ? "is-video" : ""}`}
                key={asset.id}
                onClick={() => setDetail(asset)}
              >
                <div className="media">
                  <img src={asset.thumb_url} alt="" loading="lazy" />
                </div>
                {asset.kind === "video" && (
                  <div className="tile-play">
                    <span>
                      <Play size={18} fill="currentColor" />
                    </span>
                  </div>
                )}
                <div className="asset-foot">
                  <span className="asset-prompt">{asset.prompt || "上传素材"}</span>
                  {asset.kind === "image" && (
                    <IconButton
                      label="加入参考库"
                      onClick={(event) => {
                        event.stopPropagation();
                        void addToReferences(asset);
                      }}
                    >
                      <Images size={14} />
                    </IconButton>
                  )}
                  <IconButton
                    label={asset.favorite ? "取消收藏" : "收藏"}
                    className={asset.favorite ? "is-active" : ""}
                    onClick={(event) => {
                      event.stopPropagation();
                      void toggleFavorite(asset);
                    }}
                  >
                    <Star size={14} fill={asset.favorite ? "currentColor" : "none"} />
                  </IconButton>
                  <a
                    className="icon-btn"
                    href={asset.download_url}
                    title="下载"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <Download size={14} />
                  </a>
                </div>
              </div>
            ))}
          </div>
          {items.length < total && (
            <div style={{ display: "flex", justifyContent: "center", marginTop: 20 }}>
              <Button variant="soft" loading={loading} onClick={() => void load(offset + 32)}>
                加载更多（{items.length}/{total}）
              </Button>
            </div>
          )}
        </>
      )}

      {detail && (
        <div className="lightbox" onClick={() => setDetail(null)}>
          <div className="lb-stage" onClick={(event) => event.stopPropagation()}>
            <button className="icon-btn lb-close" onClick={() => setDetail(null)} title="关闭">
              <X size={18} />
            </button>
            {detail.kind === "video" ? (
              <video src={detail.url} controls autoPlay loop playsInline poster={detail.thumb_url} />
            ) : (
              <img src={detail.url} alt="" />
            )}
          </div>
          <aside className="lb-side" onClick={(event) => event.stopPropagation()}>
            <div>
              <div className="row" style={{ marginBottom: 8 }}>
                <Badge tone={detail.kind === "video" ? "accent" : "neutral"}>
                  {detail.kind === "video" ? "视频" : "图像"}
                </Badge>
                {detail.origin === "upload" && <Badge>上传</Badge>}
                {detail.origin === "url" && <Badge>远程</Badge>}
                {detail.origin === "split" && <Badge>拆分</Badge>}
                {detail.origin === "upscaled" && <Badge>放大</Badge>}
                {detail.favorite && <Badge tone="accent">已收藏</Badge>}
              </div>
              <div className="kv">
                <b>模型</b>
                <span>{detail.model_name || "—"}</span>
                <b>尺寸</b>
                <span>{detail.width && detail.height ? `${detail.width} × ${detail.height}` : "—"}</span>
                <b>时间</b>
                <span>{formatRelative(detail.created_at)}</span>
                <b>文件</b>
                <span>{detail.bytes ? `${(detail.bytes / 1024 / 1024).toFixed(2)} MB` : "—"}</span>
              </div>
            </div>

            {detail.prompt && (
              <div>
                <h3>提示词</h3>
                <div className="lb-prompt">{detail.prompt}</div>
              </div>
            )}

            {detail.negative && (
              <div>
                <h3>反向词</h3>
                <div className="lb-prompt">{detail.negative}</div>
              </div>
            )}

            <div className="lb-actions">
              <Button variant="primary" icon={<Wand2 size={15} />} onClick={() => void reuse(detail, false)}>
                复用这组参数
              </Button>
              <Button variant="soft" icon={<Copy size={15} />} onClick={() => void reuse(detail, true)}>
                作为参考继续改
              </Button>
              {detail.kind === "image" && (
                <Button variant="soft" icon={<Images size={15} />} onClick={() => void addToReferences(detail)}>
                  加入参考库
                </Button>
              )}
              {detail.kind === "image" && (
                <Button variant="soft" icon={<GitCompare size={15} />} onClick={() => void compareWithRefs(detail)}>
                  对比参考
                </Button>
              )}
              {detail.kind === "image" &&
                (comparePick && comparePick.id !== detail.id ? (
                  <Button variant="soft" icon={<GitCompare size={15} />} onClick={() => compareWithA(detail)}>
                    与 A 对比
                  </Button>
                ) : (
                  <Button variant="ghost" icon={<GitCompare size={15} />} onClick={() => markCompareA(detail)}>
                    设为对比 A
                  </Button>
                ))}
              {detail.kind === "image" && (
                <a className="btn btn-ghost" href={api.assets.referenceZipUrl(detail.id)}>
                  <Archive size={15} /> 参考图 ZIP
                </a>
              )}
              {detail.kind === "image" && (
                <>
                  <Button variant="soft" icon={<Brush size={15} />} onClick={() => setInpaintAsset(detail)}>
                    局部重绘
                  </Button>
                  <Button variant="soft" icon={<Sparkles size={15} />} onClick={() => setRefineAsset(detail)}>
                    精修
                  </Button>
                  <Button variant="ghost" icon={<Maximize2 size={15} />} onClick={() => void upscale(detail)}>
                    本地放大 2x
                  </Button>
                  <Button variant="ghost" icon={<Grid2X2 size={15} />} onClick={() => setSplitAsset(detail)}>
                    宫格拆分
                  </Button>
                  <Button variant="ghost" icon={<UserRound size={15} />} onClick={() => setCharacterAsset(detail)}>
                    角色工具
                  </Button>
                </>
              )}
              <a className="btn btn-soft" href={detail.download_url}>
                <Download size={15} /> 下载原文件
              </a>
              <Button variant="ghost" icon={<Star size={15} />} onClick={() => void toggleFavorite(detail)}>
                {detail.favorite ? "取消收藏" : "收藏"}
              </Button>
              <Button variant="danger" icon={<Trash2 size={15} />} onClick={() => void remove(detail)}>
                删除
              </Button>
            </div>

            <VersionStrip
              assetId={detail.id}
              currentId={detail.id}
              onSelect={(item) => setDetail(item)}
              onCompare={(item) =>
                setCompare({
                  left: { url: item.url, label: `v${item.version}`, kind: "asset" },
                  right: { url: detail.url, label: `当前 v${detail.version}`, kind: "asset" },
                  mode: "selection",
                })
              }
            />
          </aside>
        </div>
      )}

      <CompareModal
        open={Boolean(compare)}
        onClose={() => setCompare(null)}
        left={compare?.left ?? null}
        right={compare?.right ?? null}
        alternatives={compare?.alternatives}
        initialMode={compare?.mode === "fidelity" ? "overlay" : "side"}
      />

      <InpaintModal
        open={Boolean(inpaintAsset)}
        asset={inpaintAsset}
        onClose={() => {
          setInpaintAsset(null);
          void load(0);
        }}
      />
      <RefineModal
        open={Boolean(refineAsset)}
        asset={refineAsset}
        onClose={() => {
          setRefineAsset(null);
          void load(0);
        }}
      />
      <GridSplitModal
        open={Boolean(splitAsset)}
        asset={splitAsset}
        onClose={() => setSplitAsset(null)}
        onDone={() => void load(0)}
      />
      <CharacterToolsModal
        open={Boolean(characterAsset)}
        asset={characterAsset}
        onClose={() => {
          setCharacterAsset(null);
          void load(0);
        }}
      />
    </>
  );
}
