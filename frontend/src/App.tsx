import { LayoutGrid, LogOut, MessageSquare, Package, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiFetch,
  createShelf,
  deleteConversation,
  deleteShelf,
  deleteSource,
  ingestSource,
  isSourceBusy,
  listShelves,
  moveSourceToShelf,
  renameConversation,
  renameShelf,
  renameSource,
  listConversations,
  listMessages,
  READABLE_MODALITIES,
  streamChat,
  waitForSourceReady,
  type ChatMessage,
  type Conversation,
  type IngestInput,
  type Shelf,
  type SourceMeta,
  type SourceStatus,
} from "./api";
import AuthScreen from "./components/AuthScreen";
import ButlerPanel, { type LayoutMode } from "./components/ButlerPanel";
import ConfirmDialog from "./components/ConfirmDialog";
import BatchMoveShelfMenu from "./components/BatchMoveShelfMenu";
import CreateShelfDialog from "./components/CreateShelfDialog";
import IngestToastStack, { type IngestJob } from "./components/IngestToastStack";
import LibrarySheet from "./components/LibrarySheet";
import RenameSourceDialog from "./components/RenameSourceDialog";
import ShelfContextMenu from "./components/ShelfContextMenu";
import ShelfRail, { type ShelfFilter } from "./components/ShelfRail";
import SourceContextMenu from "./components/SourceContextMenu";
import SourceGrid from "./components/SourceGrid";
import SourceHoverCard from "./components/SourceHoverCard";
import SourceReader from "./components/SourceReader";
import SpaceCanvas, { type SpacePoint } from "./components/SpaceCanvas";
import WarehouseViewSwitch, { type WarehouseView } from "./components/WarehouseViewSwitch";

const TOKEN_KEY = "mar2_access_token";
const USER_KEY = "mar2_username";
const WAREHOUSE_VIEW_KEY = "mar2_warehouse_view";

function randomId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function readWarehouseView(): WarehouseView {
  return localStorage.getItem(WAREHOUSE_VIEW_KEY) === "grid" ? "grid" : "spatial";
}

type RackSource = {
  id: string;
  title: string;
  modality: string;
  summary: string;
  chunks: number;
  created_at?: string;
  status?: SourceStatus;
  error_message?: string | null;
  shelf_id?: string | null;
  shelf_name?: string | null;
};

type SpaceSnapshot = {
  sources: RackSource[];
  points: SpacePoint[];
  provider: string;
  dimensions: number;
};

const MODALITY_LABELS: Record<string, string> = {
  text: "文本", url: "网页", pdf: "PDF", txt: "TXT", md: "Markdown", query: "查询",
};

function normalizeSpace(data: unknown): SpaceSnapshot {
  const p = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const sourcesRaw = Array.isArray(p.sources) ? p.sources : [];
  return {
    sources: sourcesRaw.map((item) => {
      const s = (item ?? {}) as Record<string, unknown>;
      const statusRaw = typeof s.status === "string" ? s.status : "ready";
      const status = (["pending", "processing", "ready", "failed"].includes(statusRaw)
        ? statusRaw
        : "ready") as SourceStatus;
      return {
        id: String(s.id ?? ""),
        title: String(s.title ?? ""),
        modality: String(s.modality ?? "text"),
        summary: String(s.summary ?? ""),
        chunks: typeof s.chunks === "number" ? s.chunks : typeof s.chunk_count === "number" ? s.chunk_count : 0,
        created_at: typeof s.created_at === "string" ? s.created_at : undefined,
        status,
        error_message: typeof s.error_message === "string" ? s.error_message : null,
        shelf_id: s.shelf_id == null || s.shelf_id === "" ? null : String(s.shelf_id),
        shelf_name: typeof s.shelf_name === "string" ? s.shelf_name : null,
      };
    }),
    points: (Array.isArray(p.points) ? p.points : []) as SpacePoint[],
    provider: String(p.provider ?? p.embedding_model ?? "未知"),
    dimensions: typeof p.dimensions === "number" ? p.dimensions : 1024,
  };
}

