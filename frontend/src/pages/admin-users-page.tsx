import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate } from "react-router";
import { z } from "zod";

import { api, type WorkspaceRole } from "@/api/client";
import { useAuth } from "@/auth/auth-context";
import { Button, Card, ErrorNotice, Input, Label, PageHeading, Spinner } from "@/components/ui";

const schema = z.object({
  email: z.string().email("올바른 이메일을 입력하세요."),
  display_name: z.string().min(1, "표시 이름을 입력하세요.").max(200),
  password: z.string().min(12, "임시 비밀번호는 12자 이상이어야 합니다."),
  workspace_role: z.enum(["VIEWER", "EDITOR", "ADMIN"]),
});
type Values = z.infer<typeof schema>;

export function AdminPage() {
  const { user } = useAuth();
  const [created, setCreated] = useState("");
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { workspace_role: "VIEWER" } });
  const mutation = useMutation({ mutationFn: (values: Values) => api.createUser(values), onSuccess: (data) => { setCreated(data.email); reset(); } });
  if (user?.workspace_role !== "ADMIN") return <Navigate to="/app/chat" replace />;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <PageHeading eyebrow="Administration" title="관리자 페이지" description="Workspace의 사용자와 접근 권한을 한곳에서 안전하게 관리합니다." />
      <section aria-labelledby="user-management-title" className="mt-8">
        <div className="mb-5 flex items-start gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-900 text-white"><ShieldCheck className="size-5" /></div>
          <div>
            <h2 id="user-management-title" className="text-lg font-bold text-slate-950">사용자 관리</h2>
            <p className="mt-1 text-sm text-slate-500">사용자를 추가하고 최소 권한 원칙에 따라 Workspace 역할을 지정합니다.</p>
          </div>
        </div>
        <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
          <Card className="p-6">
          <div className="mb-6 flex items-center gap-3"><div className="grid size-10 place-items-center rounded-xl bg-indigo-50 text-indigo-600"><UserPlus className="size-5" /></div><div><h2 className="font-bold text-slate-900">새 사용자 추가</h2><p className="text-xs text-slate-400">임시 비밀번호는 별도 보안 채널로 전달하세요.</p></div></div>
          {mutation.isError && <div className="mb-5"><ErrorNotice message={mutation.error.message} /></div>}
          {created && <div className="mb-5 flex gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"><CheckCircle2 className="size-4 shrink-0" />{created} 사용자를 추가했습니다.</div>}
          <form className="grid gap-5 sm:grid-cols-2" onSubmit={handleSubmit((values) => { setCreated(""); mutation.mutate(values); })}>
            <div><Label htmlFor="display_name">표시 이름</Label><Input id="display_name" {...register("display_name")} />{errors.display_name && <p className="mt-1 text-xs text-red-600">{errors.display_name.message}</p>}</div>
            <div><Label htmlFor="email">이메일</Label><Input id="email" type="email" {...register("email")} />{errors.email && <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>}</div>
            <div><Label htmlFor="password">임시 비밀번호</Label><Input id="password" type="password" autoComplete="new-password" {...register("password")} />{errors.password && <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>}</div>
            <div><Label htmlFor="role">Workspace 역할</Label><select id="role" className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3.5 text-sm outline-none focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100" {...register("workspace_role")}><option value="VIEWER">VIEWER</option><option value="EDITOR">EDITOR</option><option value="ADMIN">ADMIN</option></select></div>
            <div className="sm:col-span-2 flex justify-end"><Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? <Spinner /> : <UserPlus className="size-4" />} 사용자 추가</Button></div>
          </form>
          </Card>
          <div className="space-y-4">
            <RoleCard role="VIEWER" copy="문서 조회와 RAG 질문" />
            <RoleCard role="EDITOR" copy="VIEWER 권한 + 문서 관리" />
            <RoleCard role="ADMIN" copy="EDITOR 권한 + 사용자·인덱스 관리" />
          </div>
        </div>
      </section>
    </div>
  );
}

function RoleCard({ role, copy }: { role: WorkspaceRole; copy: string }) {
  return <Card className="p-4"><div className="flex items-center gap-3"><div className="grid size-9 place-items-center rounded-xl bg-slate-100 text-slate-600">{role === "ADMIN" ? <KeyRound className="size-4" /> : <Users className="size-4" />}</div><div><p className="text-sm font-bold text-slate-900">{role}</p><p className="mt-0.5 text-xs text-slate-500">{copy}</p></div></div></Card>;
}
