import { useEffect, useState } from "react";
import { GitCompare } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Asset } from "../lib/types";

const TOOL_LABEL: Record<string, string> = {
  "": "原图",
  inpaint: "局部重绘",
  refine: "精修",
  extract_costume: "服饰提取",
  character: "角色工具",
  upscale: "放大",
  split: "拆分",
};

export default function VersionStrip({
  assetId,
  currentId,
  onSelect,
  onCompare,
}: {
  assetId: string;
  currentId: string;
  onSelect: (asset: Asset) => void;
  onCompare?: (asset: Asset) => void;
}) {
  const { toast } = useStore();
  const [items, setItems] = useState<Asset[]>([]);

  useEffect(() => {
    let alive = true;
    api.assets
      .versions(assetId)
      .then((data) => {
        if (alive) setItems(data.items);
      })
      .catch((error) => {
        if (alive && error instanceof ApiError) toast(error.message, "error");
      });
    return () => {
      alive = false;
    };
  }, [assetId, toast]);

  if (items.length <= 1) return null;

  return (
    <div className="version-strip-wrap">
      <span className="facet-label">版本</span>
      <div className="version-strip">
        {items.map((item) => (
          <div key={item.id} className={`version-item ${item.id === currentId ? "is-active" : ""}`}>
            <button type="button" onClick={() => onSelect(item)} title={`v${item.version} · ${TOOL_LABEL[item.tool] ?? item.tool}`}>
              <img src={item.thumb_url} alt="" loading="lazy" />
              <span>v{item.version}</span>
            </button>
            <em>{TOOL_LABEL[item.tool] ?? item.tool ?? "版本"}</em>
            {onCompare && item.id !== currentId && (
              <button type="button" className="version-compare" onClick={() => onCompare(item)} title="与当前版本对比">
                <GitCompare size={11} />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
