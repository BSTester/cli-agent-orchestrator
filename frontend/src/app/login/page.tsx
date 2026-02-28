"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ErrorBanner, InfoHint, PageShell, PrimaryButton, SectionCard, TextInput } from "@/components/ConsoleTheme";
import { caoRequest } from "@/lib/cao";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/dashboard";

  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let canceled = false;

    async function checkExistingLogin() {
      const result = await caoRequest<{ authenticated: boolean }>("GET", "/auth/me");
      if (!canceled && result.ok && result.data.authenticated) {
        router.replace(nextPath);
      }
    }

    checkExistingLogin();
    return () => {
      canceled = true;
    };
  }, [nextPath, router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");

    const result = await caoRequest<{ ok: boolean }>("POST", "/auth/login", {
      body: { password },
    });

    if (!result.ok) {
      setError("登录失败：密码错误或服务不可用");
      setSubmitting(false);
      return;
    }

    router.replace(nextPath);
  }

  return (
    <PageShell>
      <div
        style={{
          minHeight: "calc(100vh - 36px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
      <SectionCard style={{ width: 360, padding: 22 }}>
        <h1 style={{ marginBottom: 10, color: "var(--text-bright)", fontSize: 20, textAlign: "center" }}>一人集团公司</h1>
        <div style={{ marginBottom: 16, textAlign: "center" }}>
          <InfoHint text="输入控制台密码后进入管理页面" />
        </div>

        <form onSubmit={onSubmit}>
          <TextInput
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="控制台密码"
            required
            style={{ width: "100%", padding: "9px 12px", marginBottom: 10 }}
          />
          {error && <ErrorBanner text={error} />}
          <PrimaryButton
            type="submit"
            disabled={submitting}
            style={{
              width: "100%",
              padding: "9px 12px",
              opacity: submitting ? 0.75 : 1,
            }}
          >
            {submitting ? "登录中..." : "登录"}
          </PrimaryButton>
        </form>
      </SectionCard>
      </div>
    </PageShell>
  );
}
