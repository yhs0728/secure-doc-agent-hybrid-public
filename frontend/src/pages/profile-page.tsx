import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, Shield, UserRound } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { api } from "@/api/client";
import { useAuth } from "@/auth/auth-context";
import { Badge, Button, Card, ErrorNotice, Input, Label, PageHeading, Spinner } from "@/components/ui";
import { shortId } from "@/lib/utils";

const schema = z.object({ current: z.string().min(12), next: z.string().min(12, "새 비밀번호는 12자 이상이어야 합니다."), confirm: z.string() }).refine((value) => value.next === value.confirm, { path: ["confirm"], message: "새 비밀번호가 일치하지 않습니다." });
type Values = z.infer<typeof schema>;

export function ProfilePage() {
  const { user } = useAuth();
  const [success, setSuccess] = useState(false);
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema) });
  const mutation = useMutation({ mutationFn: (values: Values) => api.changePassword(values.current, values.next), onSuccess: () => { setSuccess(true); reset(); } });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
      <PageHeading eyebrow="Account" title="내 계정" description="현재 Workspace 권한을 확인하고 비밀번호를 변경합니다." />
      <Card className="mb-5 p-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <div className="grid size-14 place-items-center rounded-2xl bg-slate-900 text-white"><UserRound className="size-6" /></div>
          <div className="flex-1"><div className="flex items-center gap-2"><h2 className="font-bold text-slate-900">Workspace 사용자</h2><Badge tone="indigo">{user?.workspace_role}</Badge></div><p className="mt-2 text-xs text-slate-400">User {user ? shortId(user.user_id) : "-"} · Workspace {user ? shortId(user.workspace_id) : "-"}</p></div>
          <div className="flex items-center gap-2 text-xs font-semibold text-emerald-700"><Shield className="size-4" /> JWT 인증됨</div>
        </div>
      </Card>
      <Card className="p-6">
        <div className="mb-6 flex items-center gap-3"><div className="grid size-10 place-items-center rounded-xl bg-indigo-50 text-indigo-600"><KeyRound className="size-5" /></div><div><h2 className="font-bold text-slate-900">비밀번호 변경</h2><p className="text-xs text-slate-400">다른 서비스에서 사용하지 않는 12자 이상의 비밀번호를 사용하세요.</p></div></div>
        {mutation.isError && <div className="mb-5"><ErrorNotice message={mutation.error.message} /></div>}
        {success && <div className="mb-5 flex gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"><CheckCircle2 className="size-4" />비밀번호를 변경했습니다.</div>}
        <form className="max-w-md space-y-5" onSubmit={handleSubmit((values) => { setSuccess(false); mutation.mutate(values); })}>
          <div><Label htmlFor="current">현재 비밀번호</Label><Input id="current" type="password" autoComplete="current-password" {...register("current")} /></div>
          <div><Label htmlFor="next">새 비밀번호</Label><Input id="next" type="password" autoComplete="new-password" {...register("next")} />{errors.next && <p className="mt-1 text-xs text-red-600">{errors.next.message}</p>}</div>
          <div><Label htmlFor="confirm">새 비밀번호 확인</Label><Input id="confirm" type="password" autoComplete="new-password" {...register("confirm")} />{errors.confirm && <p className="mt-1 text-xs text-red-600">{errors.confirm.message}</p>}</div>
          <Button type="submit" disabled={mutation.isPending}>{mutation.isPending && <Spinner />} 비밀번호 변경</Button>
        </form>
      </Card>
    </div>
  );
}
