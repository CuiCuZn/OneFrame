import { useEffect, useMemo, useRef, useState } from "react";
import { Move, RotateCcw, SlidersHorizontal } from "lucide-react";
import { Button, Modal, Segmented } from "./ui";

export interface CompareSource {
  url: string;
  label: string;
  kind?: "generated" | "reference" | "asset";
  missing?: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  left: CompareSource | null;
  right: CompareSource | null;
  alternatives?: CompareSource[];
  initialMode?: "side" | "overlay";
}

type Transform = { scale: number; x: number; y: number };

const IDENTITY: Transform = { scale: 1, x: 0, y: 0 };

export default function CompareModal({
  open,
  onClose,
  left,
  right,
  alternatives,
  initialMode = "side",
}: Props) {
  const [mode, setMode] = useState<"side" | "overlay">(initialMode);
  const [position, setPosition] = useState(50);
  const [top, setTop] = useState<Transform>(IDENTITY);
  const [dragging, setDragging] = useState(false);
  const [rightIndex, setRightIndex] = useState(0);
  const dragStart = useRef<{ x: number; y: number; origin: Transform } | null>(null);

  useEffect(() => {
    if (!open) return;
    setMode(initialMode);
    setPosition(50);
    setTop(IDENTITY);
    setDragging(false);
    setRightIndex(0);
  }, [open, initialMode, left?.url, right?.url]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (mode !== "overlay") return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setPosition((value) => Math.max(0, value - 2));
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setPosition((value) => Math.min(100, value + 2));
      } else if (event.key === "Home") {
        event.preventDefault();
        setPosition(0);
      } else if (event.key === "End") {
        event.preventDefault();
        setPosition(100);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, mode, onClose]);

  const activeRight = alternatives?.[rightIndex] ?? right;
  const available = useMemo(
    () => Boolean(left?.url && activeRight?.url),
    [left, activeRight],
  );

  if (!left || !activeRight) return null;

  const beginDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (mode !== "overlay" || !available) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStart.current = { x: event.clientX, y: event.clientY, origin: top };
    setDragging(true);
  };

  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return;
    const start = dragStart.current;
    setTop({
      ...start.origin,
      x: start.origin.x + (event.clientX - start.x),
      y: start.origin.y + (event.clientY - start.y),
    });
  };

  const endDrag = () => {
    dragStart.current = null;
    setDragging(false);
  };

  const zoom = (event: React.WheelEvent<HTMLDivElement>) => {
    if (mode !== "overlay") return;
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.08 : 0.92;
    setTop((value) => ({
      ...value,
      scale: Math.min(4, Math.max(0.4, Number((value.scale * factor).toFixed(3)))),
    }));
  };

  return (
    <Modal
      open={open}
      title="对比工作台"
      subtitle={
        mode === "overlay"
          ? "拖动上层图片或滚轮缩放，对齐后看贴合度；滑杆控制显示范围"
          : "并排查看两张图，适合比较不同模型或不同版本"
      }
      onClose={onClose}
      width={1120}
      footer={
        <>
          <Segmented
            value={mode}
            onChange={(value) => setMode(value)}
            options={[
              { value: "side", label: "并排" },
              { value: "overlay", label: "叠加" },
            ]}
          />
          <span className="grow" />
          {mode === "overlay" && (
            <Button
              variant="ghost"
              icon={<RotateCcw size={14} />}
              onClick={() => setTop(IDENTITY)}
            >
              重置对齐
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
        </>
      }
    >
      {alternatives && alternatives.length > 1 && (
        <div className="compare-alts">
          <span className="facet-label">参考</span>
          {alternatives.map((item, index) => (
            <button
              key={`${item.url}-${index}`}
              className={`chip ${index === rightIndex ? "is-active" : ""}`}
              onClick={() => setRightIndex(index)}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
      {!available ? (
        <div className="compare-missing">
          <SlidersHorizontal size={20} />
          <p>{left.missing || activeRight.missing ? "有一张参考图已丢失，无法对比。" : "缺少对比图片。"}</p>
        </div>
      ) : mode === "side" ? (
        <div className="compare-side">
          <figure>
            <div className="compare-image-box">
              <img src={left.url} alt={left.label} />
            </div>
            <figcaption>{left.label}</figcaption>
          </figure>
          <figure>
            <div className="compare-image-box">
              <img src={activeRight.url} alt={activeRight.label} />
            </div>
            <figcaption>{activeRight.label}</figcaption>
          </figure>
        </div>
      ) : (
        <>
          <div
            className={`compare-overlay ${dragging ? "is-dragging" : ""}`}
            onPointerDown={beginDrag}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onWheel={zoom}
          >
            <img className="compare-base" src={activeRight.url} alt={activeRight.label} />
            <img
              className="compare-top"
              src={left.url}
              alt={left.label}
              style={{
                clipPath: `inset(0 ${100 - position}% 0 0)`,
                transform: `translate(${top.x}px, ${top.y}px) scale(${top.scale})`,
              }}
            />
            <div className="compare-divider" style={{ left: `${position}%` }} />
            <span className="compare-label compare-label-left">{left.label}</span>
            <span className="compare-label compare-label-right">{activeRight.label}</span>
            <span className="compare-hint">
              <Move size={12} /> 拖拽上层 / 滚轮缩放
            </span>
          </div>
          <div className="compare-slider">
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={position}
              onChange={(event) => setPosition(Number(event.target.value))}
            />
            <span>{position}%</span>
          </div>
        </>
      )}
    </Modal>
  );
}
