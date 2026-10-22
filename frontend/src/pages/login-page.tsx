import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, CheckCircle2, Eye, EyeOff, FileSearch2, LockKeyhole, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router";
import { z } from "zod";

import { useAuth } from "@/auth/auth-context";
import { Button, ErrorNotice, Input, Label, Spinner } from "@/components/ui";

const loginSchema = z.object({
  email: z.string().email("올바른 이메일 주소를 입력하세요."),
  password: z.string().min(12, "비밀번호는 12자 이상이어야 합니다."),
});

type LoginValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });

  if (user) return <Navigate to="/app/chat" replace />;

  const submit = async (values: LoginValues) => {
    setError("");
    try {
      await login(values.email, values.password);
      const redirect = (location.state as { from?: string } | null)?.from ?? "/app/chat";
      navigate(redirect, { replace: true });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "로그인하지 못했습니다.");
    }
  };

  return (
    <div className="grid min-h-screen bg-white lg:grid-cols-[1.05fr_0.95fr]">
      <section className="relative hidden overflow-hidden bg-slate-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -left-24 top-24 size-80 rounded-full bg-indigo-500/15 blur-3xl" />
        <div className="absolute bottom-0 right-0 size-96 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <div className="grid size-11 place-items-center rounded-2xl bg-indigo-500"><ShieldCheck className="size-6" /></div>
          <div>
            <p className="font-bold">SecureDoc</p>
            <p className="text-xs uppercase tracking-[0.16em] text-slate-400">Evidence Workspace</p>
          </div>
        </div>

        <div className="relative max-w-xl">
          <p className="mb-5 text-sm font-bold uppercase tracking-[0.2em] text-indigo-300">Grounded answers, visible evidence</p>
          <h1 className="text-5xl font-bold leading-[1.12] tracking-tight">
            답변을 믿기 전에<br />근거를 확인하세요.
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-slate-300">
            조직의 문서를 안전하게 검색하고, 모든 답변이 어떤 자료에서 나왔는지 한 화면에서 검증합니다.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {[
              [FileSearch2, "근거 중심", "문서 출처 확인"],
              [LockKeyhole, "역할 기반", "권한별 접근 제어"],
              [CheckCircle2, "검증 가능", "검토 필요 표시"],
            ].map(([Icon, title, copy]) => {
              const ItemIcon = Icon as typeof FileSearch2;
              return (
                <div key={String(title)} className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur">
                  <ItemIcon className="mb-5 size-5 text-indigo-300" />
                  <p className="text-sm font-bold">{String(title)}</p>
                  <p className="mt-1 text-xs text-slate-400">{String(copy)}</p>
                </div>
              );
            })}
          </div>
        </div>
        <p className="relative text-xs text-slate-500">SecureDoc는 중요한 결정을 대신하지 않습니다. 원문과 조직 정책을 함께 확인하세요.</p>
      </section>

      <section className="flex items-center justify-center bg-[#f8fafc] px-5 py-12">
        <div className="w-full max-w-md">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <div className="grid size-10 place-items-center rounded-xl bg-indigo-600 text-white"><ShieldCheck className="size-5" /></div>
            <span className="font-bold">SecureDoc</span>
          </div>
          <div className="mb-8">
            <p className="text-sm font-bold text-indigo-600">Workspace 로그인</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-950">다시 오신 것을 환영합니다</h2>
            <p className="mt-3 text-sm leading-6 text-slate-500">조직에서 발급받은 계정으로 로그인하세요.</p>
          </div>

          <form className="space-y-5" onSubmit={handleSubmit(submit)} noValidate>
            {error && <ErrorNotice message={error} />}
            <div>
              <Label htmlFor="email">이메일</Label>
              <Input id="email" type="email" autoComplete="username" placeholder="name@company.com" {...register("email")} />
              {errors.email && <p className="mt-1.5 text-xs text-red-600">{errors.email.message}</p>}
            </div>
            <div>
              <div className="flex items-center justify-between"><Label htmlFor="password">비밀번호</Label></div>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="12자 이상 입력"
                  className="pr-12"
                  {...register("password")}
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-xl text-slate-500 transition hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500"
                  aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 표시"}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword((visible) => !visible)}
                >
                  {showPassword ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
                </button>
              </div>
              {errors.password && <p className="mt-1.5 text-xs text-red-600">{errors.password.message}</p>}
            </div>
            <Button className="w-full" type="submit" disabled={isSubmitting}>
              {isSubmitting ? <><Spinner /> 로그인 중</> : <>로그인 <ArrowRight className="size-4" /></>}
            </Button>
          </form>
          <div className="mt-8 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs leading-5 text-slate-500">
            계정이 없거나 권한을 변경해야 한다면 Workspace 관리자에게 문의하세요.
          </div>
        </div>
      </section>
    </div>
  );
}
