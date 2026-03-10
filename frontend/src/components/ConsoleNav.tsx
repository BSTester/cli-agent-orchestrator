"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { SecondaryButton } from "@/components/ConsoleTheme";
import { caoRequest } from "@/lib/cao";

const navItems = [
  { href: "/dashboard", label: "集团总览" },
  { href: "/organization", label: "组织管理" },
  { href: "/agents", label: "会话管理" },
  { href: "/assets", label: "资产管理" },
  { href: "/tasks", label: "任务管理" },
];

export default function ConsoleNav() {
  const pathname = usePathname();
  const router = useRouter();

  const normalizedPathname = pathname.endsWith("/") && pathname !== "/"
    ? pathname.slice(0, -1)
    : pathname;

  async function handleLogout() {
    await caoRequest("POST", "/auth/logout");
    router.replace("/login");
  }

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "12px 18px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
        backdropFilter: "blur(10px)",
      }}
    >
      <div style={{ fontWeight: 700, color: "var(--text-bright)" }}>一人集团公司</div>
      <nav style={{ display: "flex", gap: 16 }}>
        {navItems.map((item) => {
          const active = normalizedPathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                textDecoration: "none",
                color: active ? "var(--text-bright)" : "var(--text-dim)",
                fontWeight: active ? 700 : 500,
                border: "1px solid var(--border)",
                borderRadius: 999,
                padding: "4px 10px",
                background: active ? "var(--surface2)" : "transparent",
              }}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <SecondaryButton onClick={handleLogout} style={{ padding: "6px 10px" }}>
        退出登录
      </SecondaryButton>
    </header>
  );
}
