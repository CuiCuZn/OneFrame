import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { PromptEnhanceResult } from "../lib/types";
import { Button, Modal } from "./ui";

export default function EnhanceModal({
  open,
  onClose,
  prompt,
  negative,
  style,
  modality,
  hasRefs,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  prompt: string;
  negative: string;
  style: string;
  modality: string;
  hasRefs: boolean;
  onApply: (prompt: string, negative: string) => void;
}) {
  const { toast } = useStore();
  const [result, setResult] = useState<PromptEnhanceResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (!prompt.trim()) {
      setResult(null);
      return;
    }
    let alive = true;
    setLoading(true);
    api
      .enhancePrompt({
        prompt,
        negative,
        style,
        modality,
        has_refs: hasRefs,
        language: "zh",
      })
      .then((data) => {
        if (alive) setResult(data);
      })
      .catch((error) => {
        if (alive) toast(error instanceof ApiError ? error.message : "增强失败", "error");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prompt, negative, style, modality, hasRefs]);

  return (
    <Modal
      open={open}
      title="提示词增强"
      subtitle="本地规则补全，不调用大模型；结果仍可继续编辑"
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <span className="grow" />
          <Button
            variant="primary"
            disabled={!result}
            onClick={() => {
              if (!result) return;
              onApply(result.prompt, result.negative);
              onClose();
            }}
          >
            应用
          </Button>
        </>
      }
    >
      {loading ? (
        <div className="tool-hint">
          <Loader2 size={15} className="spin" /> 正在按规则补全…
        </div>
      ) : !result ? (
        <p className="hint-block">先写一句提示词，再使用增强。</p>
      ) : (
        <div className="enhance-grid">
          <div>
            <span className="tool-label">原文</span>
            <div className="lb-prompt">{prompt}</div>
          </div>
          <div>
            <span className="tool-label">
              <Sparkles size={12} /> 增强后
            </span>
            <div className="lb-prompt">{result.prompt}</div>
            <ul className="enhance-notes">
              {result.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Modal>
  );
}
