import { LoaderCircle } from "lucide-react";
import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";

import { useAuth } from "@/auth/auth-context";
import { ChatProvider } from "@/chat/chat-context";
import { AppShell } from "@/components/app-shell";
import { LoginPage } from "@/pages/login-page";

const ChatPage = lazy(() => import("@/pages/chat-page").then((module) => ({ default: module.ChatPage })));
const DocumentsPage = lazy(() => import("@/pages/documents-page").then((module) => ({ default: module.DocumentsPage })));
const IndexPage = lazy(() => import("@/pages/index-page").then((module) => ({ default: module.IndexPage })));
const ProfilePage = lazy(() => import("@/pages/profile-page").then((module) => ({ default: module.ProfilePage })));
const AdminPage = lazy(() => import("@/pages/admin-users-page").then((module) => ({ default: module.AdminPage })));

function PageFallback() {
  return <div className="flex min-h-[50vh] items-center justify-center gap-3 text-sm font-semibold text-slate-500"><LoaderCircle className="size-5 animate-spin text-indigo-600" /> 화면 불러오는 중</div>;
}

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="grid min-h-screen place-items-center bg-[#f5f7fb]"><div className="flex items-center gap-3 text-sm font-semibold text-slate-500"><LoaderCircle className="size-5 animate-spin text-indigo-600" /> Workspace 확인 중</div></div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/app" element={<Protected><ChatProvider><AppShell /></ChatProvider></Protected>}>
        <Route index element={<Navigate to="chat" replace />} />
        <Route path="chat" element={<Suspense fallback={<PageFallback />}><ChatPage /></Suspense>} />
        <Route path="documents" element={<Suspense fallback={<PageFallback />}><DocumentsPage /></Suspense>} />
        <Route path="index" element={<Suspense fallback={<PageFallback />}><IndexPage /></Suspense>} />
        <Route path="profile" element={<Suspense fallback={<PageFallback />}><ProfilePage /></Suspense>} />
        <Route path="admin" element={<Suspense fallback={<PageFallback />}><AdminPage /></Suspense>} />
        <Route path="admin/users" element={<Navigate to="/app/admin" replace />} />
      </Route>
      <Route path="/" element={<Navigate to="/app/chat" replace />} />
      <Route path="*" element={<Navigate to="/app/chat" replace />} />
    </Routes>
  );
}
