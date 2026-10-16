import { Languages, Loader2, MessageSquarePlus, Sparkles } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { streamChat } from "../api";
import { getSelectionPortalRoot, type SelectionAnchor } from "../hooks/useReadingSelection";

export type SelectionAction = "translate" | "explain" | "ask";

type Props = {
  token: string;
  sourceTitle: string;
  anchor: SelectionAnchor;
  onAddToDraft: (text: string) => void;
  onOpenMeridian?: () => void;
  onDismiss: () => void;
};

type PanelMode = "menu" | "loading" | "result";

const ACTIONS: Array<{ id: SelectionAction; label: string; icon: typeof Languages }> = [
  { id: "translate", label: "翻译", icon: Languages },
  { id: "explain", label: "解释", icon: Sparkles },
  { id: "ask", label: "对话", icon: MessageSquarePlus },
];

function previewText(text: string, max = 48) {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

export default function SelectionPopover({
  token,
  sourceTitle,
  anchor,
  onAddToDraft,
  onOpenMeridian,
  onDismiss,
}: Props) {
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState({ top: anchor.bottom + 12, left: anchor.left, flip: false });
  const [portalRoot, setPortalRoot] = useState(getSelectionPortalRoot);
  const [panel, setPanel] = useState<PanelMode>("menu");
  const [resultTitle, setResultTitle] = useState("");
  const [resultBody, setResultBody] = useState("");

  useEffect(() => {
    function syncRoot() {
      setPortalRoot(getSelectionPortalRoot());
    }
    document.addEventListener("fullscreenchange", syncRoot);
    syncRoot();
    return () => document.removeEventListener("fullscreenchange", syncRoot);
  }, []);

  useLayoutEffect(() => {
    const card = cardRef.current;
    const margin = 16;
    const cardW = card?.offsetWidth ?? 260;
    const cardH = card?.offsetHeight ?? 56;
    const gap = 10;
    const spaceBelow = window.innerHeight - anchor.bottom - margin;
    const spaceAbove = anchor.top - margin;
    const flip = spaceBelow < cardH + gap && spaceAbove > spaceBelow;

    let top = flip ? anchor.top - cardH - gap : anchor.bottom + gap;
    let left = anchor.left;

    top = Math.max(margin, Math.min(top, window.innerHeight - cardH - margin));
    left = Math.max(margin + cardW / 2, Math.min(left, window.innerWidth - margin - cardW / 2));

    setPos({ top, left, flip });
  }, [anchor, portalRoot, panel, resultBody]);

  async function runInline(action: "translate" | "explain", text: string) {
    const snippet = text.length > 400 ? `${text.slice(0, 400)}…` : text;
    setPanel("loading");
    setResultTitle(action === "translate" ? "翻译" : "解释");
    setResultBody("");

    const prompt =
      action === "translate"
        ? `请翻译以下内容，只输出译文，不要附加说明：\n「${snippet}」`
        : `请简要解释以下内容的含义（不超过150字）：\n「${snippet}」`;

    let assembled = "";
    let streamError = "";
    try {
      await streamChat(token, { message: prompt, conv_id: null }, (payload) => {
        if (payload.kind === "error") {
          streamError = payload.message;
          setResultBody(payload.message);
        } else if (payload.kind === "text") {
          assembled += payload.text;
          setResultBody(assembled);
        }
      });
      if (streamError) setResultBody(streamError);
      else if (!assembled.trim()) setResultBody("未能获取结果，请重试。");
      setPanel("result");
    } catch (err) {
      setResultBody(err instanceof Error ? err.message : "请求失败");
      setPanel("result");
    }
  }

  function handleAction(action: SelectionAction) {
    if (action === "ask") {
      const snippet = anchor.text.length > 400 ? `${anchor.text.slice(0, 400)}…` : anchor.text;
      onAddToDraft(
        `关于「${sourceTitle}」中的这段内容「${snippet}」，请结合资料库帮我分析`,
      );
      onOpenMeridian?.();
      onDismiss();
      return;
    }
    void runInline(action, anchor.text);
  }

  return createPortal(
    <div
      className={`selection-popover${panel !== "menu" ? " expanded" : ""}`}
      style={{ top: pos.top, left: pos.left }}
      ref={cardRef}
      role="dialog"
      aria-label="划词操作"
      onMouseDown={(e) => e.preventDefault()}
    >
      <span
        className={`selection-popover-arrow${pos.flip ? " flip" : ""}`}
        aria-hidden
      />

      {panel === "menu" && (
        <div className="selection-popover-card">
          <p className="selection-popover-quote">"{previewText(anchor.text)}"</p>
          <div className="selection-popover-actions">
            {ACTIONS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                className="selection-popover-btn"
                onClick={() => handleAction(id)}
              >
                <Icon size={15} strokeWidth={1.75} />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {panel === "loading" && (
        <div className="selection-popover-panel">
          <header className="selection-popover-panel-head">
            <span>{resultTitle}</span>
          </header>
          <div className="selection-popover-panel-body loading">
            <Loader2 className="spin" size={16} />
            <span>Meridian 思考中…</span>
          </div>
        </div>
      )}

      {panel === "result" && (
        <div className="selection-popover-panel">
          <header className="selection-popover-panel-head">
            <span>{resultTitle}</span>
            <button type="button" className="selection-popover-back" onClick={() => setPanel("menu")}>
              返回
            </button>
          </header>
          <div className="selection-popover-panel-body">{resultBody}</div>
          <footer className="selection-popover-panel-foot">
            <button
              type="button"
              className="selection-popover-foot-btn"
              onClick={() => {
                onAddToDraft(resultBody);
                onOpenMeridian?.();
                onDismiss();
              }}
            >
              加入对话
            </button>
            <button type="button" className="selection-popover-foot-btn ghost" onClick={onDismiss}>
              关闭
            </button>
          </footer>
        </div>
      )}
    </div>,
    portalRoot,
  );
}
