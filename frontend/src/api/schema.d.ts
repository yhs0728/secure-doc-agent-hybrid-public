export interface components {
  schemas: {
    LoginRequest: { email: string; password: string };
    TokenResponse: { access_token: string; token_type: string; expires_in: number };
    CurrentUserResponse: {
      user_id: string;
      organization_id: string;
      workspace_id: string;
      workspace_role: "VIEWER" | "EDITOR" | "ADMIN";
      auth_type: string;
    };
    DocumentResponse: {
      document_id: string;
      title: string;
      file_name: string;
      page_count: number;
      processing_status?: "PENDING" | "READY" | "FAILED" | "DELETING" | "DELETED";
      error_code?: string | null;
    };
    QuestionResponse: {
      answer: string;
      citations: string[];
      requires_human_review: boolean;
      response_mode?: "generated" | "search_only";
      response_reason?: string;
      conversation_id?: string | null;
    };
    ConversationSummaryResponse: {
      conversation_id: string;
      title: string;
      updated_at: string;
    };
    ConversationMessageResponse: {
      message_id: string;
      role: string;
      content: string;
      citations: string[];
      requires_human_review: boolean;
      response_mode?: "generated" | "search_only";
      response_reason?: string;
      created_at: string;
    };
    ConversationDetailResponse: components["schemas"]["ConversationSummaryResponse"] & {
      messages: components["schemas"]["ConversationMessageResponse"][];
    };
    DocumentUploadResponse: { file_name: string; size_bytes: number; status: string };
    DocumentDeleteResponse: { document_id: string; file_name: string; status: string };
    IndexStatusResponse: {
      status: string;
      document_count: number;
      chunk_count: number;
      embedding_model: string;
      chunk_size: number;
      chunk_overlap: number;
    };
    IndexUpdateResponse: {
      status: string;
      full_rebuild: boolean;
      added: string[];
      modified: string[];
      deleted: string[];
      unchanged: string[];
    };
    UserCreateResponse: {
      user_id: string;
      email: string;
      workspace_id: string;
      workspace_role: "VIEWER" | "EDITOR" | "ADMIN";
    };
    ErrorResponse: { error: { code: string; message: string; request_id: string } };
  };
}

type JsonResponse<T> = { content: { "application/json": T } };

export interface paths {
  "/api/v1/auth/login": {
    post: {
      requestBody: { content: { "application/json": components["schemas"]["LoginRequest"] } };
      responses: { 200: JsonResponse<components["schemas"]["TokenResponse"]> };
    };
  };
  "/api/v1/auth/me": {
    get: { responses: { 200: JsonResponse<components["schemas"]["CurrentUserResponse"]> } };
  };
  "/api/v1/auth/change-password": {
    post: {
      requestBody: {
        content: { "application/json": { current_password: string; new_password: string } };
      };
      responses: { 204: { content: never } };
    };
  };
  "/api/v1/auth/users": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            email: string;
            display_name: string;
            password: string;
            workspace_role: "VIEWER" | "EDITOR" | "ADMIN";
          };
        };
      };
      responses: { 201: JsonResponse<components["schemas"]["UserCreateResponse"]> };
    };
  };
  "/api/v1/documents": {
    get: {
      parameters: { query?: { keyword?: string } };
      responses: { 200: JsonResponse<components["schemas"]["DocumentResponse"][]> };
    };
  };
  "/api/v1/questions": {
    post: {
      requestBody: { content: { "application/json": { question: string; conversation_id?: string | null } } };
      responses: { 200: JsonResponse<components["schemas"]["QuestionResponse"]> };
    };
  };
  "/api/v1/conversations": {
    get: { responses: { 200: JsonResponse<components["schemas"]["ConversationSummaryResponse"][]> } };
  };
  "/api/v1/conversations/{conversation_id}": {
    get: {
      parameters: { path: { conversation_id: string } };
      responses: { 200: JsonResponse<components["schemas"]["ConversationDetailResponse"]> };
    };
  };
  "/api/v1/index/status": {
    get: { responses: { 200: JsonResponse<components["schemas"]["IndexStatusResponse"]> } };
  };
  "/api/v1/index/update": {
    post: { responses: { 200: JsonResponse<components["schemas"]["IndexUpdateResponse"]>; 202: JsonResponse<components["schemas"]["IndexUpdateResponse"]> } };
  };
  "/api/v1/documents/{document_id}": {
    delete: {
      parameters: { path: { document_id: string } };
      responses: { 200: JsonResponse<components["schemas"]["DocumentDeleteResponse"]> };
    };
  };
  "/api/v1/ready": {
    get: {
      responses: {
        200: JsonResponse<{ status: string; checks: Record<string, string> }>;
      };
    };
  };
}
