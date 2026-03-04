"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import ConsoleNav from "@/components/ConsoleNav";
import {
  CardGrid,
  EmptyState,
  ErrorBanner,
  PageIntro,
  PageShell,
  PrimaryButton,
  SectionCard,
  SectionTitle,
  SecondaryButton,
  StatCard,
  CodeEditorInput,
} from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import {
  caoRequest,
  ConsoleAssetEntry,
  ConsoleAssetFileResponse,
  ConsoleAssetTeam,
  ConsoleAssetTeamsResponse,
  ConsoleAssetTreeResponse,
} from "@/lib/cao";

const TEXT_PREVIEW_EXTENSIONS = new Set([
  "md",
  "markdown",
  "txt",
  "json",
  "yaml",
  "yml",
  "xml",
  "csv",
  "log",
  "ts",
  "tsx",
  "js",
  "jsx",
  "py",
  "sh",
  "sql",
  "html",
  "css",
  "scss",
  "toml",
  "ini",
  "conf",
]);

function formatBytes(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function AssetsPage() {
  const [teams, setTeams] = useState<ConsoleAssetTeam[]>([]);
  const [error, setError] = useState("");
  const [selectedTeam, setSelectedTeam] = useState<ConsoleAssetTeam | null>(null);
  const [currentPath, setCurrentPath] = useState("");
  const [treeEntries, setTreeEntries] = useState<ConsoleAssetTreeResponse["entries"]>([]);
  const [selectedEntryPath, setSelectedEntryPath] = useState("");
  const [selectedEntry, setSelectedEntry] = useState<ConsoleAssetEntry | null>(null);
  const [selectedNodeByPath, setSelectedNodeByPath] = useState<Record<string, string>>({});
  const [treeByPath, setTreeByPath] = useState<Record<string, ConsoleAssetEntry[]>>({});
  const [expandedDirsByPath, setExpandedDirsByPath] = useState<Record<string, Set<string>>>({});
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [selectedFileContent, setSelectedFileContent] = useState("");
  const [showPreviewDrawer, setShowPreviewDrawer] = useState(false);
  const [previewMode, setPreviewMode] = useState<"rendered" | "source">("source");
  const [copyLabel, setCopyLabel] = useState("复制");
  const [loadingTree, setLoadingTree] = useState(false);
  const [loadingFile, setLoadingFile] = useState(false);
  const [deletingPath, setDeletingPath] = useState("");

  const loadTeams = useCallback(async () => {
    const result = await caoRequest<ConsoleAssetTeamsResponse>("GET", "/console/assets/teams");
    if (!result.ok) {
      setError("获取团队资产列表失败");
      return;
    }

    setTeams(result.data.teams || []);
    setError("");
  }, []);

  const loadTree = useCallback(async (team: ConsoleAssetTeam, path: string) => {
    setLoadingTree(true);
    const result = await caoRequest<ConsoleAssetTreeResponse>(
      "GET",
      `/console/assets/teams/${encodeURIComponent(team.leader_id)}/tree`,
      { query: { path } }
    );

    if (!result.ok) {
      setError("读取团队目录失败");
      setLoadingTree(false);
      return;
    }

    setTreeEntries(result.data.entries || []);
    setCurrentPath(result.data.path || "");
    setTreeByPath((previous) => ({
      ...previous,
      [result.data.path || ""]: result.data.entries || [],
    }));
    setLoadingTree(false);
    setError("");
  }, []);

  const loadFile = useCallback(async (team: ConsoleAssetTeam, path: string) => {
    setLoadingFile(true);
    const result = await caoRequest<ConsoleAssetFileResponse>(
      "GET",
      `/console/assets/teams/${encodeURIComponent(team.leader_id)}/file`,
      { query: { path } }
    );

    if (!result.ok) {
      setError("读取文件失败");
      setLoadingFile(false);
      return;
    }

    const resolvedPath = result.data.path || path;
    const ext = resolvedPath.split(".").pop()?.toLowerCase();
    const defaultMode =
      ext === "md" || ext === "markdown" || ext === "html" || ext === "htm" ? "rendered" : "source";
    setSelectedFilePath(resolvedPath);
    setSelectedFileContent(result.data.content || "");
    setCopyLabel("复制");
    setPreviewMode(defaultMode);
    setShowPreviewDrawer(true);
    setLoadingFile(false);
    setError("");
  }, []);

  const deleteEntry = useCallback(
    async (team: ConsoleAssetTeam, entry: ConsoleAssetEntry) => {
      const label = entry.is_dir ? "文件夹" : "文件";
      if (!window.confirm(`确定要删除${label} "${entry.name}" 吗？此操作不可撤销。`)) {
        return;
      }
      setDeletingPath(entry.path);
      const result = await caoRequest<{ ok: boolean }>(
        "DELETE",
        `/console/assets/teams/${encodeURIComponent(team.leader_id)}/entry`,
        { query: { path: entry.path } }
      );
      setDeletingPath("");
      if (!result.ok) {
        setError(`删除失败：${entry.path}`);
        return;
      }
      setError("");
      // Refresh the current directory tree view
      void loadTree(team, currentPath);
      // Also invalidate cached subtree if it was a directory
      if (entry.is_dir) {
        setTreeByPath((previous) => {
          const next = { ...previous };
          for (const key of Object.keys(next)) {
            if (key === entry.path || key.startsWith(entry.path + "/")) {
              delete next[key];
            }
          }
          return next;
        });
        setExpandedDirsByPath((previous) => {
          const teamKey = team.leader_id;
          const nextExpanded = new Set(previous[teamKey] || []);
          for (const p of [...nextExpanded]) {
            if (p === entry.path || p.startsWith(entry.path + "/")) {
              nextExpanded.delete(p);
            }
          }
          return { ...previous, [teamKey]: nextExpanded };
        });
      }
      if (selectedEntryPath === entry.path) {
        setSelectedEntryPath("");
        setSelectedEntry(null);
      }
    },
    [currentPath, loadTree, selectedEntryPath]
  );

  useEffect(() => {
    void loadTeams();
  }, [loadTeams]);

  const pathSegments = useMemo(() => {
    if (!currentPath) {
      return [] as string[];
    }
    return currentPath.split("/").filter(Boolean);
  }, [currentPath]);

  function selectTeam(team: ConsoleAssetTeam) {
    setSelectedTeam(team);
    setSelectedFilePath("");
    setSelectedFileContent("");
    setSelectedEntryPath("");
    setSelectedEntry(null);
    setShowPreviewDrawer(false);
    setTreeByPath({ "": [] });
    setExpandedDirsByPath({});
    setSelectedNodeByPath((previous) => ({ ...previous, [team.leader_id]: "" }));
    void loadTree(team, "");
  }

  function openDirectory(path: string) {
    if (!selectedTeam) {
      return;
    }
    setSelectedFilePath("");
    setSelectedFileContent("");
    setShowPreviewDrawer(false);
    void loadTree(selectedTeam, path);
  }

  function isTextPreviewable(path: string): boolean {
    const fileName = path.split("/").pop() || "";
    const extension = fileName.includes(".") ? fileName.split(".").pop()?.toLowerCase() : "";
    if (!extension) {
      return false;
    }
    return TEXT_PREVIEW_EXTENSIONS.has(extension);
  }

  async function handleCopySource() {
    try {
      await navigator.clipboard.writeText(selectedFileContent || "");
      setCopyLabel("已复制");
      setTimeout(() => setCopyLabel("复制"), 1200);
    } catch {
      setCopyLabel("复制失败");
      setTimeout(() => setCopyLabel("复制"), 1200);
    }
  }

  function isMarkdownFile(filePath: string): boolean {
    const ext = filePath.split(".").pop()?.toLowerCase();
    return ext === "md" || ext === "markdown";
  }

  function isHtmlFile(filePath: string): boolean {
    const ext = filePath.split(".").pop()?.toLowerCase();
    return ext === "html" || ext === "htm";
  }

  function toDownloadUrl(team: ConsoleAssetTeam, path: string): string {
    const base =
      process.env.NEXT_PUBLIC_CAO_CONTROL_PANEL_URL?.trim() ||
      (typeof window !== "undefined" && window.location.port === "3000"
        ? "http://localhost:8000"
        : typeof window !== "undefined"
          ? window.location.origin
          : "");
    const normalizedBase = base.replace(/\/$/, "");
    const searchParams = new URLSearchParams({ path });
    return `${normalizedBase}/console/assets/teams/${encodeURIComponent(team.leader_id)}/download?${searchParams.toString()}`;
  }

  function toggleTreeDir(path: string) {
    if (!selectedTeam) {
      return;
    }

    const currentTree = treeByPath[currentPath] || [];
    const target = currentTree.find((item) => item.path === path);
    if (!target || !target.is_dir) {
      return;
    }

    const teamKey = selectedTeam.leader_id;
    const nextExpanded = new Set(expandedDirsByPath[teamKey] || []);
    if (nextExpanded.has(path)) {
      nextExpanded.delete(path);
    } else {
      nextExpanded.add(path);
      if (!treeByPath[path]) {
        void loadTree(selectedTeam, path);
      }
    }

    setExpandedDirsByPath((previous) => ({ ...previous, [teamKey]: nextExpanded }));
  }

  function onClickEntry(entry: ConsoleAssetEntry) {
    setSelectedEntryPath(entry.path);
    setSelectedEntry(entry);
    if (selectedTeam) {
      setSelectedNodeByPath((previous) => ({
        ...previous,
        [selectedTeam.leader_id]: entry.path,
      }));
    }
  }

  function onDoubleClickEntry(entry: ConsoleAssetEntry) {
    if (!selectedTeam) {
      return;
    }

    if (entry.is_dir) {
      openDirectory(entry.path);
      return;
    }

    if (isTextPreviewable(entry.path)) {
      void loadFile(selectedTeam, entry.path);
      return;
    }

    window.open(toDownloadUrl(selectedTeam, entry.path), "_blank", "noopener,noreferrer");
  }

  function renderTreeNodes(parentPath: string, depth: number) {
    if (!selectedTeam) {
      return [];
    }
    const entries = treeByPath[parentPath] || [];
    const teamKey = selectedTeam.leader_id;
    const expanded = expandedDirsByPath[teamKey] || new Set<string>();

    return entries.map((entry) => {
      const isSelected = selectedEntryPath === entry.path;
      const isExpanded = expanded.has(entry.path);
      const canExpand = entry.is_dir;
      return (
        <div key={entry.path}>
          <div
            onClick={() => {
              onClickEntry(entry);
              if (entry.is_dir) {
                toggleTreeDir(entry.path);
              }
            }}
            onDoubleClick={() => onDoubleClickEntry(entry)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 6px",
              paddingLeft: 8 + depth * 14,
              borderRadius: 6,
              cursor: "pointer",
              background: isSelected ? "var(--surface)" : "transparent",
              color: isSelected ? "var(--text-bright)" : "var(--text)",
              fontSize: 12,
              userSelect: "none",
            }}
            title={entry.path}
          >
            <span style={{ width: 10, textAlign: "center", color: "var(--text-dim)" }}>
              {canExpand ? (isExpanded ? "▾" : "▸") : ""}
            </span>
            <span>{entry.is_dir ? "📁" : "📄"}</span>
            <span
              style={{
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {entry.name}
            </span>
          </div>
          {canExpand && isExpanded ? renderTreeNodes(entry.path, depth + 1) : null}
        </div>
      );
    });
  }

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="资产管理"
          description="按团队浏览工作目录资产，支持树形目录下钻与文本文件在线预览。"
        />

        {error && <ErrorBanner text={error} />}

        <SectionCard style={{ padding: 10 }}>
          <CardGrid minWidth={180} gap={10}>
            <StatCard label="可浏览团队" value={teams.length} />
            <StatCard label="当前目录" value={selectedTeam ? currentPath || "/" : "-"} />
          </CardGrid>
        </SectionCard>

        <SectionCard>
          <SectionTitle title="团队资产入口" />
          {teams.length === 0 ? (
            <EmptyState text="暂无已配置工作目录的团队" />
          ) : (
            <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
              {teams.map((team) => {
                const active = selectedTeam?.leader_id === team.leader_id;
                return (
                  <div
                    key={team.leader_id}
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: 10,
                      padding: 10,
                      background: active ? "var(--surface2)" : "var(--surface)",
                    }}
                  >
                    <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 6 }}>
                      {team.team_name}
                    </div>
                    <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 8 }}>
                      {team.working_directory}
                    </div>
                    <SecondaryButton
                      type="button"
                      onClick={() => selectTeam(team)}
                      style={{ padding: "6px 10px", fontSize: 12 }}
                    >
                      {active ? "已选择" : "打开目录"}
                    </SecondaryButton>
                  </div>
                );
              })}
            </div>
          )}
        </SectionCard>

        {selectedTeam ? (
          <SectionCard>
            <SectionTitle title={`资源管理器 · ${selectedTeam.team_name}`} />

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "320px 1fr",
                gap: 12,
                minHeight: 520,
              }}
            >
              <div
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  background: "var(--surface2)",
                  overflow: "auto",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "8px 10px",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div style={{ color: "var(--text-bright)", fontWeight: 700, fontSize: 12 }}>目录树</div>
                  <SecondaryButton
                    type="button"
                    onClick={() => openDirectory("")}
                    style={{ padding: "2px 8px", fontSize: 11 }}
                  >
                    回到根目录
                  </SecondaryButton>
                </div>
                <div style={{ padding: 8 }}>
                  {loadingTree && Object.keys(treeByPath).length === 0 ? (
                    <div style={{ color: "var(--text-dim)", fontSize: 12 }}>目录加载中...</div>
                  ) : (
                    renderTreeNodes("", 0)
                  )}
                </div>
              </div>

              <div
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  background: "var(--surface)",
                  overflow: "hidden",
                  display: "grid",
                  gridTemplateRows: "auto 1fr",
                }}
              >
                <div
                  style={{
                    padding: "8px 10px",
                    borderBottom: "1px solid var(--border)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                    当前目录：{currentPath || "/"}
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {pathSegments.map((segment, index) => {
                      const path = pathSegments.slice(0, index + 1).join("/");
                      return (
                        <SecondaryButton
                          key={path}
                          type="button"
                          onClick={() => openDirectory(path)}
                          style={{ padding: "2px 8px", fontSize: 11 }}
                        >
                          {segment}
                        </SecondaryButton>
                      );
                    })}
                  </div>
                </div>

                <div style={{ overflow: "auto", padding: 10 }}>
                  {loadingTree ? (
                    <div style={{ color: "var(--text-dim)", fontSize: 13 }}>目录加载中...</div>
                  ) : treeEntries.length === 0 ? (
                    <EmptyState text="当前目录为空" />
                  ) : (
                    <div style={{ display: "grid", gap: 8 }}>
                      {treeEntries.map((entry) => {
                        const isActive = selectedEntryPath === entry.path;
                        const rememberedNode = selectedTeam
                          ? selectedNodeByPath[selectedTeam.leader_id]
                          : "";
                        const shouldHighlightFromRemembered = rememberedNode === entry.path;
                        const effectiveActive = isActive || shouldHighlightFromRemembered;
                        const previewable = !entry.is_dir && isTextPreviewable(entry.path);
                        return (
                          <div
                            key={entry.path}
                            onClick={() => onClickEntry(entry)}
                            onDoubleClick={() => onDoubleClickEntry(entry)}
                            style={{
                              border: "1px solid var(--border)",
                              borderRadius: 8,
                              padding: 8,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              gap: 8,
                              background: effectiveActive ? "var(--surface2)" : "var(--surface)",
                              cursor: "pointer",
                            }}
                          >
                            <div style={{ minWidth: 0 }}>
                              <div
                                style={{
                                  color: "var(--text-bright)",
                                  fontWeight: 700,
                                  whiteSpace: "nowrap",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                }}
                              >
                                {entry.is_dir ? "📁" : "📄"} {entry.name}
                              </div>
                              <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                                {entry.path} · {entry.is_dir ? "目录" : formatBytes(entry.size)}
                              </div>
                            </div>

                            <div style={{ display: "flex", gap: 8 }}>
                              {entry.is_dir ? (
                                <SecondaryButton
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    openDirectory(entry.path);
                                  }}
                                  style={{ padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" }}
                                >
                                  进入
                                </SecondaryButton>
                              ) : previewable ? (
                                <SecondaryButton
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    if (!selectedTeam) {
                                      return;
                                    }
                                    void loadFile(selectedTeam, entry.path);
                                  }}
                                  style={{ padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" }}
                                >
                                  预览
                                </SecondaryButton>
                              ) : (
                                <SecondaryButton
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    if (!selectedTeam) {
                                      return;
                                    }
                                    window.open(
                                      toDownloadUrl(selectedTeam, entry.path),
                                      "_blank",
                                      "noopener,noreferrer"
                                    );
                                  }}
                                  style={{ padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" }}
                                >
                                  下载
                                </SecondaryButton>
                              )}
                              <SecondaryButton
                                type="button"
                                disabled={deletingPath === entry.path}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  if (!selectedTeam) {
                                    return;
                                  }
                                  void deleteEntry(selectedTeam, entry);
                                }}
                                style={{
                                  padding: "4px 8px",
                                  fontSize: 12,
                                  whiteSpace: "nowrap",
                                  color: "var(--danger, #e05c5c)",
                                }}
                              >
                                {deletingPath === entry.path ? "删除中..." : "删除"}
                              </SecondaryButton>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </SectionCard>
        ) : (
          <EmptyState text="请选择一个团队以浏览其工作目录" />
        )}

        {showPreviewDrawer && selectedFilePath && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.45)",
              display: "flex",
              justifyContent: "flex-end",
              zIndex: 40,
            }}
            onClick={() => setShowPreviewDrawer(false)}
          >
            <div
              onClick={(event) => event.stopPropagation()}
              style={{
                width: "75vw",
                minWidth: "min(700px, 100vw)",
                maxWidth: "100vw",
                height: "100%",
                background: "var(--surface)",
                borderLeft: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  padding: 14,
                  borderBottom: "1px solid var(--border)",
                  background: "var(--surface2)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      color: "var(--text-bright)",
                      fontWeight: 700,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    文本预览
                  </div>
                  <div
                    style={{
                      color: "var(--text-dim)",
                      fontSize: 12,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {selectedFilePath}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  {(isMarkdownFile(selectedFilePath) || isHtmlFile(selectedFilePath)) && (
                    <SecondaryButton
                      type="button"
                      onClick={() =>
                        setPreviewMode((previous) => (previous === "rendered" ? "source" : "rendered"))
                      }
                      style={{ padding: "6px 10px" }}
                    >
                      {previewMode === "rendered" ? "查看源码" : "渲染预览"}
                    </SecondaryButton>
                  )}
                  <SecondaryButton
                    type="button"
                    onClick={handleCopySource}
                    disabled={loadingFile}
                    style={{ padding: "6px 10px" }}
                  >
                    {copyLabel}
                  </SecondaryButton>
                  {selectedTeam ? (
                    <PrimaryButton
                      type="button"
                      onClick={() => window.open(toDownloadUrl(selectedTeam, selectedFilePath), "_blank", "noopener,noreferrer")}
                      style={{ padding: "6px 10px" }}
                    >
                      下载
                    </PrimaryButton>
                  ) : null}
                  <SecondaryButton
                    type="button"
                    onClick={() => setShowPreviewDrawer(false)}
                    style={{ padding: "6px 10px" }}
                  >
                    关闭
                  </SecondaryButton>
                </div>
              </div>

              <div style={{ flex: 1, padding: 12, minHeight: 0, overflow: "hidden" }}>
                {loadingFile ? (
                  <div style={{ color: "var(--text-dim)", fontSize: 13 }}>文件加载中...</div>
                ) : previewMode === "rendered" && isMarkdownFile(selectedFilePath) ? (
                  <div
                    style={{
                      height: "100%",
                      overflowY: "auto",
                      color: "var(--text)",
                      fontSize: 14,
                      lineHeight: 1.7,
                    }}
                    className="markdown-body"
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedFileContent}</ReactMarkdown>
                  </div>
                ) : previewMode === "rendered" && isHtmlFile(selectedFilePath) ? (
                  <iframe
                    srcDoc={selectedFileContent}
                    sandbox="allow-scripts"
                    style={{
                      width: "100%",
                      height: "100%",
                      border: "none",
                      borderRadius: 6,
                      background: "#fff",
                    }}
                    title={selectedFilePath}
                  />
                ) : (
                  <CodeEditorInput
                    value={selectedFileContent}
                    onChange={() => {}}
                    language="auto"
                    fileName={selectedFilePath}
                    showToolbar
                    defaultReadOnly
                    showReadOnlyToggle={false}
                    fullHeight
                    style={{ width: "100%", height: "100%", minHeight: 0 }}
                  />
                )}
              </div>
            </div>
          </div>
        )}
      </PageShell>
    </RequireAuth>
  );
}
