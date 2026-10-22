import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUp,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Copy,
  FileText,
  PanelRightOpen,
  ShieldQuestion,
  Sparkles,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router";
import remarkGfm from "remark-gfm";

import { api, type QuestionAnswer } from "@/api/client";
import { useChat } from "@/chat/chat-context";
import { Badge, Button, Dialog, ErrorNotice, Spinner } from "@/components/ui";

const suggestions = [
  "계정이 잠기는 조건과 해제 절차를 알려줘",
  "백업 보존 기간을 정책별로 비교해줘",
  "원격 접속 시 지켜야 할 사항을 체크리스트로 만들어줘",
];

export function ChatPage() {
  const documents = useQuery({ queryKey: ["documents"], queryFn: () => api.documents() });
  const {
    query,
    setQuery,
    exchanges,
    submitting,
    loadingConversation,
    conversationError,
    submit,
  } = useChat();
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [mobileEvidence, setMobileEvidence] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [exchanges, submitting]);

  useEffect(() => {
    const latestCitation = exchanges.at(-1)?.answer?.citations[0];
    if (latestCitation) setActiveCitation((current) => current ?? latestCitation);
  }, [exchanges]);

  useEffect(() => {
    if (exchanges.length === 0) setActiveCitation(null);
  }, [exchanges.length]);

  const evidencePanel = (
    <EvidencePanel
      citation={activeCitation}
      document={documents.data?.find((item) => item.file_name === activeCitation)}
      onClose={() => setActiveCitation(null)}
    />
  );

  const selectCitation = (citation: string) => {
    setActiveCitation(citation);
    if (!window.matchMedia("(min-width: 1280px)").matches) {
      setMobileEvidence(true);
    }
  };

  return (
    <div className="grid h-[calc(100vh-4rem)] min-h-[620px] xl:grid-cols-[minmax(460px,1fr)_340px]">
      <section className="relative flex min-h-0 flex-col bg-[#f8fafc]">
        <div className="flex items-center justify-between border-b border-slate-200/80 bg-white/80 px-4 py-3 backdrop-blur sm:px-6">
          <div>
            <div className="flex items-center gap-2"><ShieldQuestion className="size-4 text-indigo-600" /><h1 className="text-sm font-bold text-slate-900">질문과 근거</h1></div>
            <p className="mt-0.5 text-xs text-slate-400">현재 Workspace의 모든 문서를 검색합니다</p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" className="xl:hidden" onClick={() => setMobileEvidence(true)}>
              <PanelRightOpen className="size-4" /> 근거
            </Button>
          </div>
        </div>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          <div className="mx-auto max-w-3xl">
            {conversationError && <div className="mb-5"><ErrorNotice message={conversationError} /></div>}
            {loadingConversation ? (
              <div className="flex min-h-[45vh] items-center justify-center gap-3 text-sm text-slate-500"><Spinner /> 대화를 불러오는 중</div>
            ) : exchanges.length === 0 ? (
              <EmptyChat onSelect={submit} documentCount={documents.data?.length ?? 0} />
            ) : (
              <div className="space-y-9">
                {exchanges.map((exchange) => (
                  <article key={exchange.id}>
                    <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-slate-900 px-4 py-3 text-sm leading-6 text-white shadow-sm">
                      {exchange.question}
                    </div>
                    <div className="mt-5 flex gap-3">
                      <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl bg-indigo-600 text-white shadow-sm"><Sparkles className="size-4" /></div>
                      <div className="min-w-0 flex-1">
                        {exchange.error ? (
                          <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{exchange.error}</div>
                        ) : exchange.answer ? (
                          <AnswerBlock
                            answer={exchange.answer}
                            elapsed={exchange.elapsed}
                            onCitation={selectCitation}
                          />
                        ) : (
                          <div aria-live="polite" className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
                            <Spinner className="text-indigo-600" /> 문서에서 답변을 찾고 있습니다…
                          </div>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="safe-bottom border-t border-slate-200 bg-white/90 px-4 pt-3 backdrop-blur sm:px-8">
          <form
            className="mx-auto max-w-3xl"
            onSubmit={(event) => { event.preventDefault(); void submit(); }}
          >
            <div className="relative rounded-2xl border border-slate-200 bg-white shadow-lg shadow-slate-200/60 focus-within:border-indigo-300 focus-within:ring-4 focus-within:ring-indigo-100">
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); }
                }}
                rows={2}
                maxLength={1000}
                className="block w-full resize-none rounded-2xl bg-transparent px-4 py-3.5 pr-14 text-sm leading-6 outline-none placeholder:text-slate-400"
                placeholder="조직 문서를 바탕으로 질문하세요…"
                aria-label="질문"
              />
              <Button type="submit" size="icon" className="absolute bottom-2.5 right-2.5 size-9 rounded-xl" disabled={!query.trim() || submitting} aria-label="질문 전송">
                {submitting ? <Spinner /> : <ArrowUp className="size-4" />}
              </Button>
            </div>
            <p className="mt-2 text-center text-[11px] text-slate-400">AI 답변에는 오류가 있을 수 있습니다. 중요한 결정 전 근거 문서를 확인하세요.</p>
          </form>
        </div>
      </section>

      <aside className="hidden min-h-0 border-l border-slate-200 bg-white xl:block">{evidencePanel}</aside>
      <Dialog open={mobileEvidence} onOpenChange={setMobileEvidence} title="근거 확인" description="답변 생성에 사용된 문서입니다.">
        <div className="-mx-6 -mb-6 h-[65vh]">{evidencePanel}</div>
      </Dialog>
    </div>
  );
}

function EmptyChat({ onSelect, documentCount }: { onSelect: (question: string) => void; documentCount: number }) {
  return (
    <div className="flex min-h-[55vh] flex-col justify-center">
      <div className="grid size-12 place-items-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-200"><Sparkles className="size-5" /></div>
      <h2 className="mt-6 text-2xl font-bold tracking-tight text-slate-950">문서에서 무엇을 확인할까요?</h2>
      <p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">
        현재 {documentCount}개 문서를 검색할 수 있습니다. 답변과 함께 사용된 문서의 출처를 표시합니다.
      </p>
      <div className="mt-7 grid gap-3 sm:grid-cols-2">
        {suggestions.map((suggestion) => (
          <button key={suggestion} onClick={() => void onSelect(suggestion)} className="group flex min-h-20 items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-4 text-left text-sm font-medium leading-6 text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md">
            {suggestion}<ChevronRight className="size-4 shrink-0 text-slate-300 transition group-hover:text-indigo-600" />
          </button>
        ))}
        <Link to="/app/documents" className="flex min-h-20 items-center gap-3 rounded-2xl border border-dashed border-slate-300 p-4 text-sm font-semibold text-slate-500 hover:border-indigo-300 hover:text-indigo-700">
          <BookOpen className="size-5" /> 검색할 문서 관리하기
        </Link>
      </div>
    </div>
  );
}

function AnswerBlock({ answer, elapsed, onCitation }: { answer: QuestionAnswer; elapsed?: number; onCitation: (citation: string) => void }) {
  return (
    <div>
      {answer.response_mode === "search_only" && (
        <div className="mb-4 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900">
          <strong>문서 검색 결과</strong>
          <p className="mt-1 text-xs">AI가 생성한 답변이 아닙니다. 아래 문서 발췌와 출처를 직접 확인해 주세요.</p>
        </div>
      )}
      {answer.requires_human_review && answer.response_mode !== "search_only" && (
        <div className="mb-4 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <div><strong>검토가 필요한 답변입니다.</strong><p className="mt-0.5 text-xs leading-5 text-amber-700">충분한 문서 근거를 확인하지 못했습니다. 중요한 결정에는 사용하지 마세요.</p></div>
        </div>
      )}
      <div className="markdown-answer"><ReactMarkdown remarkPlugins={[remarkGfm]}>{answer.answer}</ReactMarkdown></div>
      {answer.citations.length > 0 && (
        <div className="mt-5 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.1em] text-slate-500"><CheckCircle2 className="size-4 text-emerald-600" /> 사용한 근거 {answer.citations.length}개</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {answer.citations.map((citation, index) => (
              <button key={citation} onClick={() => onCitation(citation)} className="inline-flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 hover:bg-indigo-50 hover:text-indigo-700 hover:ring-indigo-200">
                <span className="text-indigo-600">[{index + 1}]</span>{citation}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="mt-3 flex items-center justify-between border-t border-slate-200 pt-3">
        <span className="text-[11px] text-slate-400">{elapsed ? `${elapsed}초 · ` : ""}{answer.citations.length}개 문서 근거</span>
        <button onClick={() => void navigator.clipboard.writeText(answer.answer)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="답변 복사"><Copy className="size-4" /></button>
      </div>
    </div>
  );
}

function EvidencePanel({ citation, document, onClose }: { citation: string | null; document?: { title: string; file_name: string; page_count: number }; onClose: () => void }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div><p className="text-sm font-bold text-slate-900">근거 확인</p><p className="mt-0.5 text-xs text-slate-400">출처와 문서 정보를 검증하세요</p></div>
        {citation && <button onClick={onClose} className="text-xs font-semibold text-slate-400 hover:text-slate-700">초기화</button>}
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-5">
        {!citation ? (
          <div className="flex h-full min-h-80 flex-col items-center justify-center text-center">
            <div className="grid size-12 place-items-center rounded-2xl bg-slate-100 text-slate-400"><FileSearchIcon /></div>
            <p className="mt-4 text-sm font-semibold text-slate-700">확인할 근거를 선택하세요</p>
            <p className="mt-2 max-w-52 text-xs leading-5 text-slate-400">답변 아래의 출처를 선택하면 문서 정보를 여기에서 확인할 수 있습니다.</p>
          </div>
        ) : (
          <div>
            <Badge tone="indigo">답변 근거</Badge>
            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex gap-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-white text-indigo-600 shadow-sm"><FileText className="size-5" /></div>
                <div className="min-w-0"><p className="break-words text-sm font-bold text-slate-900">{document?.title ?? citation}</p><p className="mt-1 break-all text-xs text-slate-400">{document?.file_name ?? citation}</p></div>
              </div>
              {document && <p className="mt-4 border-t border-slate-200 pt-3 text-xs text-slate-500">문서 페이지: {document.page_count || "확인되지 않음"}</p>}
            </div>
            <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-800">
              현재 API는 citation의 원문 문단과 페이지 위치를 반환하지 않습니다. 파일 이름은 실제 검색 결과이지만, 원문 미리보기는 구조화 citation API가 추가된 후 제공됩니다.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function FileSearchIcon() {
  return <FileText className="size-5" />;
}
