import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type CurrentUser = components["schemas"]["CurrentUserResponse"];
export type DocumentItem = components["schemas"]["DocumentResponse"];
export type QuestionAnswer = components["schemas"]["QuestionResponse"];
export type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];
export type ConversationDetail = components["schemas"]["ConversationDetailResponse"];
export type IndexStatus = components["schemas"]["IndexStatusResponse"];
export type WorkspaceRole = CurrentUser["workspace_role"];

const TOKEN_KEY = "securedoc.access-token";

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = getAccessToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401 && getAccessToken()) {
      setAccessToken(null);
      window.dispatchEvent(new Event("securedoc:unauthorized"));
    }
    return response;
  },
};

const client = createClient<paths>({ baseUrl: import.meta.env.VITE_API_BASE_URL ?? "" });
client.use(authMiddleware);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code = "REQUEST_FAILED",
    readonly status = 0,
    readonly requestId?: string,
    readonly retryAfter?: number,
  ) {
    super(message);
  }
}

function throwApiError(error: unknown, response: Response): never {
  const payload = error as components["schemas"]["ErrorResponse"] | undefined;
  const retryHeader = response.headers.get("Retry-After");
  throw new ApiError(
    payload?.error?.message || friendlyMessage(response.status),
    payload?.error?.code,
    response.status,
    payload?.error?.request_id,
    retryHeader ? Number(retryHeader) : undefined,
  );
}

function friendlyMessage(status: number): string {
  if (status === 401) return "로그인이 필요합니다.";
  if (status === 403) return "현재 역할로 실행할 수 없는 작업입니다.";
  if (status === 409) return "동일한 문서 또는 정보가 이미 존재합니다.";
  if (status === 413) return "파일이 최대 허용 크기를 초과했습니다.";
  if (status === 415) return "지원하지 않는 파일 형식입니다.";
  if (status === 429) return "현재 질문 요청이 많습니다. 잠시 후 다시 시도해 주세요.";
  if (status === 503) return "서비스 일부가 아직 준비되지 않았습니다.";
  if (status === 504) return "답변 생성 시간이 초과되었습니다.";
  return "요청을 처리하지 못했습니다.";
}

export const api = {
  async login(email: string, password: string) {
    const { data, error, response } = await client.POST("/api/v1/auth/login", {
      body: { email, password },
    });
    if (!data) throwApiError(error, response);
    return data;
  },
  async me() {
    const { data, error, response } = await client.GET("/api/v1/auth/me");
    if (!data) throwApiError(error, response);
    return data;
  },
  async documents(keyword?: string) {
    const { data, error, response } = await client.GET("/api/v1/documents", {
      params: { query: keyword ? { keyword } : {} },
    });
    if (!data) throwApiError(error, response);
    return data;
  },
  async ask(question: string, conversationId?: string) {
    const { data, error, response } = await client.POST("/api/v1/questions", {
      body: { question, conversation_id: conversationId },
    });
    if (!data) throwApiError(error, response);
    return data;
  },
  async conversations() {
    const { data, error, response } = await client.GET("/api/v1/conversations");
    if (!data) throwApiError(error, response);
    return data;
  },
  async conversation(conversationId: string) {
    const { data, error, response } = await client.GET(
      "/api/v1/conversations/{conversation_id}",
      { params: { path: { conversation_id: conversationId } } },
    );
    if (!data) throwApiError(error, response);
    return data;
  },
  async upload(file: File) {
    const formData = new FormData();
    formData.set("file", file);
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1/documents/upload`, {
      method: "POST",
      headers: getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {},
      body: formData,
    });
    const payload = await response.json().catch(() => undefined);
    if (!response.ok) throwApiError(payload, response);
    return payload as components["schemas"]["DocumentUploadResponse"];
  },
  async deleteDocument(documentId: string) {
    const { data, error, response } = await client.DELETE("/api/v1/documents/{document_id}", {
      params: { path: { document_id: documentId } },
    });
    if (!data) throwApiError(error, response);
    return data;
  },
  async indexStatus() {
    const { data, error, response } = await client.GET("/api/v1/index/status");
    if (!data) throwApiError(error, response);
    return data;
  },
  async rebuildIndex() {
    const { data, error, response } = await client.POST("/api/v1/index/update");
    if (!data) throwApiError(error, response);
    return data;
  },
  async createUser(body: {
    email: string;
    display_name: string;
    password: string;
    workspace_role: WorkspaceRole;
  }) {
    const { data, error, response } = await client.POST("/api/v1/auth/users", { body });
    if (!data) throwApiError(error, response);
    return data;
  },
  async changePassword(currentPassword: string, newPassword: string) {
    const { error, response } = await client.POST("/api/v1/auth/change-password", {
      body: { current_password: currentPassword, new_password: newPassword },
    });
    if (!response.ok) throwApiError(error, response);
  },
  async ready() {
    const { data, error, response } = await client.GET("/api/v1/ready");
    if (!data) throwApiError(error, response);
    return data;
  },
};
