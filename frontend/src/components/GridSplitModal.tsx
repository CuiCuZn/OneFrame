import { useEffect, useMemo, useState } from "react";
import { Check, Grid2X2, Loader2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Asset, JobAsset } from "../lib/types";
import { Button, Modal } from "./ui";

export default function GridSplitModal({
  open,
  asset,
  onClose,
  onDone,
}: {
  open: boolean;
  asset: Asset | JobAsset | null;
  onClose: () => void;
  onDone?: () => void;
}) {
  const { toast } = useStore();
  const [rows, setRows] = useState(2);
  const [columns, setColumns] = useState(2);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Asset[]>([]);

  const total = rows * columns;
  const all = useMemo(() => Array.from({ length: total }, (_, index) => index), [total]);

  useEffect(() => {
    if (!open) return;
    setRows(2);
    setColumns(2);
    setSelected([0, 1, 2, 3]);
    setResults([]);
  }, [open, asset?.id]);

  useEffect(() => {
    setSelected(all);
  }, [all]);

  const toggle = (index: number) => {
    setSelected((current) =>
      current.includes(index) ? current.filter((item) => item !== index) : [...current, index].sort((a, b) => a - b),
    );
  };

  const submit = async () => {
    if (!asset) return;
    if (!selected.length) return toast("至少选择一个格子", "error");
    setBusy(true);
    try {
      const data = await api.assets.split(asset.id, {
        rows,
        columns,
        cells: selected,
      });
      setResults(data.items);
      onDone?.();
      toast(`已拆出 ${data.items.length} 张素材`, "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "拆分失败", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="宫格拆分"
      subtitle="按行列无损裁切，每个格子生成一张独立素材"
      onClose={onClose}
      width={780}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <span className="grow" />
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            拆分选中格子
          </Button>
        </>
      }
    >
      {!asset ? null : (
        <div className="split-layout">
          <div
            className="split-preview"
            style={{ backgroundImage: `url(${asset.url})` }}
          >
            <div
              className="split-grid"
              style={{ gridTemplateColumns: `repeat(${columns}, 1fr)`, gridTemplateRows: `repeat(${rows}, 1fr)` }}
            >
              {all.map((index) => (
                <button
                  key={index}
                  type="button"
                  className={`split-cell ${selected.includes(index) ? "is-on" : ""}`}
                  onClick={() => toggle(index)}
                  title={selected.includes(index) ? "取消这一格" : "选择这一格"}
                >
                  {selected.includes(index) && <Check size={14} />}
                </button>
              ))}
            </div>
          </div>
          <div className="split-side">
            <span className="tool-label">行列</span>
            <div className="split-controls">
              <select className="select" value={rows} onChange={(event) => setRows(Number(event.target.value))}>
                {[1, 2, 3, 4].map((value) => (
                  <option key={value} value={value}>
                    {value} 行
                  </option>
                ))}
              </select>
              <select className="select" value={columns} onChange={(event) => setColumns(Number(event.target.value))}>
                {[1, 2, 3, 4].map((value) => (
                  <option key={value} value={value}>
                    {value} 列
                  </option>
                ))}
              </select>
            </div>
            <span className="hint-block">
              已选 {selected.length} / {total} 格；点击预览格子可取消或选中。
            </span>
            {results.length > 0 && (
              <div className="split-results">
                {results.map((item) => (
                  <a key={item.id} href={item.url} target="_blank" rel="noreferrer">
                    <img src={item.thumb_url} alt="" />
                  </a>
                ))}
              </div>
            )}
            {!results.length && (
              <div className="tool-hint">
                <Grid2X2 size={14} /> 拆分不调用上游，不计费；结果会出现在作品库。
              </div>
            )}
            {busy && (
              <div className="tool-hint">
                <Loader2 size={14} className="spin" /> 正在裁切…
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