function formatWhen(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function pointMetaLine(point: SpacePoint, sources: RackSource[]) {
  const modality = MODALITY_LABELS[point.modality] || point.modality;
  if (point.modality === "query") return modality;
  const source = sources.find((item) => item.id === point.source_id);
  const shelf = source?.shelf_name || (source && source.shelf_id == null ? "未分类" : "");
  const bits = [modality];
  if (shelf) bits.push(shelf);
  if (source?.created_at) {
    const when = formatWhen(source.created_at);
    if (when) bits.push(when);
  }
  if (isSourceBusy(source?.status)) bits.push("处理中");
  if (source?.status === "failed") bits.push("失败");
  return bits.join(" · ");
}

function matchesShelfFilter(source: RackSource, filter: ShelfFilter) {
  if (filter === "all") return true;
  if (filter === "inbox") return source.shelf_id == null;
  return source.shelf_id === filter;
}

function Workspace({ token, username, onLogout }: { token: string; username: string; onLogout: () => void }) {
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("warehouse");
  const [warehouseView, setWarehouseView] = useState<WarehouseView>(readWarehouseView);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [space, setSpace] = useState<SpaceSnapshot | null>(null);
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [shelfFilter, setShelfFilter] = useState<ShelfFilter>("all");
  const [selectedPoint, setSelectedPoint] = useState<SpacePoint | null>(null);
  const [hoveredPoint, setHoveredPoint] = useState<SpacePoint | null>(null);
  const [hoverPosition, setHoverPosition] = useState<{ x: number; y: number } | null>(null);
  const [contextMenu, setContextMenu] = useState<{ point: SpacePoint; x: number; y: number } | null>(null);
  const [pendingDeleteSourceId, setPendingDeleteSourceId] = useState<string | null>(null);
  const [deletingSourceId, setDeletingSourceId] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<SpacePoint | null>(null);
  const [renamingSource, setRenamingSource] = useState(false);
  const [createShelfOpen, setCreateShelfOpen] = useState(false);
  const [creatingShelf, setCreatingShelf] = useState(false);
  const [shelfContextMenu, setShelfContextMenu] = useState<{ shelf: Shelf; x: number; y: number } | null>(null);
  const [renameShelfTarget, setRenameShelfTarget] = useState<Shelf | null>(null);
  const [renamingShelf, setRenamingShelf] = useState(false);
  const [pendingDeleteShelfId, setPendingDeleteShelfId] = useState<string | null>(null);
  const [deletingShelfId, setDeletingShelfId] = useState<string | null>(null);
  const [readingSource, setReadingSource] = useState<SourceMeta | null>(null);
  const [meridianCompanionOpen, setMeridianCompanionOpen] = useState(true);
  const readingShellRef = useRef<HTMLDivElement | null>(null);
  const exitingFullscreenRef = useRef(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [deletingConvId, setDeletingConvId] = useState<number | null>(null);
  const [renamingConvId, setRenamingConvId] = useState<number | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [queryPoint, setQueryPoint] = useState<SpacePoint | null>(null);
  const [highlightScores, setHighlightScores] = useState<Map<string, number>>(() => new Map());
  const [ingestJobs, setIngestJobs] = useState<IngestJob[]>([]);
  const [batchMode, setBatchMode] = useState(false);
  const [batchSelectedIds, setBatchSelectedIds] = useState<Set<string>>(() => new Set());
  const [batchMoveMenu, setBatchMoveMenu] = useState<{ x: number; y: number } | null>(null);
  const [batchMoving, setBatchMoving] = useState(false);

  const allSources = space?.sources ?? [];
  const filteredSources = useMemo(
    () => allSources.filter((s) => matchesShelfFilter(s, shelfFilter)),
    [allSources, shelfFilter],
  );
  const filteredSourceIds = useMemo(() => new Set(filteredSources.map((s) => s.id)), [filteredSources]);
  const filteredPoints = useMemo(
    () => (space?.points ?? []).filter((p) => p.modality === "query" || filteredSourceIds.has(p.source_id)),
    [space?.points, filteredSourceIds],
  );
  const shelfCounts = useMemo(() => {
    const map: Record<string, number> = { all: allSources.length, inbox: 0 };
    for (const shelf of shelves) map[shelf.id] = 0;
    for (const src of allSources) {
      if (src.shelf_id == null) map.inbox += 1;
      else if (map[src.shelf_id] != null) map[src.shelf_id] += 1;
      else map[src.shelf_id] = 1;
    }
    return map;
  }, [allSources, shelves]);
  const processingCount = useMemo(
    () => ingestJobs.filter((job) => job.status === "processing").length,
    [ingestJobs],
  );
  const ingestDefaultShelfId =
    shelfFilter !== "all" && shelfFilter !== "inbox" ? shelfFilter : null;
  const activeShelfName =
    ingestDefaultShelfId != null
      ? shelves.find((s) => s.id === ingestDefaultShelfId)?.name
      : shelfFilter === "inbox"
        ? "未分类"
        : null;

  function openLibrary() {
    setLibraryOpen(true);
  }
  const sourceCount = allSources.filter((s) => s.status !== "failed").length;
  const isReading = readingSource != null;
  const isReadingRef = useRef(isReading);
  isReadingRef.current = isReading;
  const pendingDelete = conversations.find((c) => c.id === pendingDeleteId) ?? null;
  const pendingDeleteSource = space?.sources.find((s) => s.id === pendingDeleteSourceId) ?? null;
  const pendingDeleteShelf = shelves.find((s) => s.id === pendingDeleteShelfId) ?? null;
  const cardPoint = selectedPoint ?? hoveredPoint;
  const cardPosition = selectedPoint
    ? undefined
    : hoverPosition
      ? { top: hoverPosition.y + 12, left: hoverPosition.x + 12 }
      : undefined;

  const handleAuthFailure = useCallback(
    (err: unknown) => {
      if (err && typeof err === "object" && "status" in err && (err as { status?: number }).status === 401) {
        onLogout();
      }
    },
    [onLogout],
  );

  const refreshSpace = useCallback(async () => {
    const data = await apiFetch<{ space?: unknown }>("/space", token);
    setSpace(normalizeSpace(data));
  }, [token]);

  const refreshShelves = useCallback(async () => {
    try {
      setShelves(await listShelves(token));
    } catch (err) {
      handleAuthFailure(err);
      // 后端未实现 /shelves 时不阻断主流程
      if (err && typeof err === "object" && "status" in err && (err as { status?: number }).status === 404) {
        setShelves([]);
      }
    }
  }, [token, handleAuthFailure]);

  const refreshConversations = useCallback(async () => {
    setConversationsLoading(true);
    try {
      setConversations(await listConversations(token));
    } catch (err) {
      handleAuthFailure(err);
    } finally {
      setConversationsLoading(false);
    }
  }, [token, handleAuthFailure]);

  const loadMessages = useCallback(
    async (convId: number) => {
      setMessagesLoading(true);
      try {
        setMessages(await listMessages(token, convId));
      } catch (err) {
        handleAuthFailure(err);
        setMessages([]);
      } finally {
        setMessagesLoading(false);
      }
    },
    [token, handleAuthFailure],
  );

  useEffect(() => {
    refreshSpace().catch(handleAuthFailure);
  }, [refreshSpace, handleAuthFailure]);

  useEffect(() => {
    refreshShelves().catch(() => undefined);
  }, [refreshShelves]);

  useEffect(() => {
    // pending 只在 Redis，/space 往往看不到 busy；入库中也要靠 ingestJobs 驱动轮询
    const busyInSpace = (space?.sources ?? []).some((s) => isSourceBusy(s.status));
    const busyIngest = ingestJobs.some((job) => job.status === "processing");
    if (!busyInSpace && !busyIngest) return;
    const id = window.setInterval(() => {
      refreshSpace().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(id);
  }, [space?.sources, ingestJobs, refreshSpace]);

  useEffect(() => {
    if (!batchMode) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setBatchMode(false);
        setBatchSelectedIds(new Set());
        setBatchMoveMenu(null);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [batchMode]);

  useEffect(() => {
    refreshConversations().catch(() => undefined);
  }, [refreshConversations]);

  useEffect(() => {
    if (activeConvId == null) { setMessages([]); return; }
    loadMessages(activeConvId).catch(() => undefined);
  }, [activeConvId, loadMessages]);

  useEffect(() => {
    if (!isReading) return;
    const el = readingShellRef.current;
    if (!el) return;

    void el.requestFullscreen().catch(() => undefined);

    function onFullscreenChange() {
      if (exitingFullscreenRef.current) return;
      if (isReadingRef.current && document.fullscreenElement !== el) {
        setReadingSource(null);
        setMeridianCompanionOpen(true);
      }
    }

    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      exitingFullscreenRef.current = true;
      if (document.fullscreenElement === el) {
        void document.exitFullscreen().catch(() => undefined);
      }
      queueMicrotask(() => {
        exitingFullscreenRef.current = false;
      });
    };
  }, [isReading]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        if (isReading) {
          event.preventDefault();
          setMeridianCompanionOpen((open) => !open);
        }
        return;
      }
      if (event.key === "Escape") {
        if (isReading && meridianCompanionOpen) {
          setMeridianCompanionOpen(false);
          return;
        }
        if (readingSource) {
          closeReader();
          return;
        }
        if (layoutMode === "chat") setLayoutMode("balanced");
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [layoutMode, readingSource, meridianCompanionOpen, isReading]);

  function openReader(source: SourceMeta | RackSource) {
    if (!READABLE_MODALITIES.has(source.modality)) return;
    setReadingSource({
      id: source.id,
      title: source.title,
      modality: source.modality,
      summary: "summary" in source ? source.summary : undefined,
      created_at: "created_at" in source ? source.created_at : undefined,
    });
    setSelectedPoint(null);
    setMeridianCompanionOpen(true);
  }

  function closeReader() {
    exitingFullscreenRef.current = true;
    setReadingSource(null);
    setMeridianCompanionOpen(true);
    if (readingShellRef.current && document.fullscreenElement === readingShellRef.current) {
      void document.exitFullscreen().catch(() => undefined);
    }
    queueMicrotask(() => {
      exitingFullscreenRef.current = false;
    });
  }

  function dismissIngestJob(id: string) {
    setIngestJobs((jobs) => jobs.filter((job) => job.id !== id));
  }

  function handleIngest(input: IngestInput) {
    const jobId = randomId();
    const title =
      input.kind === "file"
        ? input.title
        : input.kind === "text"
          ? input.title || "未命名"
          : input.title || input.url.replace(/^https?:\/\//, "").slice(0, 48);

    setIngestJobs((jobs) => [...jobs, { id: jobId, title, status: "processing" }]);

    void (async () => {
      try {
        // 链路 A：异步接单；链路 B：轮询 detail 至 ready（期间 ingestJobs=processing 会驱动 /space 刷新）
        const source = await ingestSource(token, input);
        await waitForSourceReady(token, source.id);
        setIngestJobs((jobs) =>
          jobs.map((job) => (job.id === jobId ? { ...job, status: "success" } : job)),
        );
        await refreshSpace();
        await refreshShelves().catch(() => undefined);

        window.setTimeout(() => {
          setIngestJobs((jobs) => jobs.filter((job) => job.id !== jobId));
        }, 4500);
      } catch (err) {
        handleAuthFailure(err);
        const message = err instanceof Error ? err.message : "入库失败";
        setIngestJobs((jobs) =>
          jobs.map((job) => (job.id === jobId ? { ...job, status: "error", message } : job)),
        );
      }
    })();
  }

  function handleAskFromReader(text: string) {
    setDraft(text);
    setMeridianCompanionOpen(true);
  }

  function persistWarehouseView(view: WarehouseView) {
    setWarehouseView(view);
    localStorage.setItem(WAREHOUSE_VIEW_KEY, view);
  }

  function askAboutPoint(point: SpacePoint) {
    setDraft(`请介绍一下「${point.title}」`);
    setContextMenu(null);
    if (layoutMode === "warehouse") setLayoutMode("balanced");
  }

  function askAboutSource(source: RackSource) {
    setDraft(`请介绍一下「${source.title}」`);
    setContextMenu(null);
    if (layoutMode === "warehouse") setLayoutMode("balanced");
  }

  function handleGridSelect(source: RackSource) {
    const point = space?.points.find((p) => p.source_id === source.id) ?? null;
    handleSelectPoint(point);
  }

  function handleGridContextMenu(source: RackSource, position: { x: number; y: number }) {
    const point = space?.points.find((p) => p.source_id === source.id);
    if (!point) return;
    handlePointContextMenu(point, position);
  }

  function openReaderFromPoint(point: SpacePoint) {
    const src = space?.sources.find((s) => s.id === point.source_id);
    if (src) openReader(src);
    setContextMenu(null);
  }

  function handlePointContextMenu(point: SpacePoint, position: { x: number; y: number }) {
    setSelectedPoint(point);
    setContextMenu({ point, x: position.x, y: position.y });
  }

  async function confirmDeleteSource() {
    if (!pendingDeleteSourceId) return;
    const sourceId = pendingDeleteSourceId;
    setDeletingSourceId(sourceId);
    try {
      await deleteSource(token, sourceId);
      setPendingDeleteSourceId(null);
      setContextMenu(null);
      if (selectedPoint?.source_id === sourceId) setSelectedPoint(null);
      if (hoveredPoint?.source_id === sourceId) setHoveredPoint(null);
      if (readingSource?.id === sourceId) closeReader();
      await refreshSpace();
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingSourceId(null);
    }
  }

  async function confirmRenameSource(title: string) {
    if (!renameTarget) return;
    setRenamingSource(true);
    setError("");
    try {
      const data = await renameSource(token, renameTarget.source_id, title);
      if (data.space) {
        setSpace(normalizeSpace(data.space));
      } else {
        await refreshSpace();
      }
      setRenameTarget(null);
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 401) {
        handleAuthFailure(err);
        setError(err instanceof Error ? err.message : "重命名失败");
      }
      setError(err.message || "重命名失败");
    } finally {
      setRenamingSource(false);
    }
  }

  async function handleMoveToShelf(shelfId: string | null) {
    if (!contextMenu) return;
    const sourceId = contextMenu.point.source_id;
    setContextMenu(null);
    setError("");
    try {
      await moveSourceToShelf(token, sourceId, shelfId);
      await refreshShelves();
      await refreshSpace();
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "移动失败");
    }
  }

  
  function toggleBatchMode() {
    setBatchMode((on) => {
      if (on) {
        setBatchSelectedIds(new Set());
        setBatchMoveMenu(null);
      }
      return !on;
    });
    setContextMenu(null);
  }

  function toggleBatchSelect(sourceId: string) {
    setBatchSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(sourceId)) next.delete(sourceId);
      else next.add(sourceId);
      return next;
    });
  }

  function handleBatchSelectAll() {
    const selectable = filteredSources.filter((s) => !isSourceBusy(s.status)).map((s) => s.id);
    const allSelected = selectable.length > 0 && selectable.every((id) => batchSelectedIds.has(id));
    if (allSelected) {
      setBatchSelectedIds(new Set());
      return;
    }
    setBatchSelectedIds(new Set(selectable));
  }

  async function handleBatchMoveToShelf(shelfId: string | null) {
    const ids = [...batchSelectedIds];
    if (ids.length === 0) return;
    setBatchMoveMenu(null);
    setBatchMoving(true);
    setError("");
    const succeeded = new Set<string>();
    let fail = 0;
    try {
      for (const sourceId of ids) {
        try {
          await moveSourceToShelf(token, sourceId, shelfId);
          succeeded.add(sourceId);
        } catch (err) {
          fail += 1;
          handleAuthFailure(err);
        }
      }
      await refreshShelves();
      await refreshSpace(); 
      setBatchSelectedIds((prev) => {
        const next = new Set(prev);
        for (const id of succeeded) next.delete(id);
        return next;
      });
      if (fail === 0) {
        setBatchMode(false);
      } else {
        setError(`已移动 ${succeeded.size} 份，${fail} 份失败`);
      }
    } finally {
      setBatchMoving(false);
    }
  }

  async function handleCreateShelf(name: string) {
    setError("");
    setCreatingShelf(true);
    try {
      const shelf = await createShelf(token, name);
      await refreshShelves();
      setShelfFilter(shelf.id);
      setCreateShelfOpen(false);
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "创建资料架失败");
    } finally {
      setCreatingShelf(false);
    }
  }

  function handleShelfContextMenu(shelf: Shelf, position: { x: number; y: number }) {
    setShelfContextMenu({ shelf, x: position.x, y: position.y });
  }

  async function confirmRenameShelf(name: string) {
    if (!renameShelfTarget) return;
    setRenamingShelf(true);
    setError("");
    try {
      await renameShelf(token, renameShelfTarget.id, name);
      await refreshShelves();
      await refreshSpace();
      setRenameShelfTarget(null);
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "重命名资料架失败");
    } finally {
      setRenamingShelf(false);
    }
  }

  async function confirmDeleteShelf() {
    if (!pendingDeleteShelfId) return;
    const shelfId = pendingDeleteShelfId;
    setDeletingShelfId(shelfId);
    setError("");
    try {
      await deleteShelf(token, shelfId);
      setPendingDeleteShelfId(null);
      setShelfContextMenu(null);
      if (shelfFilter === shelfId) setShelfFilter("all");
      await refreshShelves();
      await refreshSpace();
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "删除资料架失败");
    } finally {
      setDeletingShelfId(null);
    }
  }

  async function sendMessage(text?: string) {
    const msg = (text ?? draft).trim();
    if (!msg || isSending) return;

    if (!isReading && layoutMode === "warehouse") setLayoutMode("balanced");
    if (isReading) setMeridianCompanionOpen(true);

    setIsSending(true);
    setError("");
    setStreamingText("");
    setDraft("");

    const optimistic: ChatMessage = {
      id: -Date.now(),
      role: "user",
      content: msg,
      created_at: new Date().toISOString(),
    };
    setMessages((cur) => [...cur, optimistic]);

    let nextConvId = activeConvId;
    let assembled = "";
    let streamError = "";

    try {
      await streamChat(token, { message: msg, conv_id: activeConvId }, (payload) => {
        if (payload.kind === "conv_id") {
          nextConvId = payload.convId;
          setActiveConvId(payload.convId);
        } else if (payload.kind === "retrieval") {
          if (payload.space) setSpace(normalizeSpace(payload.space));
          setQueryPoint(payload.query_point ?? null);
          {
            const scores = new Map<string, number>();
            const values = payload.matches
              .map((m) => m.score)
              .filter((s): s is number => typeof s === "number");
            const maxScore = values.length ? Math.max(...values) : 1;
            const minScore = values.length ? Math.min(...values) : 0;
            const span = Math.max(maxScore - minScore, 1e-6);
            payload.matches.forEach((m, index) => {
              // 无分数时按排名近似：越靠前越高
              const raw =
                typeof m.score === "number"
                  ? m.score
                  : 1 - index / Math.max(payload.matches.length, 1);
              // 相对分档 0~1，便于高亮亮度
              const normalized = values.length
                ? (raw - minScore) / span
                : raw;
              scores.set(m.source_id, Math.min(1, Math.max(0, normalized)));
            });
            setHighlightScores(scores);
          }
          setWarehouseView("spatial");
          if (!isReading && layoutMode === "warehouse") setLayoutMode("balanced");
        } else if (payload.kind === "error") {
          streamError = payload.message;
          setStreamingText("");
        } else if (payload.kind === "text") {
          assembled += payload.text;
          setStreamingText(assembled);
        }
      });

      if (streamError) {
        setStreamingText("");
        setError(streamError);
      } else if (assembled.trim()) {
        setStreamingText("");
        setMessages((cur) => [
          ...cur,
          { id: -(Date.now() + 1), role: "assistant", content: assembled, created_at: new Date().toISOString() },
        ]);
      } else {
        setStreamingText("");
      }

      if (nextConvId != null) {
        await loadMessages(nextConvId);
        await refreshConversations();
      }
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "发送失败");
      if (activeConvId == null) {
        setMessages((cur) => cur.filter((m) => m.id !== optimistic.id));
      }
    } finally {
      setStreamingText("");
      setIsSending(false);
    }
  }

  function handleSelectPoint(point: SpacePoint | null) {
    setSelectedPoint(point);
    if (point && point.modality !== "query") {
      setDraft(`请介绍一下「${point.title}」`);
    }
  }

  function handleHoverPoint(point: SpacePoint | null, position?: { x: number; y: number }) {
    if (selectedPoint) return;
    setHoveredPoint(point);
    setHoverPosition(position ?? null);
  }

  function startNewChat() {
    setActiveConvId(null);
    setMessages([]);
    setDraft("");
    setStreamingText("");
    setQueryPoint(null);
    setHighlightScores(new Map());
  }

  function requestDeleteConv(convId: number) {
    setPendingDeleteId(convId);
  }

  async function handleRenameConv(convId: number, title: string) {
    setRenamingConvId(convId);
    setError("");
    try {
      await renameConversation(token, convId, title);
      await refreshConversations();
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "重命名会话失败");
    } finally {
      setRenamingConvId(null);
    }
  }

  async function confirmDeleteConv() {
    if (pendingDeleteId == null) return;
    const convId = pendingDeleteId;
    setDeletingConvId(convId);
    try {
      await deleteConversation(token, convId);
      setPendingDeleteId(null);
      if (activeConvId === convId) startNewChat();
      await refreshConversations();
    } catch (err) {
      handleAuthFailure(err);
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingConvId(null);
    }
  }

  return (
    <div className={`vault-shell${isReading ? " is-reading" : ""}`}>
      {!isReading && (
        <header className="vault-topbar">
          <div className="vault-brand">
            <h1>资料<em>仓库</em></h1>
            <p>
              {sourceCount > 0
                ? `${sourceCount} 份资料 · 知识空间已就绪`
                : "开始入库，构建你的知识空间"}
              {processingCount > 0 ? ` · ${processingCount} 份入库中` : ""}
            </p>
          </div>
          <div className="vault-toolbar">
            <div className="layout-switch" role="group" aria-label="布局模式">
              <button type="button" className={layoutMode === "balanced" ? "active" : ""} onClick={() => setLayoutMode("balanced")} title="均衡" aria-label="均衡布局">
                <LayoutGrid size={16} />
              </button>
              <button type="button" className={layoutMode === "chat" ? "active" : ""} onClick={() => setLayoutMode("chat")} title="全屏对话" aria-label="全屏对话">
                <MessageSquare size={16} />
              </button>
              <button type="button" className={layoutMode === "warehouse" ? "active" : ""} onClick={() => setLayoutMode("warehouse")} title="专注仓库" aria-label="专注仓库">
                <Package size={16} />
              </button>
            </div>
            <span className="vault-toolbar-divider" aria-hidden />
            <span className="meta-chip meta-chip--user" title={username}>🙂 {username}</span>
            <button
              type="button"
              className="btn-primary vault-ingest-btn"
              onClick={openLibrary}
              title={
                activeShelfName
                  ? `入库到「${activeShelfName}」`
                  : "添加入库"
              }
            >
              <Plus size={15} /> 入库
            </button>
            <button type="button" className="icon-btn" onClick={onLogout} title="退出" aria-label="退出"><LogOut size={16} /></button>
          </div>
        </header>
      )}

      {error && !isReading && <div className="error-toast" role="alert">{error}</div>}

      {!isReading && (
      <div className={`vault-workspace mode-${layoutMode}`}>
        {layoutMode !== "chat" && (
          <section className={`warehouse-stage with-shelf view-${warehouseView}`}>
            <ShelfRail
              shelves={shelves}
              filter={shelfFilter}
              counts={shelfCounts}
              onFilterChange={setShelfFilter}
              onCreateShelf={() => setCreateShelfOpen(true)}
              onShelfContextMenu={handleShelfContextMenu}
            />
            <div className="warehouse-main">
              {warehouseView === "spatial" ? (
                <>
                  <SpaceCanvas
                    points={filteredPoints}
                    queryPoint={queryPoint}
                    highlightScores={highlightScores}
                    selectedId={selectedPoint?.id ?? null}
                    hoveredId={hoveredPoint?.id ?? null}
                    onSelect={handleSelectPoint}
                    onHover={handleHoverPoint}
                    onContextMenu={handlePointContextMenu}
                    viewSwitch={
                      <WarehouseViewSwitch
                        variant="canvas"
                        value={warehouseView}
                        onChange={persistWarehouseView}
                      />
                    }
                  />
                  {cardPoint && cardPoint.modality !== "query" && filteredSourceIds.has(cardPoint.source_id) && (
                    <SourceHoverCard
                      point={cardPoint}
                      metaLine={pointMetaLine(cardPoint, allSources)}
                      readable={
                        READABLE_MODALITIES.has(cardPoint.modality) &&
                        !isSourceBusy(allSources.find((s) => s.id === cardPoint.source_id)?.status) &&
                        allSources.find((s) => s.id === cardPoint.source_id)?.status !== "failed"
                      }
                      pinned={Boolean(selectedPoint)}
                      style={
                        cardPosition
                          ? {
                              position: "fixed",
                              top: Math.min(cardPosition.top, window.innerHeight - 220),
                              left: Math.min(cardPosition.left, window.innerWidth - 300),
                              width: 280,
                              zIndex: 20,
                            }
                          : undefined
                      }
                      onOpen={
                        READABLE_MODALITIES.has(cardPoint.modality)
                          ? () => openReaderFromPoint(cardPoint)
                          : undefined
                      }
                      onAsk={() => askAboutPoint(cardPoint)}
                      onContextMenu={(event) => {
                        event.preventDefault();
                        handlePointContextMenu(cardPoint, { x: event.clientX, y: event.clientY });
                      }}
                    />
                  )}
                  {filteredSources.length === 0 && (
                    <div className="warehouse-empty">
                      <p className="warehouse-empty-title">
                        {shelfFilter === "all"
                          ? "这一视图暂无资料"
                          : shelfFilter === "inbox"
                            ? "未分类还是空的"
                            : `「${activeShelfName ?? "此架"}」还没有资料`}
                      </p>
                      <p className="warehouse-empty-desc">
                        {shelfFilter === "all"
                          ? "从右上角入库，或点下方按钮开始。"
                          : shelfFilter === "inbox"
                            ? "入库后可先放在未分类，稍后整理到资料架。"
                            : `点击入库将默认放入「${activeShelfName ?? "此架"}」，也可从右键菜单移入。`}
                      </p>
                      <button type="button" className="btn-ghost" onClick={openLibrary}>
                        <Plus size={15} /> 开始入库
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <SourceGrid
                  sources={filteredSources}
                  selectedId={selectedPoint?.source_id ?? null}
                  modalityLabels={MODALITY_LABELS}
                  readableModalities={READABLE_MODALITIES}
                  emptyTitle={
                    shelfFilter === "all"
                      ? "仓库还是空的"
                      : shelfFilter === "inbox"
                        ? "未分类还是空的"
                        : `「${activeShelfName ?? "此架"}」还没有资料`
                  }
                  emptyDesc={
                    shelfFilter === "all"
                      ? "入库 PDF、Markdown 或文本，Meridian 会帮你整理成可检索的知识空间。"
                      : shelfFilter === "inbox"
                        ? "先入库到未分类，稍后可用右键整理到资料架。"
                        : `将默认入库到「${activeShelfName ?? "此架"}」。也可从其它资料右键移入。`
                  }
                  onSelect={handleGridSelect}
                  onOpen={openReader}
                  onAsk={askAboutSource}
                  onContextMenu={handleGridContextMenu}
                  onAddSource={openLibrary}
                  batchMode={batchMode}
                  selectedIds={batchSelectedIds}
                  batchMoving={batchMoving}
                  onToggleBatchMode={toggleBatchMode}
                  onToggleSelect={toggleBatchSelect}
                  onSelectAll={handleBatchSelectAll}
                  onClearSelection={() => setBatchSelectedIds(new Set())}
                  onOpenBatchMoveMenu={(pos) => setBatchMoveMenu(pos)}
                  viewSwitch={
                    <WarehouseViewSwitch
                      variant="toolbar"
                      value={warehouseView}
                      onChange={persistWarehouseView}
                    />
                  }
                />
              )}
            </div>
              {contextMenu && (
                <SourceContextMenu
                  x={contextMenu.x}
                  y={contextMenu.y}
                  title={contextMenu.point.title}
                  readable={READABLE_MODALITIES.has(contextMenu.point.modality)}
                  currentShelfId={allSources.find((s) => s.id === contextMenu.point.source_id)?.shelf_id ?? null}
                  shelves={shelves}
                  onOpen={
                    READABLE_MODALITIES.has(contextMenu.point.modality)
                      ? () => openReaderFromPoint(contextMenu.point)
                      : undefined
                  }
                  onAsk={() => askAboutPoint(contextMenu.point)}
                  onRename={() => {
                    setRenameTarget(contextMenu.point);
                    setContextMenu(null);
                  }}
                  onMoveToShelf={(shelfId) => {
                    void handleMoveToShelf(shelfId);
                  }}
                  onDelete={() => {
                    setPendingDeleteSourceId(contextMenu.point.source_id);
                    setContextMenu(null);
                  }}
                  onClose={() => setContextMenu(null)}
                />
              )}
              {batchMoveMenu && (
                <BatchMoveShelfMenu
                  x={batchMoveMenu.x}
                  y={batchMoveMenu.y}
                  shelves={shelves}
                  onMove={(shelfId) => {
                    void handleBatchMoveToShelf(shelfId);
                  }}
                  onClose={() => setBatchMoveMenu(null)}
                />
              )}
          </section>
        )}

        <ButlerPanel
          layoutMode={layoutMode}
          sourceCount={sourceCount}
          messages={messages}
          draft={draft}
          streamingText={streamingText}
          isSending={isSending || messagesLoading}
          conversations={conversations}
          activeConvId={activeConvId}
          conversationsLoading={conversationsLoading}
          deletingConvId={deletingConvId}
          renamingConvId={renamingConvId}
          onRenameConv={handleRenameConv}
          onLayoutChange={setLayoutMode}
          onDraftChange={setDraft}
          onSend={sendMessage}
          onNewChat={startNewChat}
          onSelectConv={setActiveConvId}
          onDeleteConv={requestDeleteConv}
        />
      </div>
      )}

      {isReading && readingSource && (
        <div className="reading-shell" ref={readingShellRef}>
          <div className={`reading-split${meridianCompanionOpen ? " with-companion" : ""}`}>
            <div className="reading-main">
              <SourceReader
                token={token}
                source={readingSource}
                immersive
                onClose={closeReader}
                onAsk={handleAskFromReader}
                onOpenMeridian={() => setMeridianCompanionOpen(true)}
              />
            </div>

            {meridianCompanionOpen && (
              <aside className="reading-companion" aria-label="Meridian 伴读">
                <ButlerPanel
                  companion
                  layoutMode="balanced"
                  sourceCount={sourceCount}
                  messages={messages}
                  draft={draft}
                  streamingText={streamingText}
                  isSending={isSending || messagesLoading}
                  conversations={conversations}
                  activeConvId={activeConvId}
                  conversationsLoading={conversationsLoading}
                  deletingConvId={deletingConvId}
                  renamingConvId={renamingConvId}
                  onRenameConv={handleRenameConv}
                  onLayoutChange={setLayoutMode}
                  onDraftChange={setDraft}
                  onSend={sendMessage}
                  onNewChat={startNewChat}
                  onSelectConv={setActiveConvId}
                  onDeleteConv={requestDeleteConv}
                  onClose={() => setMeridianCompanionOpen(false)}
                />
              </aside>
            )}
          </div>

          {!meridianCompanionOpen && (
            <button
              type="button"
              className="meridian-fab"
              title="唤起 Meridian 伴读（Ctrl+K）"
              onClick={() => setMeridianCompanionOpen(true)}
            >
              <span aria-hidden>🧭</span>
              <span>Meridian</span>
            </button>
          )}

          {error && <div className="error-toast reading-error-toast" role="alert">{error}</div>}
        </div>
      )}

      {!isReading && shelfContextMenu && (
        <ShelfContextMenu
          x={shelfContextMenu.x}
          y={shelfContextMenu.y}
          name={shelfContextMenu.shelf.name}
          onRename={() => {
            setRenameShelfTarget(shelfContextMenu.shelf);
            setShelfContextMenu(null);
          }}
          onDelete={() => {
            setPendingDeleteShelfId(shelfContextMenu.shelf.id);
            setShelfContextMenu(null);
          }}
          onClose={() => setShelfContextMenu(null)}
        />
      )}

      <LibrarySheet
        open={libraryOpen}
        shelves={shelves}
        defaultShelfId={ingestDefaultShelfId}
        onClose={() => setLibraryOpen(false)}
        onSubmit={handleIngest}
      />

      <IngestToastStack jobs={ingestJobs} onDismiss={dismissIngestJob} />

      <ConfirmDialog
        open={pendingDeleteId != null}
        title="删除这段对话？"
        description={`「${pendingDelete?.title || `话题 #${pendingDeleteId}`}」删除后无法恢复。`}
        confirmLabel="删除"
        busy={deletingConvId != null}
        onCancel={() => {
          if (deletingConvId == null) setPendingDeleteId(null);
        }}
        onConfirm={() => {
          void confirmDeleteConv();
        }}
      />

      <ConfirmDialog
        open={pendingDeleteSourceId != null}
        title="删除这份资料？"
        description={`「${pendingDeleteSource?.title || pendingDeleteSourceId}」将从仓库与向量索引中移除，无法恢复。`}
        confirmLabel="删除"
        busy={deletingSourceId != null}
        onCancel={() => {
          if (deletingSourceId == null) setPendingDeleteSourceId(null);
        }}
        onConfirm={() => {
          void confirmDeleteSource();
        }}
      />

      <RenameSourceDialog
        open={renameTarget != null}
        currentTitle={renameTarget?.title ?? ""}
        busy={renamingSource}
        onCancel={() => {
          if (!renamingSource) setRenameTarget(null);
        }}
        onConfirm={(title) => {
          void confirmRenameSource(title);
        }}
      />

      <ConfirmDialog
        open={pendingDeleteShelfId != null}
        title="删除这个资料架？"
        description={
          pendingDeleteShelf
            ? `「${pendingDeleteShelf.name}」将被删除，架内的 ${shelfCounts[pendingDeleteShelf.id] ?? 0} 份资料会移至「未分类」。`
            : "资料架删除后，架内资料会移至「未分类」。"
        }
        confirmLabel="删除"
        busy={deletingShelfId != null}
        onCancel={() => {
          if (deletingShelfId == null) setPendingDeleteShelfId(null);
        }}
        onConfirm={() => {
          void confirmDeleteShelf();
        }}
      />

      <RenameSourceDialog
        open={renameShelfTarget != null}
        heading="重命名资料架"
        placeholder="输入新名称"
        currentTitle={renameShelfTarget?.name ?? ""}
        maxLength={20}
        busy={renamingShelf}
        onCancel={() => {
          if (!renamingShelf) setRenameShelfTarget(null);
        }}
        onConfirm={(name) => {
          void confirmRenameShelf(name);
        }}
      />

      <CreateShelfDialog
        open={createShelfOpen}
        busy={creatingShelf}
        onCancel={() => {
          if (!creatingShelf) setCreateShelfOpen(false);
        }}
        onConfirm={(name) => {
          void handleCreateShelf(name);
        }}
      />
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [username, setUsername] = useState(() => localStorage.getItem(USER_KEY) || "");

  function handleAuth(accessToken: string, user: string) {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(USER_KEY, user);
    setToken(accessToken);
    setUsername(user);
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUsername("");
  }

  if (!token) return <AuthScreen onAuth={handleAuth} />;
  return <Workspace token={token} username={username} onLogout={logout} />;
}
