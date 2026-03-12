"use client";

export type AuthLinkConfidence = "high" | "possible" | "low";

export type DetectedAuthLink = {
  url: string;
  confidence: AuthLinkConfidence;
  reason: string;
  context: string;
  score: number;
};

const ANSI_PATTERN = /\u001b(?:\][^\u0007]*(?:\u0007|\u001b\\)|[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
const CONTROL_PATTERN = /[\u0000-\u0008\u000b-\u001f\u007f]/g;
const URL_PATTERN = /https?:\/\/[^\s<>"'`]+/gi;
const AUTH_URL_PATTERN =
  /(login|sign(?:-|%20|\s)?in|oauth|authorize|authorise|auth|device|verify|verification|activate|consent|sso)/i;
const AUTH_CONTEXT_PATTERN =
  /(login|sign(?:-| )?in|authenticate|authentication|authorize|authori[sz]ation|oauth|device code|verification code|complete.*browser|finish.*browser|browser.*(open|visit|continue)|visit .*url|open .*url|continue .*browser|approve|consent)/i;
const ACTION_CONTEXT_PATTERN = /(open|visit|copy|paste|browser|continue|complete|click|go to)/i;
const NEGATIVE_URL_PATTERN = /(docs?|documentation|readme|tutorial|guide|help|privacy|terms)/i;
const NEGATIVE_CONTEXT_PATTERN = /(documentation|docs?|readme|example|for more information|learn more|help center|privacy policy|terms of service)/i;

function trimTrailingUrlPunctuation(url: string): string {
  let trimmed = url.trim().replace(/[.,;:'"]+$/g, "");

  while (trimmed.endsWith(")")) {
    const opens = (trimmed.match(/\(/g) || []).length;
    const closes = (trimmed.match(/\)/g) || []).length;
    if (closes <= opens) {
      break;
    }
    trimmed = trimmed.slice(0, -1);
  }

  while (trimmed.endsWith("]")) {
    const opens = (trimmed.match(/\[/g) || []).length;
    const closes = (trimmed.match(/\]/g) || []).length;
    if (closes <= opens) {
      break;
    }
    trimmed = trimmed.slice(0, -1);
  }

  while (trimmed.endsWith("}")) {
    const opens = (trimmed.match(/\{/g) || []).length;
    const closes = (trimmed.match(/\}/g) || []).length;
    if (closes <= opens) {
      break;
    }
    trimmed = trimmed.slice(0, -1);
  }

  return trimmed;
}

function normalizeWhitespace(text: string): string {
  return text.replace(/\r\n?/g, "\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n");
}

export function stripTerminalDecorations(text: string): string {
  return normalizeWhitespace(text.replace(ANSI_PATTERN, "").replace(CONTROL_PATTERN, ""));
}

export function mergeTerminalOutput(previous: string, chunk: string, limit = 20000): string {
  const resetPrefix = "\u001bc";
  const isReset = chunk.startsWith(resetPrefix);
  const normalizedChunk = stripTerminalDecorations(isReset ? chunk.slice(resetPrefix.length) : chunk);
  const merged = isReset ? normalizedChunk : `${previous}${normalizedChunk}`;
  return merged.length > limit ? merged.slice(-limit) : merged;
}

function buildReason(score: number, url: string, context: string): string {
  const reasons: string[] = [];
  if (AUTH_URL_PATTERN.test(url)) {
    reasons.push("链接路径包含登录/认证关键词");
  }
  if (AUTH_CONTEXT_PATTERN.test(context)) {
    reasons.push("终端提示附近提到了登录认证或浏览器继续操作");
  }
  if (ACTION_CONTEXT_PATTERN.test(context)) {
    reasons.push("终端提示附近包含打开/访问/继续等动作词");
  }
  if (NEGATIVE_URL_PATTERN.test(url) || NEGATIVE_CONTEXT_PATTERN.test(context)) {
    reasons.push("同时也像说明性链接，建议人工确认");
  }
  if (reasons.length === 0) {
    reasons.push(score > 0 ? "检测到可能与登录相关的 URL" : "检测到 URL，请人工确认");
  }
  return reasons[0];
}

export function detectAuthLinksFromTerminalOutput(text: string): DetectedAuthLink[] {
  const normalized = stripTerminalDecorations(text);
  const results = new Map<string, DetectedAuthLink>();

  for (const match of normalized.matchAll(URL_PATTERN)) {
    const rawUrl = match[0];
    const url = trimTrailingUrlPunctuation(rawUrl);
    if (!url) {
      continue;
    }

    const start = match.index ?? 0;
    const end = start + rawUrl.length;
    const context = normalized.slice(Math.max(0, start - 120), Math.min(normalized.length, end + 120)).trim();
    const lowerUrl = url.toLowerCase();
    const lowerContext = context.toLowerCase();

    let score = 0;
    if (AUTH_URL_PATTERN.test(lowerUrl)) {
      score += 3;
    }
    if (AUTH_CONTEXT_PATTERN.test(lowerContext)) {
      score += 2;
    }
    if (ACTION_CONTEXT_PATTERN.test(lowerContext)) {
      score += 1;
    }
    if (NEGATIVE_URL_PATTERN.test(lowerUrl)) {
      score -= 2;
    }
    if (NEGATIVE_CONTEXT_PATTERN.test(lowerContext)) {
      score -= 1;
    }

    const confidence: AuthLinkConfidence = score >= 4 ? "high" : score >= 1 ? "possible" : "low";
    const candidate: DetectedAuthLink = {
      url,
      confidence,
      reason: buildReason(score, lowerUrl, lowerContext),
      context,
      score,
    };

    const existing = results.get(url);
    if (!existing || candidate.score > existing.score) {
      results.set(url, candidate);
    }
  }

  return Array.from(results.values()).sort((left, right) => {
    if (right.score !== left.score) {
      return right.score - left.score;
    }
    return left.url.localeCompare(right.url);
  });
}
