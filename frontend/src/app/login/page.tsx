"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorBanner, InfoHint, PageShell, PrimaryButton, SectionCard, TextInput } from "@/components/ConsoleTheme";
import { caoRequest, type ProviderGuideOnboardingStatus } from "@/lib/cao";

const DEFAULT_LOGIN_PATH = "/dashboard";
const ONBOARDING_PATH = "/settings";

export default function LoginPage() {
  const router = useRouter();

  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loginContext] = useState(() => {
    if (typeof window === "undefined") {
      return {
        nextPath: DEFAULT_LOGIN_PATH,
        hasExplicitNextPath: false,
      };
    }

    const nextFromQuery = new URLSearchParams(window.location.search).get("next");
    return {
      nextPath: nextFromQuery || DEFAULT_LOGIN_PATH,
      hasExplicitNextPath: Boolean(nextFromQuery),
    };
  });
  const { nextPath, hasExplicitNextPath } = loginContext;

  const resolveNextPath = useCallback(async (preferredPath: string, preferredPathIsExplicit: boolean) => {
    if (preferredPathIsExplicit) {
      return preferredPath;
    }

    const result = await caoRequest<ProviderGuideOnboardingStatus>(
      "GET",
      "/console/provider-config/onboarding-status"
    );
    if (result.ok && result.data.should_show_guide) {
      return ONBOARDING_PATH;
    }

    return DEFAULT_LOGIN_PATH;
  }, []);

  useEffect(() => {
    let canceled = false;

    async function checkExistingLogin() {
      const result = await caoRequest<{ authenticated: boolean }>("GET", "/auth/me");
      if (!canceled && result.ok && result.data.authenticated) {
        const targetPath = await resolveNextPath(nextPath, hasExplicitNextPath);
        if (!canceled) {
          router.replace(targetPath);
        }
      }
    }

    void checkExistingLogin();
    return () => {
      canceled = true;
    };
  }, [hasExplicitNextPath, nextPath, resolveNextPath, router]);

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

    const targetPath = await resolveNextPath(nextPath, hasExplicitNextPath);
    router.replace(targetPath);
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
        <h1 style={{ marginBottom: 10, color: "var(--text-bright)", fontSize: 20, textAlign: "center" }}>一人无限智能</h1>
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
