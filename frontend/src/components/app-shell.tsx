import { useQuery } from "@tanstack/react-query";
import {
  BookOpenText,
  ChevronDown,
  CircleHelp,
  DatabaseZap,
  FileStack,
  LogOut,
  Menu,
  MessageSquarePlus,
  MessagesSquare,
  Settings2,
  ShieldCheck,
  UserCog,
  X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";

import { api } from "@/api/client";
import { useAuth } from "@/auth/auth-context";
import { useChat } from "@/chat/chat-context";
import { Badge, Button, Spinner } from "@/components/ui";
import { cn, shortId } from "@/lib/utils";

const primaryItems = [
  { to: "/app/documents", label: "문서", icon: FileStack },
  { to: "/app/index", label: "검색 인덱스", icon: DatabaseZap },
];

const navigationClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition",
    isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950",
  );

export function AppShell() {
  const { user, logout } = useAuth();
  const { conversationId, draftConversation, loadingConversation, submitting, newConversation, openConversation } = useChat();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const recentConversations = draftConversation
    ? [draftConversation, ...(conversations.data ?? []).filter((item) => item.conversation_id !== draftConversation.conversation_id)]
    : conversations.data ?? [];
  const activeConversationId = conversationId ?? draftConversation?.conversation_id ?? null;

  const startConversation = () => {
    newConversation();
    navigate("/app/chat");
    setMobileOpen(false);
  };

  const selectConversation = async (selectedId: string) => {
    if (selectedId.startsWith("pending-")) return;
    navigate("/app/chat");
    setMobileOpen(false);
    await openConversation(selectedId);
  };

  const sidebar = (
    <>
      <div className="flex h-20 shrink-0 items-center gap-3 px-5">
        <div className="grid size-10 place-items-center rounded-xl bg-indigo-600 text-white shadow-lg shadow-indigo-200">
          <ShieldCheck className="size-5" />
        </div>
        <div>
          <div className="text-[15px] font-extrabold tracking-tight text-slate-950">SecureDoc</div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Evidence Workspace</div>
        </div>
      </div>

      <nav className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-3 py-4" aria-label="주 메뉴">
        <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.17em] text-slate-400">Workspace</p>
        <div className="space-y-1">
          <button
            type="button"
            onClick={startConversation}
            disabled={submitting}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <MessageSquarePlus className="size-[18px]" /> 새 대화
          </button>
          <NavLink to="/app/chat" onClick={() => setMobileOpen(false)} className={navigationClass}>
            <MessagesSquare className="size-[18px]" /> 대화
          </NavLink>
          {primaryItems.map((item) => (
            <NavLink key={item.to} to={item.to} onClick={() => setMobileOpen(false)} className={navigationClass}>
              <item.icon className="size-[18px]" />
              {item.label}
            </NavLink>
          ))}
        </div>

        <p className="mb-2 mt-7 px-3 text-[10px] font-bold uppercase tracking-[0.17em] text-slate-400">최근 대화</p>
        {(conversations.isLoading || loadingConversation) && recentConversations.length === 0 && (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-400"><Spinner /> 대화 불러오는 중</div>
        )}
        {!conversations.isLoading && recentConversations.length === 0 && (
          <p className="px-3 py-3 text-xs leading-5 text-slate-400">첫 질문을 입력하면 대화가 여기에 저장됩니다.</p>
        )}
        <div className="space-y-1">
          {recentConversations.map((conversation) => {
            const active = conversation.conversation_id === activeConversationId;
            const pending = conversation.conversation_id.startsWith("pending-");
            return (
              <button
                key={conversation.conversation_id}
                type="button"
                disabled={pending || loadingConversation}
                onClick={() => void selectConversation(conversation.conversation_id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm transition disabled:cursor-wait disabled:opacity-70",
                  active ? "bg-indigo-50 font-semibold text-indigo-900" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950",
                )}
              >
                <MessagesSquare className={cn("size-4 shrink-0", active ? "text-indigo-600" : "text-slate-400")} />
                <span className="truncate">{conversation.title}</span>
              </button>
            );
          })}
        </div>

        {user?.workspace_role === "ADMIN" && (
          <>
            <p className="mb-2 mt-7 px-3 text-[10px] font-bold uppercase tracking-[0.17em] text-slate-400">Administration</p>
            <NavLink to="/app/admin" onClick={() => setMobileOpen(false)} className={navigationClass}>
              <UserCog className="size-[18px]" /> 관리자 페이지
            </NavLink>
          </>
        )}
      </nav>

      <div className="shrink-0 border-t border-slate-200 p-3">
        <NavLink to="/app/profile" onClick={() => setMobileOpen(false)} className="flex items-center gap-3 rounded-xl p-3 hover:bg-slate-100">
          <div className="grid size-9 place-items-center rounded-full bg-slate-900 text-xs font-bold text-white">{user?.workspace_role.slice(0, 1)}</div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-slate-900">{user?.workspace_role}</div>
            <div className="truncate text-xs text-slate-400">{user ? shortId(user.user_id) : ""}</div>
          </div>
          <ChevronDown className="size-4 text-slate-400" />
        </NavLink>
        <Button variant="ghost" className="mt-1 w-full justify-start text-slate-500" onClick={logout}><LogOut className="size-4" /> 로그아웃</Button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-[#f5f7fb]">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col border-r border-slate-200 bg-white lg:flex">{sidebar}</aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button aria-label="메뉴 닫기" className="absolute inset-0 bg-slate-950/40" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex h-full w-72 flex-col bg-white shadow-2xl">
            <button aria-label="메뉴 닫기" className="absolute right-3 top-4 rounded-lg p-2 hover:bg-slate-100" onClick={() => setMobileOpen(false)}><X className="size-5" /></button>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-slate-200/80 bg-[#f5f7fb]/90 px-4 backdrop-blur-xl sm:px-6">
          <div className="flex items-center gap-3">
            <button className="rounded-lg p-2 text-slate-600 hover:bg-white lg:hidden" onClick={() => setMobileOpen(true)} aria-label="메뉴 열기"><Menu className="size-5" /></button>
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><BookOpenText className="size-4 text-indigo-600" /> 보안 문서 Workspace</div>
              <p className="hidden text-xs text-slate-400 sm:block">답변보다 근거를 먼저 확인하세요</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone="green"><span className="size-1.5 rounded-full bg-emerald-500" /> 연결됨</Badge>
            <button className="hidden rounded-lg p-2 text-slate-500 hover:bg-white sm:block" aria-label="도움말"><CircleHelp className="size-5" /></button>
            <button className="hidden rounded-lg p-2 text-slate-500 hover:bg-white sm:block" aria-label="설정"><Settings2 className="size-5" /></button>
          </div>
        </header>
        <main><Outlet /></main>
      </div>
    </div>
  );
}
