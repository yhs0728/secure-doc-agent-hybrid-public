import { expect, test } from "@playwright/test";

test("login form explains validation requirements", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "다시 오신 것을 환영합니다" })).toBeVisible();
  await page.getByRole("button", { name: /로그인/ }).click();
  await expect(page.getByText("올바른 이메일 주소를 입력하세요.")).toBeVisible();
  await expect(page.getByText("비밀번호는 12자 이상이어야 합니다.")).toBeVisible();
});
