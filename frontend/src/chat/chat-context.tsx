import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  api,
  ApiError,
  type ConversationDetail,
  type ConversationSummary,
  type QuestionAnswer,
} from "@/api/client";
import { useAuth } from "@/auth/auth-context";

export interface Exchange {
  id: string;
  question: string;
  answer?: QuestionAnswer;
  error?: string;
  elapsed?: number;
}

interface StoredChat {
  conversationId: string | null;
  exchanges: Exchange[];
}

interface ChatValue {
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  conversationId: string | null;
  draftConversation: ConversationSummary | null;
  exchanges: Exchange[];
  submitting: boolean;
  loadingConversation: boolean;
  conversationError: string;
  submit: (question?: string) => Promise<void>;
  openConversation: (conversationId: string) => Promise<void>;
  newConversation: () => void;
}

const ChatContext = createContext<ChatValue | null>(null);
const STORAGE_PREFIX = "securedoc.chat-history";
const MAX_STORED_EXCHANGES = 50;

function isExchange(item: unknown): item is Exchange {
  return (
    typeof item === "object"
    && item !== null
    && typeof (item as Exchange).id === "string"
    && typeof (item as Exchange).question === "string"
  );
}

function normalizeExchanges(value: unknown): Exchange[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isExchange)
    .map((item) => item.answer || item.error
      ? item
      : { ...item, error: "페이지를 새로고침해 답변 생성이 중단되었습니다. 다시 질문해 주세요." })
    .slice(-MAX_STORED_EXCHANGES);
}

function readChat(storageKey: string): StoredChat {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (Array.isArray(value)) {
      const exchanges = normalizeExchanges(value);
      const conversationId = [...exchanges]
        .reverse()
        .find((item) => item.answer?.conversation_id)?.answer?.conversation_id ?? null;
      return { conversationId, exchanges };
    }
    if (typeof value === "object" && value !== null) {
      const stored = value as Partial<StoredChat>;
      return {
        conversationId: typeof stored.conversationId === "string" ? stored.conversationId : null,
        exchanges: normalizeExchanges(stored.exchanges),
      };
    }
  } catch {
    // Invalid or blocked session storage starts a clean local conversation.
  }
  return { conversationId: null, exchanges: [] };
}

function detailToExchanges(detail: ConversationDetail): Exchange[] {
  const exchanges: Exchange[] = [];
  for (const message of detail.messages) {
    if (message.role === "USER") {
      exchanges.push({ id: message.message_id, question: message.content });
      continue;
    }
    if (message.role !== "ASSISTANT") continue;
    const exchange = [...exchanges].reverse().find((item) => !item.answer && !item.error);
    if (!exchange) continue;
    exchange.answer = {
      answer: message.content,
      citations: message.citations,
      requires_human_review: message.requires_human_review,
      response_mode: message.response_mode,
      response_reason: message.response_reason,
      conversation_id: detail.conversation_id,
    };
  }
  return exchanges;
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const storageKey = `${STORAGE_PREFIX}:${user?.workspace_id ?? "unknown"}:${user?.user_id ?? "unknown"}`;
  const [storedChat] = useState(() => readChat(storageKey));
  const [query, setQuery] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(storedChat.conversationId);
  const [draftConversation, setDraftConversation] = useState<ConversationSummary | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>(storedChat.exchanges);
  const [submitting, setSubmitting] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [conversationError, setConversationError] = useState("");

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({
        conversationId,
        exchanges: exchanges.slice(-MAX_STORED_EXCHANGES),
      }));
    } catch {
      // The live in-memory conversation remains available when browser storage is blocked.
    }
  }, [conversationId, exchanges, storageKey]);

  const submit = useCallback(async (question = query) => {
    const normalized = question.trim();
    if (!normalized || submitting || loadingConversation) return;

    const id = crypto.randomUUID();
    const optimisticConversation = conversationId ? null : {
      conversation_id: `pending-${id}`,
      title: normalized.slice(0, 500),
      updated_at: new Date().toISOString(),
    };
    setQuery("");
    setConversationError("");
    setSubmitting(true);
    if (optimisticConversation) setDraftConversation(optimisticConversation);
    if (conversationId) {
      queryClient.setQueryData<ConversationSummary[]>(["conversations"], (current = []) => {
        const selected = current.find((item) => item.conversation_id === conversationId);
        if (!selected) return current;
        return [
          { ...selected, updated_at: new Date().toISOString() },
          ...current.filter((item) => item.conversation_id !== conversationId),
        ];
      });
    }
    setExchanges((current) => [...current, { id, question: normalized }]);
    const started = performance.now();

    try {
      const answer = await api.ask(normalized, conversationId ?? undefined);
      const elapsed = Math.round((performance.now() - started) / 100) / 10;
      if (answer.conversation_id) {
        setConversationId(answer.conversation_id);
        if (optimisticConversation) {
          queryClient.setQueryData<ConversationSummary[]>(["conversations"], (current = []) => [
            {
              ...optimisticConversation,
              conversation_id: answer.conversation_id!,
              updated_at: new Date().toISOString(),
            },
            ...current.filter((item) => item.conversation_id !== answer.conversation_id),
          ]);
        }
      }
      setExchanges((current) => current.map((item) => (
        item.id === id ? { ...item, answer, elapsed } : item
      )));
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setDraftConversation(null);
    } catch (caught) {
      const message = caught instanceof ApiError && caught.retryAfter
        ? `${caught.message} ${caught.retryAfter}초 후 다시 시도할 수 있습니다.`
        : caught instanceof Error ? caught.message : "답변을 생성하지 못했습니다.";
      setExchanges((current) => current.map((item) => (
        item.id === id ? { ...item, error: message } : item
      )));
      setDraftConversation(null);
    } finally {
      setSubmitting(false);
    }
  }, [conversationId, loadingConversation, query, queryClient, submitting]);

  const openConversation = useCallback(async (selectedId: string) => {
    if (submitting || loadingConversation) return;
    setLoadingConversation(true);
    setConversationError("");
    try {
      const detail = await api.conversation(selectedId);
      setConversationId(detail.conversation_id);
      setDraftConversation(null);
      setExchanges(detailToExchanges(detail));
      setQuery("");
    } catch (caught) {
      setConversationError(caught instanceof Error ? caught.message : "대화를 불러오지 못했습니다.");
    } finally {
      setLoadingConversation(false);
    }
  }, [loadingConversation, submitting]);

  const newConversation = useCallback(() => {
    if (submitting) return;
    setConversationId(null);
    setDraftConversation(null);
    setExchanges([]);
    setQuery("");
    setConversationError("");
  }, [submitting]);

  const value = useMemo(
    () => ({
      query,
      setQuery,
      conversationId,
      draftConversation,
      exchanges,
      submitting,
      loadingConversation,
      conversationError,
      submit,
      openConversation,
      newConversation,
    }),
    [
      query,
      conversationId,
      draftConversation,
      exchanges,
      submitting,
      loadingConversation,
      conversationError,
      submit,
      openConversation,
      newConversation,
    ],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatValue {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChat must be used inside ChatProvider");
  return value;
}
