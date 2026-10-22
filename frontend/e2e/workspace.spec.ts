import { expect, test, type Page, type Route } from "@playwright/test";

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page, options: { questionDelayMs?: number } = {}) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/v1/auth/login") return json(route, { access_token: "demo-token", token_type: "bearer", expires_in: 1800 });
    if (path === "/api/v1/auth/me") return json(route, { user_id: "12345678-1234-1234-1234-123456789012", organization_id: "org-123456789", workspace_id: "workspace-123456789", workspace_role: "ADMIN", auth_type: "jwt" });
    if (path === "/api/v1/conversations") return json(route, [
      { conversation_id: "conversation-saved", title: "저장된 보안 정책 질문", updated_at: "2026-10-16T10:00:00Z" },
    ]);
    if (path === "/api/v1/conversations/conversation-saved") return json(route, {
      conversation_id: "conversation-saved",
      title: "저장된 보안 정책 질문",
      updated_at: "2026-10-16T10:00:00Z",
      messages: [
        { message_id: "message-user", role: "USER", content: "저장된 질문", citations: [], requires_human_review: false, created_at: "2026-10-16T09:59:00Z" },
        { message_id: "message-assistant", role: "ASSISTANT", content: "저장된 대화의 답변입니다.", citations: ["security-policy.pdf"], requires_human_review: false, created_at: "2026-10-16T10:00:00Z" },
      ],
    });
    if (path === "/api/v1/documents") return json(route, [
      { document_id: "security-policy", title: "정보보안 정책", file_name: "security-policy.pdf", page_count: 18 },
      { document_id: "account-lock", title: "계정 잠금 정책", file_name: "account-lock-policy.docx", page_count: 6 },
      { document_id: "remote-access", title: "원격 접속 정책", file_name: "remote-access-policy.txt", page_count: 2 },
    ]);
    if (path === "/api/v1/index/status") return json(route, { status: "ready", document_count: 3, chunk_count: 84, embedding_model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", chunk_size: 800, chunk_overlap: 120 });
    if (path === "/api/v1/questions") {
      if (options.questionDelayMs) await new Promise((resolve) => setTimeout(resolve, options.questionDelayMs));
      return json(route, { answer: "일반 사용자는 **비밀번호를 90일마다 변경**해야 합니다. 관리자 계정에는 더 짧은 주기가 적용됩니다.", citations: ["security-policy.pdf", "account-lock-policy.docx"], requires_human_review: false, conversation_id: "conversation-new" });
    }
    return json(route, { error: { code: "NOT_FOUND", message: "Not found", request_id: "e2e" } }, 404);
  });
}

test("user can show and hide the entered password", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");

  const password = page.getByLabel("비밀번호", { exact: true });
  await password.fill("safe-password-1234");
  await expect(password).toHaveAttribute("type", "password");

  await page.getByRole("button", { name: "비밀번호 표시" }).click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(password).toHaveValue("safe-password-1234");

  await page.getByRole("button", { name: "비밀번호 숨기기" }).click();
  await expect(password).toHaveAttribute("type", "password");
});

test("user can reopen a saved conversation from the sidebar", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("이메일").fill("admin@example.com");
  await page.getByLabel("비밀번호", { exact: true }).fill("safe-password-1234");
  await page.getByRole("button", { name: /^로그인/ }).click();

  await page.getByRole("button", { name: /저장된 보안 정책 질문/ }).click();
  await expect(page.getByText("저장된 질문", { exact: true })).toBeVisible();
  await expect(page.getByText("저장된 대화의 답변입니다.", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /새 대화/ }).click();
  await expect(page.getByRole("heading", { name: "문서에서 무엇을 확인할까요?" })).toBeVisible();
});

test("a new question appears in the conversation sidebar immediately", async ({ page }) => {
  await mockApi(page, { questionDelayMs: 2_000 });
  await page.goto("/login");
  await page.getByLabel("이메일").fill("admin@example.com");
  await page.getByLabel("비밀번호", { exact: true }).fill("safe-password-1234");
  await page.getByRole("button", { name: /^로그인/ }).click();

  const question = "새 보안 정책을 비교해줘";
  await page.getByRole("textbox", { name: "질문", exact: true }).fill(question);
  await page.getByRole("button", { name: "질문 전송", exact: true }).click();

  await expect(page.getByRole("button", { name: new RegExp(question) })).toBeVisible();
  await expect(page.getByText("문서에서 답변을 찾고 있습니다…")).toBeVisible();
  await expect(page.getByText("비밀번호를 90일마다 변경", { exact: false })).toBeVisible();
});

