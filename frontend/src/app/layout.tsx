import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "一人集团公司",
  description: "Web console for the CLI Agent Orchestrator API",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
