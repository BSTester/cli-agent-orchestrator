import { cp, mkdir, rm, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

async function main() {
  const scriptFile = fileURLToPath(import.meta.url);
  const scriptsDir = path.dirname(scriptFile);
  const frontendDir = path.resolve(scriptsDir, "..");
  const repoRoot = path.resolve(frontendDir, "..");

  const sourceDir = path.resolve(frontendDir, "out");
  const targetDir = path.resolve(
    repoRoot,
    "src",
    "cli_agent_orchestrator",
    "control_panel",
    "static"
  );

  try {
    const sourceStat = await stat(sourceDir);
    if (!sourceStat.isDirectory()) {
      throw new Error(`Source build output is not a directory: ${sourceDir}`);
    }
  } catch (error) {
    throw new Error(
      `Frontend build output not found at ${sourceDir}. Please run \`npm run build\` first.`,
      { cause: error }
    );
  }

  await rm(targetDir, { recursive: true, force: true });
  await mkdir(targetDir, { recursive: true });
  await cp(sourceDir, targetDir, { recursive: true });

  console.log(`[deploy] synced frontend static assets to: ${targetDir}`);
}

main().catch((error) => {
  console.error("[deploy] failed to sync frontend static assets");
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
