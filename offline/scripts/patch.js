#!/usr/bin/env node
/**
 * Claude Code Whitelabel Patch
 * Three-step: Protect → Replace → Restore
 *
 * Usage: node patch.js <cli.js> <BRAND_NAME> <API_BASE_URL> <BRAND_RGB> <LOGO_STYLE> <ENABLE_I18N> <DISABLE_TELEMETRY>
 */

const fs = require("fs");
const path = require("path");

const [
  ,, cliPath, brandName, apiBaseUrl, brandRgb,
  logoStyle = "default", enableI18n = "false", disableTelemetry = "true",
] = process.argv;

if (!cliPath || !brandName) {
  console.error("Usage: node patch.js <cli.js> <BRAND_NAME> [API_BASE_URL] [BRAND_RGB] [LOGO_STYLE] [ENABLE_I18N] [DISABLE_TELEMETRY]");
  process.exit(1);
}

const absPath = path.resolve(cliPath);
if (!fs.existsSync(absPath)) {
  console.error(`File not found: ${absPath}`);
  process.exit(1);
}

// ─── Logo presets ────────────────────────────────────────────
const LOGOS = {
  "default": [
    "    ╭━━━━━━━━━━━━━━╮",
    "    ┃   ◉  ◉       ┃",
    "    ┃     ╰━╯      ┃",
    "    ┃   ╭─────╮    ┃",
    "    ╰━━━┷━━━━━┷━━━━╯",
  ],
  "look-left": [
    "    ╭━━━━━━━━━━━━━━╮",
    "    ┃  ◉  ◉        ┃",
    "    ┃    ╰━╯       ┃",
    "    ┃  ╭─────╮     ┃",
    "    ╰━━┷━━━━━┷━━━━━╯",
  ],
  "look-right": [
    "    ╭━━━━━━━━━━━━━━╮",
    "    ┃       ◉  ◉   ┃",
    "    ┃      ╰━╯     ┃",
    "    ┃    ╭─────╮   ┃",
    "    ╰━━━━┷━━━━━┷━━━╯",
  ],
  "arms-up": [
    "  ╲╱",
    "    ╭━━━━━━━━━━━━━━╮",
    "    ┃   ◉  ◉       ┃",
    "    ┃     ╰━╯      ┃",
    "    ╰━━━━━━━━━━━━━━╯",
  ],
};

// ─── i18n map ────────────────────────────────────────────────
const I18N = {
  "What can I help you with?": "有什么我可以帮你的？",
  "Thinking...": "思考中...",
  "Yes, allow once": "是，允许一次",
  "Yes, allow always": "是，始终允许",
  "No, deny once": "否，拒绝一次",
  "No, deny always": "否，始终拒绝",
  "Allow": "允许",
  "Deny": "拒绝",
  "Retry": "重试",
  "Cancel": "取消",
  "Continue": "继续",
  "Approve": "批准",
  "Reject": "拒绝",
  "copied to clipboard": "已复制到剪贴板",
  "Compacting conversation...": "正在压缩对话...",
  "What would you like to do?": "你想做什么？",
  "Enter a prompt": "输入提示",
  "Select a model": "选择模型",
  "No changes": "无变更",
  "has been updated": "已更新",
  "has been created": "已创建",
  "has been deleted": "已删除",
  "Permission denied": "权限被拒绝",
  "File not found": "文件未找到",
  "Interrupted": "已中断",
  "Tool execution": "工具执行",
  "Reading file": "正在读取文件",
  "Writing file": "正在写入文件",
  "Searching": "正在搜索",
  "Running command": "正在执行命令",
};

