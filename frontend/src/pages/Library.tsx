import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ChevronRight,
  FolderInput,
  Heart,
  Images,
  Layers,
  Link2,
  Loader2,
  RefreshCw,
  RotateCcw,
  Search,
  Shirt,
  Star,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import { usePersistentState } from "../lib/hooks";
import type { Asset, LibraryFacets, LibraryItem, LibraryTree } from "../lib/types";
import CostumeExtractModal from "../components/CostumeExtractModal";
import {
  Badge,
  Button,
  Chip,
  EmptyState,
  Field,
  Modal,
  PageHead,
} from "../components/ui";

const KIND_LABEL: Record<string, string> = {
  pose: "姿势",
  costume: "服装",
  portrait: "人像",
  work: "作品",
  custom: "素材",
  upload: "上传",
  other: "其他",
};

const PAGE_SIZE = 48;
const DIM_PREVIEW = 14;

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export default function Library({ onUse }: { onUse: () => void }) {
  const { catalog, toast } = useStore();
  const [kind, setKind] = usePersistentState("of.lib.kind", "");
  const [favorite, setFavorite] = useState(false);
  const [depthOnly, setDepthOnly] = usePersistentState("of.lib.depth", false);
  const [query, setQuery] = useState("");
  const search = useDebounced(query, 260);
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [openDims, setOpenDims] = useState<Record<string, boolean>>({});
  const [closedKinds, setClosedKinds] = useState<Record<string, boolean>>({});
  const [openParents, setOpenParents] = useState<Record<string, boolean>>({});
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [facets, setFacets] = useState<LibraryFacets | null>(null);
  const [loading, setLoading] = useState(true);
  const [importOpen, setImportOpen] = useState(false);
  const [detail, setDetail] = useState<LibraryItem | null>(null);
  const [detailVariant, setDetailVariant] = useState<"base" | "depth">("base");
  const [variants, setVariants] = useState<LibraryItem[]>([]);
  const [urlOpen, setUrlOpen] = useState(false);
  const [urlValue, setUrlValue] = useState("");
  const [urlBusy, setUrlBusy] = useState(false);
  const [costumeOpen, setCostumeOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);

  const listReq = useRef(0);
  const facetReq = useRef(0);

  const selectedList = useMemo(
    () =>
      Object.entries(selected).flatMap(([field, values]) =>
        values.map((value) => `${field}:${value}`),
      ),
    [selected],
  );
  const selectedCount = useMemo(
    () => Object.values(selected).reduce((sum, values) => sum + values.length, 0),
    [selected],
  );

  const load = useCallback(
    async (nextOffset = 0) => {
      const request = ++listReq.current;
      setLoading(true);
      try {
        const data = await api.library.list({
          kind,
          q: search,
          favorite: favorite || undefined,
          facets: selectedList,
          depth: depthOnly || undefined,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        if (request !== listReq.current) return;
        setItems((current) => (nextOffset === 0 ? data.items : [...current, ...data.items]));
        setTotal(data.total);
        setOffset(nextOffset);
      } catch (error) {
        if (request === listReq.current) {
          toast(error instanceof ApiError ? error.message : "读取失败", "error");
        }
      } finally {
        if (request === listReq.current) setLoading(false);
      }
    },
    [kind, search, favorite, depthOnly, selectedList, toast],
  );

  const loadFacets = useCallback(async () => {
    const request = ++facetReq.current;
    try {
      const data = await api.library.facets({
        kind,
        q: search,
        favorite: favorite || undefined,
        facets: selectedList,
      });
      if (request === facetReq.current) setFacets(data);
    } catch {
      /* ignore, the grid still works */
    }
  }, [kind, search, favorite, selectedList]);

  useEffect(() => {
    void load(0);
  }, [load]);

  useEffect(() => {
    void loadFacets();
  }, [loadFacets]);

  useEffect(() => {
    if (!detail) {
      setVariants([]);
      setDetailVariant("base");
      return;
    }
    let alive = true;
    setDetailVariant("base");
    api.library
      .variants(detail.id)
      .then((data) => {
        if (alive) setVariants(data.items);
      })
      .catch(() => {
        if (alive) setVariants([detail]);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.id]);

  const useItem = (item: LibraryItem, role: string, variant: "base" | "depth" = "base") => {
    window.localStorage.setItem("of.pendingRef", JSON.stringify({ item, role, variant }));
    setDetail(null);
    toast(`已作为「${catalog?.roles.find((r) => r.id === role)?.name ?? role}」带入创作台`, "success");
    onUse();
  };

  const toggleFavorite = async (item: LibraryItem) => {
    const next = !item.favorite;
    await api.library.patch(item.id, { favorite: next });
    setItems((current) =>
      current.map((row) => (row.id === item.id ? { ...row, favorite: next ? 1 : 0 } : row)),
    );
    if (detail?.id === item.id) setDetail({ ...detail, favorite: next ? 1 : 0 });
    void loadFacets();
  };

  const removeItem = async (item: LibraryItem) => {
    if (!window.confirm("从参考库移除这条素材？（不会删除磁盘上的原文件）")) return;
    await api.library.remove(item.id);
    setItems((current) => current.filter((row) => row.id !== item.id));
    setDetail(null);
    toast("已移除");
    void loadFacets();
  };

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      const data = await api.library.upload(Array.from(files), "custom");
      toast(`已加入 ${data.items.length} 张参考图`, "success");
      await load(0);
      await loadFacets();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "上传失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const importFromUrl = async () => {
    const value = urlValue.trim();
    if (!value) return toast("先填写图片地址", "error");
    setUrlBusy(true);
    try {
      const asset = await api.assets.importUrl(value);
      const result = await api.library.fromAsset(asset.id);
      toast(result.created ? "已从 URL 导入参考库" : "这张图已经在参考库里了", result.created ? "success" : "info");
      setUrlOpen(false);
      setUrlValue("");
      await Promise.all([load(0), loadFacets()]);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "URL 导入失败", "error");
    } finally {
      setUrlBusy(false);
    }
  };

  const addExtractedToLibrary = async (asset: Pick<Asset, "id" | "thumb_url" | "url" | "prompt">) => {
    try {
      const result = await api.library.fromAsset(asset.id);
      toast(result.created ? "提取结果已存入参考库" : "提取结果已经在参考库里了", result.created ? "success" : "info");
      await Promise.all([load(0), loadFacets()]);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "存入参考库失败", "error");
    }
  };

  const pickKind = (next: string) => {
    setKind(next);
    setSelected({});
    if (next) setClosedKinds((current) => ({ ...current, [next]: false }));
  };

  const toggleKind = (value: string, open: boolean) => {
    setClosedKinds((current) => ({ ...current, [value]: open }));
  };

  const toggleValue = (field: string, value: string) => {
    setSelected((current) => {
      const values = current[field] ?? [];
      const nextValues = values.includes(value)
        ? values.filter((entry) => entry !== value)
        : [...values, value];
      const next = { ...current };
      if (nextValues.length) next[field] = nextValues;
      else delete next[field];
      return next;
    });
  };

  const pickTreeValue = (tree: LibraryTree, field: string, value: string) => {
    const switching = tree.kind !== kind;
    const currentParent = switching ? "" : (selected[tree.fields.level1] ?? [])[0] ?? "";
    const parent =
      field === tree.fields.level2
        ? (tree.children.find(
            (node) => node.value === currentParent && node.children.some((child) => child.value === value),
          ) ?? tree.children.find((node) => node.children.some((child) => child.value === value)))
        : undefined;
    setSelected((current) => {
      const base = switching ? {} : current;
      const active =
        !switching && (current[field] ?? []).length === 1 && current[field]?.[0] === value;
      const next = { ...base };
      if (field === tree.fields.level1) {
        delete next[tree.fields.level2];
        if (active) delete next[field];
        else next[field] = [value];
      } else if (parent) {
        // A sub-category always implies its parent, so keep both levels.
        next[tree.fields.level1] = [parent.value];
        if (active) delete next[field];
        else next[field] = [value];
      } else {
        delete next[field];
        if (!active) next[field] = [value];
      }
      return next;
    });
    if (switching) setKind(tree.kind);
    setClosedKinds((current) => ({ ...current, [tree.kind]: false }));

    const key = `${tree.kind}|${parent?.value ?? value}`;
    setOpenParents((current) => ({ ...current, [key]: true }));
  };

  const clearFilters = () => {
    setQuery("");
    setFavorite(false);
    setDepthOnly(false);
    setSelected({});
  };

  const breadcrumb = useMemo(() => {
    const tree = facets?.tree.find((entry) => entry.kind === kind);
    if (!tree) return "";
    const parts = [tree.label];
    for (const field of [tree.fields.level1, tree.fields.level2]) {
      const values = selected[field] ?? [];
      if (values.length) parts.push(...values);
    }
    return parts.join(" / ");
  }, [facets, kind, selected]);

  return (
    <>
      <PageHead
        eyebrow="References"
        title="参考库"
        description="姿势、服装、人像与自己的素材放在一起。分类可以一层层点开，也可以直接搜关键词。这里只索引本地文件，不会把你的素材上传到任何地方。"
        actions={
          <>
            <Button variant="soft" icon={<FolderInput size={15} />} onClick={() => setImportOpen(true)}>
              导入文件夹
            </Button>
            <Button variant="ghost" icon={<Link2 size={15} />} onClick={() => setUrlOpen(true)}>
              从 URL 导入
            </Button>
            <Button variant="ghost" icon={<Shirt size={15} />} onClick={() => setCostumeOpen(true)}>
              提取服饰
            </Button>
            <label className="btn btn-primary btn-md" style={{ cursor: "pointer" }}>
              <Upload size={15} />
              <span>上传参考</span>
              <input
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(event) => {
                  void upload(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
          </>
        }
      />

      {facets && facets.grand_total > 0 ? (
        <div className="lib-layout">
          <aside className="lib-side">
            <div className="lib-side-head">
              <div className="search lib-search">
                <Search size={14} />
                <input
                  className="input"
                  placeholder="搜标题、编号或标签"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
                {query && (
                  <button className="lib-search-clear" onClick={() => setQuery("")} aria-label="清空搜索">
                    <X size={13} />
                  </button>
                )}
              </div>
            </div>

            <div className="lib-side-scroll">
              <button
                className={`lib-kind ${!kind ? "is-active" : ""}`}
                onClick={() => pickKind("")}
              >
                <Images size={13} />
                <span>全部素材</span>
                <em>{facets.visible_total}</em>
              </button>
              <button
                className={`lib-kind ${favorite ? "is-active" : ""}`}
                onClick={() => setFavorite((value) => !value)}
              >
                <Heart size={13} />
                <span>收藏</span>
                <em>{facets.favorite}</em>
              </button>
              <button
                className={`lib-kind ${depthOnly ? "is-active" : ""}`}
                onClick={() => setDepthOnly((value) => !value)}
              >
                <Layers size={13} />
                <span>有深度图</span>
                <em>{facets.depth_total}</em>
              </button>

              <div className="lib-side-title">按分类浏览</div>

              {facets.tree.map((tree) => {
                const open = !closedKinds[tree.kind];
                return (
                  <div className="lib-tree" key={tree.kind}>
                    <div className={`lib-tree-head ${kind === tree.kind ? "is-active" : ""}`}>
                      {tree.children.length > 0 ? (
                        <button
                          type="button"
                          className={`lib-twist ${open ? "is-open" : ""}`}
                          onClick={() => toggleKind(tree.kind, open)}
                          aria-label={`${open ? "收起" : "展开"}${tree.label}`}
                          aria-expanded={open}
                        >
                          <ChevronRight size={12} />
                        </button>
                      ) : (
                        <span className="lib-twist is-empty" />
                      )}
                      <button
                        type="button"
                        className="lib-tree-label"
                        onClick={() => pickKind(tree.kind)}
                      >
                        <span>{tree.label}</span>
                        <em>{tree.count}</em>
                      </button>
                    </div>

                    {open &&
                      tree.children.map((parent) => {
                        const parentActive = (selected[tree.fields.level1] ?? []).includes(parent.value);
                        const childActive = parent.children.some((child) =>
                          (selected[tree.fields.level2] ?? []).includes(child.value),
                        );
                        const parentKey = `${tree.kind}|${parent.value}`;
                        const parentOpen = openParents[parentKey] ?? parentActive;
                        return (
                          <div className="lib-node" key={parent.value}>
                            <div
                              className={`lib-node-row ${parentActive ? "is-active" : ""} ${
                                childActive ? "has-active" : ""
                              }`}
                            >
                              {parent.children.length > 0 ? (
                                <button
                                  type="button"
                                  className={`lib-twist ${parentOpen ? "is-open" : ""}`}
                                  onClick={() =>
                                    setOpenParents((current) => ({
                                      ...current,
                                      [parentKey]: !parentOpen,
                                    }))
                                  }
                                  aria-label={`${parentOpen ? "收起" : "展开"}${parent.value}`}
                                  aria-expanded={parentOpen}
                                >
                                  <ChevronRight size={11} />
                                </button>
                              ) : (
                                <span className="lib-twist is-empty" />
                              )}
                              <button
                                type="button"
                                className="lib-node-label"
                                onClick={() => pickTreeValue(tree, tree.fields.level1, parent.value)}
                              >
                                <span>{parent.value}</span>
                                <em>{parent.count}</em>
                              </button>
                            </div>
                            {parentOpen && parent.children.length > 0 && (
                              <div className="lib-leaves">
                                {parent.children.map((child) => {
                                  const childActive = (selected[tree.fields.level2] ?? []).includes(
                                    child.value,
                                  );
                                  return (
                                    <button
                                      type="button"
                                      key={child.value}
                                      className={`lib-leaf ${childActive ? "is-active" : ""}`}
                                      onClick={() => pickTreeValue(tree, tree.fields.level2, child.value)}
                                    >
                                      <span>{child.value}</span>
                                      <em>{child.count}</em>
                                    </button>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        );
                      })}
                  </div>
                );
              })}
            </div>
            {facets.nsfw_hidden > 0 && (
              <div className="lib-nsfw-note">
                <span>已隐藏 {facets.nsfw_hidden} 条 NSFW 素材</span>
                <a href="#/settings">去开启</a>
              </div>
            )}
          </aside>

          <div className="lib-main">
            {(facets.dims.length > 0 || selectedCount > 0 || query) && (
              <div className="lib-facet-bar">
                {facets.dims.map((dim) => {
                  const values = openDims[dim.field] ? dim.values : dim.values.slice(0, DIM_PREVIEW);
                  const hidden = dim.values.length - values.length;
                  return (
                    <div className="facet-row" key={dim.field}>
                      <span className="facet-label">{dim.field}</span>
                      <div className="facet-values">
                        {values.map((entry) => (
                          <Chip
                            key={entry.value}
                            active={(selected[dim.field] ?? []).includes(entry.value)}
                            onClick={() => toggleValue(dim.field, entry.value)}
                          >
                            {entry.value} <span className="faint">{entry.count}</span>
                          </Chip>
                        ))}
                        {(hidden > 0 || openDims[dim.field]) && (
                          <button
                            className="facet-more"
                            onClick={() =>
                              setOpenDims((current) => ({ ...current, [dim.field]: !current[dim.field] }))
                            }
                          >
                            {openDims[dim.field] ? "收起" : `+${hidden}`}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="lib-result-head">
              <span className="faint">
                {loading && items.length === 0 ? "读取中…" : `${total} 条素材`}
              </span>
              {breadcrumb && <span className="lib-crumb">{breadcrumb}</span>}
              <div className="spacer" />
              {(selectedCount > 0 || favorite || query) && (
                <button className="lib-reset" onClick={clearFilters}>
                  <RotateCcw size={12} /> 清除筛选
                </button>
              )}
            </div>

            {loading && items.length === 0 ? (
              <div className="loading-row">
                <Loader2 size={16} className="spin" /> 正在读取…
              </div>
            ) : items.length === 0 ? (
              <div className="panel">
                <EmptyState
                  icon={<Images size={20} />}
                  title="没有匹配的素材"
                  description="换个关键词或分类，也可以导入新的文件夹。多个关键词用空格分隔。"
                  action={
                    <Button variant="soft" onClick={clearFilters} icon={<RotateCcw size={15} />}>
                      清除筛选
                    </Button>
                  }
                />
              </div>
            ) : (
              <>
                <div className="lib-grid">
                  {items.map((item) => (
                    <div className="lib-card" key={item.id} onClick={() => setDetail(item)}>
                      <img src={item.thumb_url} alt={item.title} loading="lazy" />
                      {Boolean(item.has_depth) && <span className="lib-depth-badge">深度</span>}
                      <button
                        className={`lib-fav ${item.favorite ? "is-on" : ""}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          void toggleFavorite(item);
                        }}
                        title={item.favorite ? "取消收藏" : "收藏"}
                      >
                        <Star size={13} fill={item.favorite ? "currentColor" : "none"} />
                      </button>
                      <button
                        className="lib-use"
                        onClick={(event) => {
                          event.stopPropagation();
                          useItem(item, "reference");
                        }}
                      >
                        用作参考 <ArrowRight size={12} />
                      </button>
                      <div className="lib-info">
                        <strong>{item.title || "未命名素材"}</strong>
                        <em>
                          {item.category_path ||
                            item.category ||
                            KIND_LABEL[item.kind] ||
                            item.kind}
                        </em>
                      </div>
                    </div>
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
          </div>
        </div>
      ) : facets ? (
        <div className="onboard-grid">
          <div className="onboard-card">
            <span className="onboard-step">01</span>
            <h3>索引姿势图库</h3>
            <p>指向你本地的 ai-pose-gallery-zh 仓库根目录，一次读入姿势、服装与人像三套索引。</p>
            <Button variant="primary" size="sm" icon={<FolderInput size={14} />} onClick={() => setImportOpen(true)}>
              选择目录
            </Button>
          </div>
          <div className="onboard-card">
            <span className="onboard-step">02</span>
            <h3>收纳自己的素材</h3>
            <p>任意文件夹都能递归索引，按子目录归类；只生成缩略图，不复制原文件。</p>
            <Button variant="soft" size="sm" icon={<FolderInput size={14} />} onClick={() => setImportOpen(true)}>
              导入文件夹
            </Button>
          </div>
          <div className="onboard-card">
            <span className="onboard-step">03</span>
            <h3>临时上传几张</h3>
            <p>拖入或选择图片，立刻作为人物 / 服装 / 姿势 / 风格参考带进创作台。</p>
            <label className="btn btn-soft btn-sm" style={{ cursor: "pointer" }}>
              <Upload size={14} />
              <span>上传参考</span>
              <input
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(event) => {
                  void upload(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
          </div>
        </div>
      ) : (
        <div className="loading-row">
          <Loader2 size={16} className="spin" /> 正在读取…
        </div>
      )}

      <ImportModal
        open={importOpen}
        roots={facets?.roots ?? []}
        onClose={() => setImportOpen(false)}
        onImported={async () => {
          await Promise.all([load(0), loadFacets()]);
        }}
        onReclassified={async (message) => {
          toast(message, "success");
          setSelected({});
          await Promise.all([load(0), loadFacets()]);
        }}
      />

      <Modal
        open={urlOpen}
        title="从 URL 导入参考"
        subtitle="只支持 http/https 图片，单张不超过 25MB；内网地址会被拒绝"
        onClose={() => setUrlOpen(false)}
        width={520}
        footer={
          <>
            <Button variant="ghost" onClick={() => setUrlOpen(false)}>
              取消
            </Button>
            <Button variant="primary" loading={urlBusy} onClick={() => void importFromUrl()}>
              导入
            </Button>
          </>
        }
      >
        <input
          className="input"
          value={urlValue}
          onChange={(event) => setUrlValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void importFromUrl();
          }}
          placeholder="https://example.com/reference.png"
          autoFocus
        />
      </Modal>

      <CostumeExtractModal
        open={costumeOpen}
        onClose={() => setCostumeOpen(false)}
        onUse={(asset) => void addExtractedToLibrary(asset)}
      />

      {detail && (
        <Modal
          open
          title={detail.title || "素材详情"}
          subtitle={detail.category_path || detail.category || KIND_LABEL[detail.kind]}
          onClose={() => setDetail(null)}
          width={780}
          footer={
            <>
              <Button
                variant="ghost"
                icon={<Star size={15} />}
                onClick={() => void toggleFavorite(detail)}
              >
                {detail.favorite ? "取消收藏" : "收藏"}
              </Button>
              <Button variant="danger" icon={<Trash2 size={15} />} onClick={() => void removeItem(detail)}>
                移除
              </Button>
              <span className="grow" />
              {(catalog?.roles ?? []).map((role) => (
                <Button key={role.id} variant="soft" onClick={() => useItem(detail, role.id, detailVariant)}>
                  用作{role.name}
                </Button>
              ))}
            </>
          }
        >
          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
            <img
              src={detailVariant === "depth" && detail.depth_url ? detail.depth_url : detail.url}
              alt=""
              style={{ maxHeight: 420, maxWidth: "58%", borderRadius: 12, objectFit: "contain", background: "#0b0d10" }}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1, minWidth: 0 }}>
              <div className="kv">
                <b>来源</b>
                <span>{detail.source.split(":")[0]}</span>
                <b>编号</b>
                <span className="mono">{detail.external_id || detail.id.slice(0, 8)}</span>
                <b>尺寸</b>
                <span>{detail.width && detail.height ? `${detail.width} × ${detail.height}` : "—"}</span>
                <b>分类</b>
                <span>{detail.category_path || detail.category || "—"}</span>
                {detail.variant_label && (
                  <>
                    <b>视角</b>
                    <span>{detail.variant_label}</span>
                  </>
                )}
              </div>
              {Boolean(detail.has_depth) && (
                <Button
                  variant="soft"
                  size="sm"
                  icon={<Layers size={14} />}
                  onClick={() => setDetailVariant((value) => (value === "depth" ? "base" : "depth"))}
                >
                  {detailVariant === "depth" ? "查看白模" : "查看深度图"}
                </Button>
              )}
              {Object.keys(detail.facets ?? {}).length > 0 ? (
                <div className="detail-facets">
                  {Object.entries(detail.facets).map(([field, values]) => (
                    <div className="detail-facet" key={field}>
                      <span className="facet-label">{field}</span>
                      <div className="facet-values">
                        {values.map((value) => (
                          <Badge key={value}>{value}</Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {detail.tags
                    .split(/\s+/)
                    .filter(Boolean)
                    .slice(0, 12)
                    .map((tag) => (
                      <Badge key={tag}>{tag}</Badge>
                    ))}
                </div>
              )}
              <p className="hint-block">
                选择用途后会把这张图带入创作台；用「编排参考提示词」可以生成“图1=人物、图2=服装”的明确指令。
              </p>
            </div>
          </div>
          {variants.length > 1 && (
            <div className="detail-variants">
              <span className="facet-label">视角</span>
              <div className="detail-variant-strip">
                {variants.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`detail-variant ${item.id === detail.id ? "is-active" : ""}`}
                    onClick={() => setDetail(item)}
                    title={item.variant_label || item.title}
                  >
                    <img src={item.thumb_url} alt="" loading="lazy" />
                    <span>{item.variant_label || "视角"}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </Modal>
      )}
    </>
  );
}

function ImportModal({
  open,
  roots,
  onClose,
  onImported,
  onReclassified,
}: {
  open: boolean;
  roots: string[];
  onClose: () => void;
  onImported: () => Promise<void>;
  onReclassified: (message: string) => Promise<void>;
}) {
  const { toast } = useStore();
  const [mode, setMode] = useState<"pose_gallery" | "folder">("pose_gallery");
  const [path, setPath] = useState("");
  const [kind, setKind] = useState("other");
  const [busy, setBusy] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [report, setReport] = useState<{
    added: number;
    updated?: number;
    scanned: number;
    skipped_remote?: number;
    skipped_missing?: number;
    depth_added?: number;
  } | null>(null);

  const run = async () => {
    if (!path.trim()) return toast("请填写本地路径", "error");
    setBusy(true);
    try {
      const result = await api.library.import(mode, path.trim(), kind);
      setReport(result);
      await onImported();
      toast(`已索引 ${result.added} 条素材`, "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "导入失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const reclassify = async () => {
    setRebuilding(true);
    try {
      const result = await api.library.reclassify();
      await onReclassified(`已重新整理 ${result.items} 条素材的分类`);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "整理失败", "error");
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <Modal
      open={open}
      title="导入参考素材"
      subtitle="只读取本地文件并生成缩略图，不复制、不上传"
      onClose={onClose}
      width={620}
      footer={
        <>
          <Button variant="ghost" icon={<RefreshCw size={14} />} loading={rebuilding} onClick={() => void reclassify()}>
            重新整理分类
          </Button>
          <span className="grow" />
          <Button variant="ghost" onClick={onClose}>
            {report ? "完成" : "取消"}
          </Button>
          {!report && (
            <Button variant="primary" loading={busy} onClick={() => void run()}>
              开始索引
            </Button>
          )}
        </>
      }
    >
      <div className="protocol-grid">
        <button
          className={`protocol-option ${mode === "pose_gallery" ? "is-active" : ""}`}
          onClick={() => setMode("pose_gallery")}
        >
          <strong>姿势图库仓库</strong>
          <em>读取姿势 / 服装 / 人像 / 中国历代服饰索引，并关联本地深度图</em>
        </button>
        <button
          className={`protocol-option ${mode === "folder" ? "is-active" : ""}`}
          onClick={() => setMode("folder")}
        >
          <strong>任意文件夹</strong>
          <em>递归索引图片，按子目录归类，适合自己的素材集</em>
        </button>
      </div>

      <Field label="本地路径" hint="绝对路径，或在允许目录内">
        <input
          className="input"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder="D:\\refs\\ai-pose-gallery-zh"
        />
      </Field>

      {mode === "folder" && (
        <Field label="归类">
          <select className="select" value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="other">其他</option>
            <option value="pose">姿势</option>
            <option value="costume">服装</option>
            <option value="portrait">人像</option>
            <option value="custom">自定义</option>
          </select>
        </Field>
      )}

      {report && (
        <div className="import-report">
          <div className="import-report-grid">
            <span>新增</span><strong>{report.added}</strong>
            <span>更新</span><strong>{report.updated ?? 0}</strong>
            <span>扫描</span><strong>{report.scanned}</strong>
            <span>深度图</span><strong>{report.depth_added ?? 0}</strong>
            <span>远程跳过</span><strong>{report.skipped_remote ?? 0}</strong>
            <span>文件缺失</span><strong>{report.skipped_missing ?? 0}</strong>
          </div>
          {Boolean(report.skipped_remote) && (
            <p className="hint-block">
              远程热链素材未下载、未写入索引。需要时请把原图下载到本地文件夹，再按「任意文件夹」导入。
            </p>
          )}
        </div>
      )}

      <div className="hint-block">
        允许读取的目录：
        <br />
        {roots.map((root) => (
          <span key={root} className="mono" style={{ display: "block", marginTop: 4 }}>
            {root}
          </span>
        ))}
        <br />
        需要索引其它磁盘时，设置环境变量 <span className="mono">ONEFRAME_LIBRARY_ROOTS</span>（多个目录用分号分隔）后重启。
      </div>

      <p className="hint-block">
        提示：两个参考图库的图片版权归原作者，仓库授权不覆盖再分发。本功能只索引你本机已有的副本，平台不会打包或公开这些图片。
      </p>
    </Modal>
  );
}
