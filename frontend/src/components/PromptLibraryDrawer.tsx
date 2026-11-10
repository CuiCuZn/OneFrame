import { useCallback, useEffect, useState } from "react";
import { Plus, Search, Star, Trash2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { PromptItem } from "../lib/types";
import { Badge, Button, Modal } from "./ui";

const CATEGORIES: { id: PromptItem["category"]; label: string }[] = [
  { id: "quality", label: "画质" },
  { id: "camera", label: "镜头" },
  { id: "lighting", label: "光线" },
  { id: "style", label: "风格" },
  { id: "custom", label: "自定义" },
];

export default function PromptLibraryDrawer({
  open,
  onClose,
  currentPrompt,
  onInsert,
}: {
  open: boolean;
  onClose: () => void;
  currentPrompt: string;
  onInsert: (text: string) => void;
}) {
  const { toast } = useStore();
  const [items, setItems] = useState<PromptItem[]>([]);
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [newCategory, setNewCategory] = useState<PromptItem["category"]>("custom");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.prompts.list({ category, q: query });
      setItems(data.items);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "提示词读取失败", "error");
    }
  }, [category, query, toast]);

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, load]);

  useEffect(() => {
    if (open) setText(currentPrompt);
  }, [open, currentPrompt]);

  const save = async () => {
    if (!title.trim() || !text.trim()) return toast("标题和内容都要填写", "error");
    setBusy(true);
    try {
      await api.prompts.create({
        title: title.trim(),
        category: newCategory,
        text: text.trim(),
      });
      setTitle("");
      toast("已保存到提示词库", "success");
      await load();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "保存失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const toggleFavorite = async (item: PromptItem) => {
    try {
      await api.prompts.favorite(item.id);
      await load();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "操作失败", "error");
    }
  };

  const remove = async (item: PromptItem) => {
    if (item.builtin) return;
    try {
      await api.prompts.remove(item.id);
      await load();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "删除失败", "error");
    }
  };

  return (
    <Modal
      open={open}
      title="提示词库"
      subtitle="常用画质、镜头、光线与风格片段，点击插入到当前提示词"
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <span className="grow" />
        </>
      }
    >
      <div className="prompt-library">
        <div className="prompt-library-head">
          <div className="search lib-search">
            <Search size={14} />
            <input
              className="input"
              placeholder="搜索标题、内容或标签"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="prompt-categories">
            <button className={`chip ${!category ? "is-active" : ""}`} onClick={() => setCategory("")}>
              全部
            </button>
            {CATEGORIES.map((item) => (
              <button
                key={item.id}
                className={`chip ${category === item.id ? "is-active" : ""}`}
                onClick={() => setCategory(category === item.id ? "" : item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="prompt-list">
          {items.map((item) => (
            <div className="prompt-card" key={item.id}>
              <div className="prompt-card-head">
                <strong>{item.title}</strong>
                <Badge>{CATEGORIES.find((entry) => entry.id === item.category)?.label ?? item.category}</Badge>
                {item.builtin && <Badge tone="neutral">内置</Badge>}
                <span className="grow" />
                <button
                  className={`icon-btn ${item.favorite ? "is-active" : ""}`}
                  onClick={() => void toggleFavorite(item)}
                  title="收藏"
                >
                  <Star size={13} fill={item.favorite ? "currentColor" : "none"} />
                </button>
                {!item.builtin && (
                  <button className="icon-btn" onClick={() => void remove(item)} title="删除">
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
              <p>{item.text}</p>
              <div className="prompt-card-actions">
                <Button size="sm" variant="soft" onClick={() => onInsert(item.text)}>
                  插入
                </Button>
              </div>
            </div>
          ))}
          {items.length === 0 && <p className="hint-block">没有匹配的提示词。</p>}
        </div>

        <div className="prompt-save">
          <div className="prompt-save-row">
            <input
              className="input"
              placeholder="标题"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
            <select
              className="select"
              value={newCategory}
              onChange={(event) => setNewCategory(event.target.value as PromptItem["category"])}
            >
              {CATEGORIES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <textarea
            className="input"
            rows={3}
            placeholder="提示词内容"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <Button variant="primary" size="sm" icon={<Plus size={14} />} loading={busy} onClick={() => void save()}>
            保存当前提示词
          </Button>
        </div>
      </div>
    </Modal>
  );
}