// ─── Protected strings (must NOT be branded) ─────────────────
const PROTECTED = [
  // User-Agent / SDK identifiers
  { marker: "__PROT_UA__", pattern: /claude-code\/[\d.]+/g },
  { marker: "__PROT_PKG__", pattern: /"name":\s*"@anthropic-ai\/claude-code"/g },
  { marker: "__PROT_SDK__", pattern: /@anthropic-ai\/sdk/g },
  // Environment variable names
  { marker: "__PROT_ENV1__", pattern: /CLAUDE_CONFIG_DIR/g },
  { marker: "__PROT_ENV2__", pattern: /CLAUDE_CODE_DISABLE/g },
  { marker: "__PROT_ENV3__", pattern: /CLAUDE_CODE_USE_/g },
  { marker: "__PROT_ENV4__", pattern: /CLAUDE_CODE_MAX_/g },
  { marker: "__PROT_ENV5__", pattern: /CLAUDE_CODE_OVERRIDE/g },
  { marker: "__PROT_ENV6__", pattern: /CLAUDE_CODE_REMOTE/g },
  { marker: "__PROT_ENV7__", pattern: /CLAUDE_CODE_UNATTENDED/g },
  { marker: "__PROT_ENV8__", pattern: /ANTHROPIC_API_KEY/g },
  { marker: "__PROT_ENV9__", pattern: /ANTHROPIC_BASE_URL/g },
  { marker: "__PROT_ENVA__", pattern: /ANTHROPIC_AUTH_TOKEN/g },
  // OAuth / auth paths
  { marker: "__PROT_OA1__", pattern: /\.claude\//g },
  { marker: "__PROT_OA2__", pattern: /claude\.ai/g },
];

// ─── Default Claude purple RGB ───────────────────────────────
const CLAUDE_PURPLE_PATTERNS = [
  /rgb\(\s*101\s*,\s*77\s*,\s*196\s*\)/g,    // Primary purple
  /rgb\(\s*124\s*,\s*95\s*,\s*223\s*\)/g,     // Lighter variant
  /rgb\(\s*79\s*,\s*57\s*,\s*168\s*\)/g,      // Darker variant
  /"#654CC4"/g,
  /"#7C5FDF"/g,
  /"#4F39A8"/g,
];

// ─── Telemetry endpoints ─────────────────────────────────────
const TELEMETRY_PATTERNS = [
  /sentry\.io[^"']*/g,
  /statsig\.anthropic\.com[^"']*/g,
  /otel-collector[^"']*/g,
];

// ────────────────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────────────────

let src = fs.readFileSync(absPath, "utf-8");
const origSize = Buffer.byteLength(src, "utf-8");
console.log(`[patch] Loaded ${absPath} (${(origSize / 1024 / 1024).toFixed(1)} MB)`);

// === Step 1: Protect ===
console.log("[patch] Step 1: Protect critical strings");
const restoreMap = {};
for (const { marker, pattern } of PROTECTED) {
  const matches = src.match(pattern);
  if (matches) {
    restoreMap[marker] = matches;
    let idx = 0;
    src = src.replace(pattern, () => `${marker}_${idx++}_`);
    console.log(`  Protected ${matches.length} occurrences → ${marker}`);
  }
}

// === Step 2: Replace ===
console.log("[patch] Step 2: Apply brand replacements");

// 2a. Brand name
let brandCount = 0;
src = src.replace(/Claude Code/g, () => { brandCount++; return brandName; });
console.log(`  Replaced ${brandCount}x "Claude Code" → "${brandName}"`);

// 2b. Colors
if (brandRgb) {
  const [r, g, b] = brandRgb.split(",").map(s => s.trim());
  for (const pat of CLAUDE_PURPLE_PATTERNS) {
    src = src.replace(pat, `rgb(${r}, ${g}, ${b})`);
  }
  console.log(`  Applied brand color rgb(${r}, ${g}, ${b})`);
}

// 2c. Logo
const logo = LOGOS[logoStyle];
if (logo) {
  // Try to find and replace the default Claude ASCII art in the banner
  const logoText = logo.map(l => `"${l}"`).join(",");
  console.log(`  Logo style: ${logoStyle}`);
}

// 2d. i18n
if (enableI18n === "true") {
  let i18nCount = 0;
  for (const [en, zh] of Object.entries(I18N)) {
    const escaped = en.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`"${escaped}"`, "g");
    const before = src;
    src = src.replace(re, `"${zh}"`);
    if (src !== before) i18nCount++;
  }
  console.log(`  Applied ${i18nCount} i18n translations`);
}

// 2e. Telemetry
if (disableTelemetry === "true") {
  let telCount = 0;
  for (const pat of TELEMETRY_PATTERNS) {
    const before = src;
    src = src.replace(pat, "localhost");
    if (src !== before) telCount++;
  }
  console.log(`  Disabled ${telCount} telemetry endpoints`);
}

// === Step 3: Restore ===
console.log("[patch] Step 3: Restore protected strings");
for (const { marker } of PROTECTED) {
  if (!restoreMap[marker]) continue;
  let idx = 0;
  const re = new RegExp(`${marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}_(\\d+)_`, "g");
  src = src.replace(re, () => {
    const original = restoreMap[marker][idx] || restoreMap[marker][0];
    idx++;
    return original;
  });
}

// 3a. API base URL — NOT patched into cli.js; handled by launcher env vars instead
if (apiBaseUrl) {
  console.log(`  API base URL will be set via ANTHROPIC_BASE_URL env var: ${apiBaseUrl}`);
  console.log(`  (cli.js retains original api.anthropic.com — overridden at runtime)`);
}

// === Write ===
fs.writeFileSync(absPath, src, "utf-8");
const newSize = Buffer.byteLength(src, "utf-8");
const delta = newSize - origSize;
console.log(`[patch] Done. ${(newSize / 1024 / 1024).toFixed(1)} MB (${delta >= 0 ? "+" : ""}${delta} bytes)`);

// === Validate ===
const final = fs.readFileSync(absPath, "utf-8");
const residual = (final.match(/Claude Code/g) || []).length;
if (residual > 0) {
  console.log(`[patch] Warning: ${residual} residual "Claude Code" references remain (may be in protected strings)`);
}
const hasProt = /__PROT_/.test(final);
if (hasProt) {
  console.error("[patch] ERROR: unreplaced __PROT_ markers found!");
  process.exit(1);
}
console.log("[patch] Validation passed.");
