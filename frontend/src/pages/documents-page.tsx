import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, File, FilePlus2, Search, Trash2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

import { api, type DocumentItem } from "@/api/client";
import { useAuth } from "@/auth/auth-context";
import { Badge, Button, Dialog, ErrorNotice, Input, PageHeading, Spinner } from "@/components/ui";
import { formatBytes } from "@/lib/utils";

const ACCEPTED = ".pdf,.docx,.txt,.csv";
const MAX_SIZE = 25 * 1024 * 1024;

export function DocumentsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleting, setDeleting] = useState<DocumentItem | null>(null);
  const documents = useQuery({ queryKey: ["documents", keyword], queryFn: () => api.documents(keyword || undefined),
    refetchInterval: (query) => query.state.data?.some((document) => document.processing_status === "PENDING") ? 2000 : false });
  const canEdit = user?.workspace_role === "EDITOR" || user?.workspace_role === "ADMIN";

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => api.deleteDocument(documentId),
    onSuccess: async () => {
      setDeleting(null);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      await queryClient.invalidateQueries({ queryKey: ["index-status"] });
    },
  });

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <PageHeading
        eyebrow="Knowledge base"
        title="문서"
        description="RAG 검색에 사용되는 Workspace 문서를 관리합니다. 업로드된 문서는 비동기로 처리된 뒤 검색에 반영됩니다."
        actions={canEdit ? <Button onClick={() => setUploadOpen(true)}><FilePlus2 className="size-4" /> 문서 업로드</Button> : undefined}
      />

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col justify-between gap-3 border-b border-slate-200 p-4 sm:flex-row sm:items-center">
          <div className="relative w-full sm:max-w-sm">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
            <Input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="제목 또는 파일명 검색" className="pl-9" />
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-500"><Badge tone="green"><Check className="size-3" /> 문서 목록</Badge>{documents.data?.length ?? 0}개 문서</div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-[0.12em] text-slate-500">
              <tr><th className="px-5 py-3">문서</th><th className="px-5 py-3">형식</th><th className="px-5 py-3">상태</th><th className="px-5 py-3">페이지</th><th className="px-5 py-3 text-right">작업</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {documents.data?.map((document) => (
                <tr key={document.document_id} className="group hover:bg-slate-50/70">
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="grid size-10 place-items-center rounded-xl bg-indigo-50 text-indigo-600"><File className="size-5" /></div>
                      <div><p className="max-w-md truncate text-sm font-semibold text-slate-900">{document.title}</p><p className="mt-1 max-w-md truncate text-xs text-slate-400">{document.file_name}</p></div>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-sm font-medium uppercase text-slate-500">{document.file_name.split(".").pop() ?? "-"}</td>
                  <td className="px-5 py-4"><Badge tone={document.processing_status === "FAILED" ? "red" : document.processing_status === "PENDING" ? "indigo" : "green"}>
                    {document.processing_status === "PENDING" ? "처리 중" : document.processing_status === "FAILED" ? "처리 실패" : "사용 가능"}
                  </Badge></td>
                  <td className="px-5 py-4 text-sm text-slate-500">{document.page_count || "-"}</td>
                  <td className="px-5 py-4 text-right">
                    {canEdit && <Button variant="ghost" size="icon" className="text-slate-400 hover:text-red-600" onClick={() => setDeleting(document)} aria-label={`${document.title} 삭제`}><Trash2 className="size-4" /></Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {documents.isLoading && <div className="flex items-center justify-center gap-2 p-12 text-sm text-slate-500"><Spinner /> 문서를 불러오는 중</div>}
        {documents.isError && <div className="p-5"><ErrorNotice message={documents.error.message} /></div>}
        {!documents.isLoading && !documents.isError && documents.data?.length === 0 && (
          <div className="flex flex-col items-center py-16 text-center">
            <div className="grid size-12 place-items-center rounded-2xl bg-slate-100 text-slate-400"><File className="size-5" /></div>
            <p className="mt-4 text-sm font-semibold text-slate-800">문서가 없습니다</p>
            <p className="mt-1 text-xs text-slate-400">검색어를 바꾸거나 첫 문서를 업로드하세요.</p>
          </div>
        )}
      </div>

      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} />
      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)} title="문서를 삭제하시겠습니까?" description={deleting ? `“${deleting.title}”의 원본과 검색 데이터 삭제를 요청합니다.` : undefined}>
        {deleteMutation.isError && <div className="mb-4"><ErrorNotice message={deleteMutation.error.message} /></div>}
        <div className="rounded-xl bg-red-50 p-4 text-sm leading-6 text-red-800"><AlertCircle className="mr-2 inline size-4" />삭제 요청 후 Object Storage와 검색 인덱스에서 비동기로 제거될 수 있습니다.</div>
        <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => setDeleting(null)}>취소</Button><Button variant="danger" disabled={deleteMutation.isPending} onClick={() => deleting && deleteMutation.mutate(deleting.document_id)}>{deleteMutation.isPending && <Spinner />} 삭제</Button></div>
      </Dialog>
    </div>
  );
}

function UploadDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState("");
  const upload = useMutation({
    mutationFn: (selected: File) => api.upload(selected),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: ["documents"] }), 2500);
    },
  });

  const selectFile = (selected?: File) => {
    setLocalError("");
    upload.reset();
    if (!selected) return;
    const extension = `.${selected.name.split(".").pop()?.toLowerCase()}`;
    if (![".pdf", ".docx", ".txt", ".csv"].includes(extension)) return setLocalError("PDF, DOCX, TXT, CSV 파일만 업로드할 수 있습니다.");
    if (selected.size > MAX_SIZE) return setLocalError("파일은 25MB 이하여야 합니다.");
    setFile(selected);
  };

  const close = () => { setFile(null); setLocalError(""); upload.reset(); onOpenChange(false); };

  return (
    <Dialog open={open} onOpenChange={(value) => value ? onOpenChange(true) : close()} title="문서 업로드" description="파일 업로드가 끝난 뒤 텍스트 추출, 임베딩, 검색 반영이 비동기로 진행됩니다.">
      {!upload.isSuccess ? (
        <>
          <button
            type="button"
            className="flex w-full flex-col items-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 px-5 py-10 text-center transition hover:border-indigo-300 hover:bg-indigo-50/40"
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => { event.preventDefault(); selectFile(event.dataTransfer.files[0]); }}
          >
            <div className="grid size-12 place-items-center rounded-2xl bg-white text-indigo-600 shadow-sm"><UploadCloud className="size-5" /></div>
            <p className="mt-4 text-sm font-bold text-slate-800">파일을 놓거나 선택하세요</p>
            <p className="mt-1 text-xs text-slate-400">PDF, DOCX, TXT, CSV · 최대 25MB</p>
          </button>
          <input ref={inputRef} hidden type="file" accept={ACCEPTED} onChange={(event) => selectFile(event.target.files?.[0])} />
          {file && <div className="mt-4 flex items-center gap-3 rounded-xl border border-slate-200 p-3"><File className="size-5 text-indigo-600" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{file.name}</p><p className="text-xs text-slate-400">{formatBytes(file.size)}</p></div></div>}
          {(localError || upload.isError) && <div className="mt-4"><ErrorNotice message={localError || upload.error?.message || "업로드하지 못했습니다."} /></div>}
          <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={close}>취소</Button><Button disabled={!file || upload.isPending} onClick={() => file && upload.mutate(file)}>{upload.isPending && <Spinner />} 업로드</Button></div>
        </>
      ) : (
        <div className="py-5 text-center">
          <div className="mx-auto grid size-14 place-items-center rounded-full bg-emerald-50 text-emerald-600"><Check className="size-6" /></div>
          <p className="mt-4 text-base font-bold text-slate-900">업로드 요청이 완료됐습니다</p>
          <p className="mt-2 text-sm leading-6 text-slate-500">상태: {upload.data.status}. 처리가 완료되면 문서 목록과 검색 인덱스에 반영됩니다.</p>
          <Button className="mt-5" onClick={close}>확인</Button>
        </div>
      )}
    </Dialog>
  );
}
