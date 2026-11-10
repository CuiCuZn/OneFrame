import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useStore } from "../lib/store";
import type { PromptEnhanceResult } from "../lib/types";
import { Badge, Button, Modal } from "./ui";

type EnhanceMode = "llm" | "rules";

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
  const [mode, setMode] = useState<EnhanceMode>("llm");

  useEffect(() => {
    if (!open) return;
    if (!prompt.trim()) {
      setResult(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setResult(null);
    api
      .enhancePrompt({
        prompt,
        negative,
        style,
        modality,
        has_refs: hasRefs,
        language: "zh",
        mode,
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
  }, [open, prompt, negative, style, modality, hasRefs, mode]);

  const subtitle =
    mode === "llm"
      ? "GLM 5.3 Flash 改写，失败自动回退本地规则；结果仍可继续编辑"
      : "本地规则补全，不调用大模型；结果仍可继续编辑";

  return (
    <Modal
      open={open}
      title="提示词增强"
      subtitle={subtitle}
      onClose={onClose}
      width={760}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="soft"
            disabled={loading}
            onClick={() => setMode(mode === "llm" ? "rules" : "llm")}
          >
            {mode === "llm" ? "改用规则" : "改用 AI"}
          </Button>
          <span className="grow" />
          <Button
            variant="primary"
            disabled={!result || loading}
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
          <Loader2 size={15} className="spin" />
          {mode === "llm" ? "正在用 GLM 5.3 Flash 改写…" : "正在按规则补全…"}
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
              {result.source === "llm" ? (
                <Badge tone="accent">AI 改写</Badge>
              ) : (
                <Badge tone="warn">本地规则</Badge>
              )}
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
