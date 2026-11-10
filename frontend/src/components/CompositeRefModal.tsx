import { useEffect, useRef, useState } from "react";
import { Download, ImagePlus, Loader2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { Asset } from "../lib/types";
import { Button, Modal } from "./ui";

export interface CompositeSource {
  role: string;
  label: string;
  url: string;
}

const WIDTH = 1800;
const HEIGHT = 1200;

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("图片加载失败"));
    image.src = url;
  });
}

function cover(context: CanvasRenderingContext2D, image: HTMLImageElement, x: number, y: number, w: number, h: number) {
  const scale = Math.max(w / image.width, h / image.height);
  const width = image.width * scale;
  const height = image.height * scale;
  context.drawImage(image, x + (w - width) / 2, y + (h - height) / 2, width, height);
}

export default function CompositeRefModal({
  open,
  sources,
  onClose,
  onUse,
}: {
  open: boolean;
  sources: CompositeSource[];
  onClose: () => void;
  onUse: (asset: Pick<Asset, "id" | "thumb_url" | "url" | "prompt">) => void;
}) {
  const { toast } = useStore();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    let alive = true;
    setReady(false);
    context.fillStyle = "#111";
    context.fillRect(0, 0, WIDTH, HEIGHT);
    const items = sources.slice(0, 3);
    const slotWidth = WIDTH / Math.max(items.length, 1);
    Promise.all(items.map((item) => loadImage(item.url).catch(() => null)))
      .then((images) => {
        if (!alive) return;
        images.forEach((image, index) => {
          const x = index * slotWidth;
          if (image) {
            context.save();
            context.beginPath();
            context.rect(x, 0, slotWidth, HEIGHT);
            context.clip();
            cover(context, image, x, 0, slotWidth, HEIGHT);
            context.restore();
          }
          if (index > 0) {
            context.fillStyle = "rgba(255,255,255,0.7)";
            context.fillRect(x - 1, 0, 2, HEIGHT);
          }
          context.fillStyle = "rgba(0,0,0,0.55)";
          context.fillRect(x + 16, HEIGHT - 70, 200, 46);
          context.fillStyle = "#fff";
          context.font = "28px sans-serif";
          context.fillText(items[index].label, x + 30, HEIGHT - 38);
        });
        setReady(true);
      })
      .catch(() => {
        if (alive) toast("参考图加载失败", "error");
      });
    return () => {
      alive = false;
    };
  }, [open, sources, toast]);

  const blob = () =>
    new Promise<Blob | null>((resolve) => {
      canvasRef.current?.toBlob((value) => resolve(value), "image/png");
    });

  const download = async () => {
    const value = await blob();
    if (!value) return;
    const url = URL.createObjectURL(value);
    const link = document.createElement("a");
    link.href = url;
    link.download = `oneframe-references-${Date.now()}.png`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const useAsReference = async () => {
    setBusy(true);
    try {
      const value = await blob();
      if (!value) throw new Error("拼图生成失败");
      const file = new File([value], "oneframe-composite.png", { type: "image/png" });
      const uploaded = await api.assets.upload([file]);
      const asset = uploaded.items[0];
      if (!asset) throw new Error("上传失败");
      onUse(asset);
      onClose();
      toast("已把拼图作为单张参考加入", "success");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "拼图使用失败", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="合成参考图"
      subtitle="把多张参考按顺序拼成一张 1800×1200 PNG，适合只接受单图参考的模型"
      onClose={onClose}
      width={920}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <span className="grow" />
          <Button variant="soft" icon={<Download size={14} />} onClick={() => void download()} disabled={!ready}>
            下载 PNG
          </Button>
          <Button
            variant="primary"
            icon={busy ? <Loader2 size={14} className="spin" /> : <ImagePlus size={14} />}
            loading={busy}
            disabled={!ready}
            onClick={() => void useAsReference()}
          >
            作为单张参考
          </Button>
        </>
      }
    >
      <canvas ref={canvasRef} width={WIDTH} height={HEIGHT} className="composite-canvas" />
      <p className="hint-block">顺序按人物 / 服装 / 姿势 / 其他参考排列；最多取前三张。</p>
    </Modal>
  );
}