test("authenticated user can inspect a grounded answer and its sources", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("이메일").fill("admin@example.com");
  await page.getByLabel("비밀번호", { exact: true }).fill("safe-password-1234");
  await page.getByRole("button", { name: /^로그인/ }).click();
  await expect(page.getByRole("heading", { name: "문서에서 무엇을 확인할까요?" })).toBeVisible();

  await page.getByRole("textbox", { name: "질문", exact: true }).fill("비밀번호 변경 주기를 알려줘");
  await page.getByRole("button", { name: "질문 전송", exact: true }).click();
  await expect(page.getByText("비밀번호를 90일마다 변경", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /security-policy.pdf/ }).click();
  await expect(page.getByText("답변 근거", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "문서", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/documents$/);
  await page.getByRole("link", { name: "대화", exact: true }).click();
  await expect(page.getByText("비밀번호를 90일마다 변경", { exact: false })).toBeVisible();

  await page.reload();
  await expect(page.getByText("비밀번호를 90일마다 변경", { exact: false })).toBeVisible();
  await page.screenshot({ path: "workspace-preview.png", fullPage: true });
});

test("admin can open the admin page and see user management", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("이메일").fill("admin@example.com");
  await page.getByLabel("비밀번호", { exact: true }).fill("safe-password-1234");
  await page.getByRole("button", { name: /^로그인/ }).click();

  await page.getByRole("link", { name: "관리자 페이지", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/admin$/);
  await expect(page.getByRole("heading", { name: "관리자 페이지", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "사용자 관리", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "사용자 추가", exact: true })).toBeVisible();
});

test("mobile user can open evidence without losing the conversation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await page.goto("/login");
  await page.locator('input[type="email"]').fill("admin@example.com");
  await page.locator('input[type="password"]').fill("safe-password-1234");
  await page.locator('form button[type="submit"]').click();
  await expect(page).toHaveURL(/\/chat$/);

  await page.locator("textarea").fill("password rotation policy");
  await page.locator('form button[type="submit"]').click();
  await page.getByRole("button", { name: /security-policy.pdf/ }).click();

  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByText("security-policy.pdf", { exact: true })).toBeVisible();
  await page.screenshot({ path: "workspace-mobile-preview.png", fullPage: true });
});


test("cloud degradation is displayed as document excerpts, including saved history", async ({ page }) => {
  await mockApi(page);
  const answer = { answer: "문서 원문 발췌: 비밀번호는 90일마다 변경합니다.", citations: ["security-policy.pdf"], requires_human_review: true, response_mode: "search_only", response_reason: "provider_unavailable", conversation_id: "conversation-new" };
  await page.route("**/api/v1/questions", (route) => json(route, answer));
  await page.route("**/api/v1/conversations/conversation-saved", (route) => json(route, {
    conversation_id: "conversation-saved", title: "저장된 보안 정책 질문", updated_at: "2026-10-19T10:00:00Z",
    messages: [
      { message_id: "u", role: "USER", content: "저장된 질문", citations: [], requires_human_review: false, created_at: "2026-10-19T10:00:00Z" },
      { ...answer, message_id: "a", role: "ASSISTANT", content: answer.answer, created_at: "2026-10-19T10:00:01Z" },
    ],
  }));
  await page.goto("/login");
  await page.getByLabel("이메일").fill("admin@example.com");
  await page.getByLabel("비밀번호", { exact: true }).fill("safe-password-1234");
  await page.getByRole("button", { name: /^로그인/ }).click();
  await page.getByRole("textbox", { name: "질문", exact: true }).fill("비밀번호 변경 주기는?");
  await page.getByRole("button", { name: "질문 전송", exact: true }).click();
  await expect(page.getByText("문서 검색 결과", { exact: true })).toBeVisible();
  await expect(page.getByText("검토가 필요한 답변입니다.", { exact: true })).toHaveCount(0);
  await expect(page.getByText("문서 원문 발췌: 비밀번호는 90일마다 변경합니다.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /저장된 보안 정책 질문/ }).click();
  await expect(page.getByText("문서 검색 결과", { exact: true })).toBeVisible();
});
