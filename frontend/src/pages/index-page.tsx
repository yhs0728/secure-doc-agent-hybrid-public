import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Database, FileStack, RefreshCw, Ruler, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { useAuth } from "@/auth/auth-context";
import { Badge, Button, Card, Dialog, ErrorNotice, PageHeading, Spinner } from "@/components/ui";

export function IndexPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const status = useQuery({ queryKey: ["index-status"], queryFn: api.indexStatus, retry: false,
    refetchInterval: (query) => query.state.data?.status === "indexing" ? 2000 : false });
  const rebuild = useMutation({
    mutationFn: api.rebuildIndex,
    onSuccess: async () => { setConfirmOpen(false); await queryClient.invalidateQueries({ queryKey: ["index-status"] }); },
  });

  const metrics = status.data ? [
    { label: "문서", value: status.data.document_count.toLocaleString(), icon: FileStack, copy: "검색에 포함된 문서" },
    { label: "청크", value: status.data.chunk_count.toLocaleString(), icon: Boxes, copy: "벡터 검색 단위" },
    { label: "청크 크기", value: String(status.data.chunk_size), icon: Ruler, copy: `Overlap ${status.data.chunk_overlap}` },
  ] : [];

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <PageHeading eyebrow="Retrieval" title="검색 인덱스" description="OpenSearch에 반영된 문서와 청크 상태를 확인합니다. 전체 재구축은 ADMIN만 실행할 수 있습니다." actions={status.data && <Badge tone="green"><span className="size-1.5 rounded-full bg-emerald-500" /> {status.data.status}</Badge>} />
      {status.isLoading && <Card className="flex items-center justify-center gap-2 p-16 text-sm text-slate-500"><Spinner /> 인덱스 상태 확인 중</Card>}
      {status.isError && <ErrorNotice message={status.error.message} />}
      {status.data && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            {metrics.map((metric) => <Card key={metric.label} className="p-5"><div className="flex items-start justify-between"><div><p className="text-sm font-semibold text-slate-500">{metric.label}</p><p className="mt-3 text-3xl font-bold tracking-tight text-slate-950">{metric.value}</p><p className="mt-1 text-xs text-slate-400">{metric.copy}</p></div><div className="grid size-10 place-items-center rounded-xl bg-indigo-50 text-indigo-600"><metric.icon className="size-5" /></div></div></Card>)}
          </div>
          <Card className="mt-5 overflow-hidden">
            <div className="border-b border-slate-100 p-5"><h2 className="font-bold text-slate-900">인덱스 구성</h2><p className="mt-1 text-sm text-slate-500">현재 검색 서비스가 사용하는 임베딩과 문서 분할 설정입니다.</p></div>
            <dl className="divide-y divide-slate-100">
              <Row label="검색 백엔드" value="OpenSearch" icon={<Database className="size-4" />} />
              <Row label="임베딩 모델" value={status.data.embedding_model} icon={<ShieldCheck className="size-4" />} />
              <Row label="청크 설정" value={`${status.data.chunk_size}자 · overlap ${status.data.chunk_overlap}`} icon={<Ruler className="size-4" />} />
            </dl>
          </Card>
          {user?.workspace_role === "ADMIN" && (
            <Card className="mt-5 flex flex-col justify-between gap-4 p-5 sm:flex-row sm:items-center">
              <div><h2 className="font-bold text-slate-900">전체 인덱스 재구축</h2><p className="mt-1 text-sm leading-6 text-slate-500">사용 가능한 문서를 다시 분석하고 검증된 인덱스로 alias를 교체합니다.</p></div>
              <Button variant="secondary" onClick={() => setConfirmOpen(true)}><RefreshCw className="size-4" /> 재구축</Button>
            </Card>
          )}
        </>
      )}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen} title="검색 인덱스를 재구축할까요?" description="문서 수와 임베딩 처리량에 따라 시간이 오래 걸릴 수 있습니다.">
        {rebuild.isError && <div className="mb-4"><ErrorNotice message={rebuild.error.message} /></div>}
        <div className="rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">기존 활성 인덱스는 새 인덱스 검증이 완료될 때까지 유지됩니다. 동시에 여러 재구축을 실행하지 마세요.</div>
        <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => setConfirmOpen(false)}>취소</Button><Button disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>{rebuild.isPending && <Spinner />} 재구축 시작</Button></div>
      </Dialog>
    </div>
  );
}

function Row({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return <div className="grid gap-2 px-5 py-4 sm:grid-cols-[180px_1fr]"><dt className="flex items-center gap-2 text-sm font-semibold text-slate-500">{icon}{label}</dt><dd className="break-all text-sm font-medium text-slate-800">{value}</dd></div>;
}
