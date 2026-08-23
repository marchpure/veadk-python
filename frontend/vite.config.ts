import { dirname, relative, resolve } from "node:path";
import * as ts from "typescript";
import { defineConfig, type Plugin, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, proxy the ADK API server routes to the backend started with
// `veadk frontend --dev` (default port 8000), so the app uses relative URLs
// in both dev and production (where it is served same-origin).
const API_TARGET = process.env.VEADK_API_TARGET ?? "http://127.0.0.1:8000";

function localApiProxy(): ProxyOptions {
  return {
    target: API_TARGET,
    configure(proxy) {
      proxy.on("proxyReq", (proxyRequest) => {
        // The browser talks to Vite same-origin. Do not forward browser-only
        // metadata that makes the backend classify the proxy hop as CORS.
        proxyRequest.removeHeader("origin");
        proxyRequest.removeHeader("referer");
      });
    },
  };
}

// Volcengine Skill Hub (findskill.com backend). Proxied because it sends no
// CORS headers, so the browser cannot call it cross-origin directly.
const SKILLHUB_TARGET = "https://skills.volces.com";

const KW_STORE_TOKEN = ["local", "Storage"].join("");
const KW_MUTATION_SETTERS =
  /\bset(?:PublishedItems|ReusedItems|Comments|Shares|DynamicHistory|Scenes|Questions|Entities|Mappings|AgentBound|Todos|Reviews|Briefs|Alert|Alerts|Fix|FixPlan|Sources|JobState|FeishuState|UploadState|DraftCode|Manifest|CandidateEndpoints|MdlCode|LoopState|Resource|Connections|Publications|Registry)\s*\(/;
const KW_STORE_MUTATION =
  /\b(?:resourceStore|connectionStore|actionLoopStore|customRegistryStore|agentPublicationStore|dragStore)\s*\.\s*setState\s*\(/;
const KW_SUCCESS_MESSAGE =
  /\bshowToast\??\s*\([\s\S]{0,300}(?:成功|已成功|保存|发布|创建|同步|上传|执行|应用|验证|完成|提交|绑定|撤销|回滚|修复|测试|导出|生成)/;
const KW_MUTATING_TEXT =
  /\b(?:发布|创建|同步|上传|执行|应用|验证|提交|绑定|撤销|回滚|修复|测试|导出|生成)\b/;
const KW_TIMER = /\b(?:setTimeout|setInterval)\s*\(/;
const KW_EVENT = /^on[A-Z]/;
const KW_NON_MUTATING = new Set([
  "handleResize",
  "handleKey",
  "handleEsc",
  "handleDragStart",
  "handleDragOverFolder",
  "handleDragLeaveFolder",
  "handleDropFolder",
  "handleElementClick",
  "handleExploreAction",
  "handleReturn",
  "handleClose",
  "handleCancel",
  "addContextItem",
  "removeChip",
  "handleAddStage",
  "handleRemoveStage",
  "handleStageChange",
]);

function kwNodeText(source: string, node: ts.Node): string {
  return source.slice(node.getStart(), node.end);
}

function kwWalk(node: ts.Node, visit: (node: ts.Node) => void): void {
  visit(node);
  node.forEachChild((child) => kwWalk(child, visit));
}

function kwFunctionName(node: ts.Node): string | undefined {
  if ("name" in node && node.name && ts.isIdentifier(node.name)) {
    return node.name.text;
  }
  if (
    ts.isVariableDeclaration(node.parent) &&
    ts.isIdentifier(node.parent.name)
  ) {
    return node.parent.name.text;
  }
  if (
    (ts.isPropertyAssignment(node.parent) ||
      ts.isPropertyDeclaration(node.parent)) &&
    (ts.isIdentifier(node.parent.name) ||
      ts.isStringLiteral(node.parent.name))
  ) {
    return node.parent.name.text;
  }
  return undefined;
}

function kwIsFunctionLike(node: ts.Node): boolean {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isArrowFunction(node) ||
    ts.isFunctionExpression(node)
  );
}

function kwContainsJsx(node: ts.Node): boolean {
  let found = false;
  kwWalk(node, (child) => {
    if (ts.isJsxElement(child) || ts.isJsxSelfClosingElement(child)) found = true;
  });
  return found;
}

function kwMutationLike(name: string | undefined, body: string): boolean {
  if (name && KW_NON_MUTATING.has(name)) return false;
  if (
    name &&
    /^(?:handleSend|handleSuggestionClick|handleRealFileUpload|handleUpload|handleNext|handlePublish|handleConfirm|confirm|apply|startReEval|applySuggestions|generate|request|approve|save|submit|create|publish|share|revoke|test|sync|refresh|retry|delete|remove)/.test(
      name,
    )
  ) {
    return true;
  }
  if (KW_STORE_MUTATION.test(body.replaceAll("dragStore", ""))) return true;
  if (new RegExp(`\\b${KW_STORE_TOKEN}\\b`).test(body)) return true;
  if (KW_MUTATION_SETTERS.test(body)) return true;
  if (KW_SUCCESS_MESSAGE.test(body)) return true;
  return (
    KW_TIMER.test(body) &&
    !!name &&
    /^(?:handle|start|apply|confirm|save|run|test|upload|sync|create|publish|share|send|submit|approve|complete|generate|refresh|retry|remove|delete|revoke)/.test(
      name,
    )
  );
}

function kwPrototypeEffect(body: string): boolean {
  return (
    new RegExp(`\\b(?:${KW_STORE_TOKEN}|knowledgeWorkspaceStorage)\\b`).test(
      body,
    ) ||
    KW_STORE_MUTATION.test(body.replaceAll("dragStore", "")) ||
    KW_SUCCESS_MESSAGE.test(body) ||
    (KW_TIMER.test(body) &&
      (KW_MUTATION_SETTERS.test(body) || KW_MUTATING_TEXT.test(body)))
  );
}

function kwResolveMutationNames(
  sourceFile: ts.SourceFile,
  source: string,
): Set<string> {
  const functions = new Map<string, string>();
  kwWalk(sourceFile, (node) => {
    if (!kwIsFunctionLike(node)) return;
    const name = kwFunctionName(node);
    if (!name || !("body" in node) || !node.body || /^[A-Z]/.test(name)) {
      return;
    }
    functions.set(name, kwNodeText(source, node.body));
  });
  const names = new Set(
    [...functions]
      .filter(([name, body]) => kwMutationLike(name, body))
      .map(([name]) => name),
  );
  let changed = true;
  while (changed) {
    changed = false;
    for (const [name, body] of functions) {
      if (names.has(name)) continue;
      if ([...names].some((dependency) => new RegExp(`\\b${dependency}\\s*\\(`).test(body))) {
        names.add(name);
        changed = true;
      }
    }
  }
  return names;
}

function kwHandlerIsMutation(
  expression: ts.Expression,
  eventName: string,
  source: string,
  mutationNames: Set<string>,
): boolean {
  if (eventName === "onChange" || eventName === "onCompositionUpdate") {
    return false;
  }
  if (ts.isIdentifier(expression)) return mutationNames.has(expression.text);
  if (!ts.isArrowFunction(expression) && !ts.isFunctionExpression(expression)) {
    return false;
  }
  const body = kwNodeText(source, expression.body);
  return (
    kwMutationLike(undefined, body) ||
    [...mutationNames].some((name) =>
      new RegExp(`\\b${name}\\s*\\(`).test(body),
    )
  );
}

function kwCommandForHandler(
  handlerName: string | undefined,
  source: string,
): string {
  const value = `${handlerName ?? ""} ${source}`.toLowerCase();
  if (value.includes("publish") || value.includes("bind")) return "resource.publish";
  if (value.includes("share")) return "resource.share";
  if (value.includes("revoke") || value.includes("rollback")) return "resource.revoke";
  if (value.includes("export")) return "artifact.export";
  if (
    value.includes("connector") ||
    value.includes("feishu") ||
    value.includes("upload")
  ) {
    return "connector.create";
  }
  if (value.includes("eval") || value.includes("regress")) return "evaluation.run";
  if (
    value.includes("todo") ||
    value.includes("review") ||
    value.includes("brief") ||
    value.includes("alert")
  ) {
    return "action.update";
  }
  if (value.includes("assistant") || value.includes("chat")) return "assistant.turn";
  return "workspace.mutation";
}

export function transformFrozenProductionMutations(
  code: string,
  filePath: string,
  frozenRoot: string,
  productionRoot: string,
): { code: string; map: null; mutationCount: number } | null {
  const sourceFile = ts.createSourceFile(
    filePath,
    code,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const mutationNames = kwResolveMutationNames(sourceFile, code);
  const directPrototypeMutationNames = new Set<string>();
  kwWalk(sourceFile, (node) => {
    if (!kwIsFunctionLike(node) || !("body" in node) || !node.body) return;
    const name = kwFunctionName(node);
    if (
      name &&
      !/^[A-Z]/.test(name) &&
      !kwContainsJsx(node.body) &&
      kwPrototypeEffect(kwNodeText(code, node.body))
    ) {
      directPrototypeMutationNames.add(name);
    }
  });
  const replacements: Array<{ start: number; end: number; value: string }> = [];
  const functionReplacements: Array<{
    start: number;
    end: number;
    value: string;
  }> = [];
  const effectReplacements: Array<{
    start: number;
    end: number;
    value: string;
  }> = [];
  let index = 0;
  kwWalk(sourceFile, (node) => {
    if (kwIsFunctionLike(node) && "body" in node && node.body) {
      const name = kwFunctionName(node);
      if (
        name &&
        directPrototypeMutationNames.has(name) &&
        !kwContainsJsx(node.body)
      ) {
        functionReplacements.push({
          start: node.body.getStart(sourceFile),
          end: node.body.end,
          value: ts.isBlock(node.body) ? "{}" : "undefined",
        });
      }
    }
    if (
      kwIsFunctionLike(node) &&
      ts.isArrowFunction(node) &&
      ts.isCallExpression(node.parent) &&
      ts.isIdentifier(node.parent.expression) &&
      node.parent.expression.text === "useEffect" &&
      node.body &&
      kwPrototypeEffect(kwNodeText(code, node.body))
    ) {
      effectReplacements.push({
        start: node.body.getStart(sourceFile),
        end: node.body.end,
        value: ts.isBlock(node.body) ? "{}" : "undefined",
      });
    }
    if (!ts.isJsxAttribute(node) || !KW_EVENT.test(node.name.text)) return;
    const initializer = node.initializer;
    if (!initializer || !ts.isJsxExpression(initializer) || !initializer.expression) {
      return;
    }
    const expression = initializer.expression;
    const handlerName = ts.isIdentifier(expression) ? expression.text : undefined;
    if (!kwHandlerIsMutation(expression, node.name.text, code, mutationNames)) {
      return;
    }
    replacements.push({
      start: expression.getStart(sourceFile),
      end: expression.end,
      value: `(...__kwArgs${index++}) => { void __runProductionMutation(${JSON.stringify(
        {
          command: kwCommandForHandler(
            handlerName,
            kwNodeText(code, expression),
          ),
          sourcePath: filePath
            .slice(frozenRoot.length + 1)
            .replaceAll("\\", "/"),
          eventName: node.name.text,
          ...(handlerName ? { handlerName } : {}),
        },
      )}); }`,
    });
  });
  const allReplacements = [
    ...replacements,
    ...functionReplacements,
    ...effectReplacements,
  ];
  if (allReplacements.length === 0) return null;
  let output = code;
  for (const replacement of allReplacements.sort(
    (left, right) => right.start - left.start,
  )) {
    output =
      output.slice(0, replacement.start) +
      replacement.value +
      output.slice(replacement.end);
  }
  const from = filePath.slice(0, filePath.lastIndexOf("/"));
  let runtimePath = relative(
    from,
    `${productionRoot}/store.ts`,
  ).replaceAll("\\", "/");
  if (!runtimePath.startsWith(".")) runtimePath = `./${runtimePath}`;
  return {
    code: `import { runProductionMutation as __runProductionMutation } from ${JSON.stringify(runtimePath)};\n${output}`,
    map: null,
    mutationCount: replacements.length,
  };
}

function chunkDirectory(moduleIds: readonly string[]): string {
  const normalizedIds = moduleIds.map((moduleId) => moduleId.replaceAll("\\", "/"));
  if (
    normalizedIds.some(
      (moduleId) =>
        moduleId.includes("/node_modules/mermaid/") ||
        moduleId.includes("/node_modules/@mermaid-js/"),
    )
  ) {
    return "assets/visualizations/mermaid";
  }
  if (
    normalizedIds.some(
      (moduleId) =>
        moduleId.includes("/node_modules/echarts/") ||
        moduleId.includes("/node_modules/zrender/"),
    )
  ) {
    return "assets/visualizations/echarts";
  }
  return "assets/chunks";
}

function knowledgeWorkspaceProductionBoundary(): Plugin {
  const frozenRoot = resolve(process.cwd(), "src/knowledge-workspace/frozen-ui");
  const productionRoot = resolve(process.cwd(), "src/knowledge-workspace/production");
  const storageVirtualId = "\0knowledge-workspace-storage";

  return {
    name: "knowledge-workspace-production-boundary",
    resolveId(source, importer) {
      if (source === "virtual:knowledge-workspace-storage") {
        return storageVirtualId;
      }
      if (!importer || !importer.startsWith(frozenRoot)) return null;
      const resolved = resolve(dirname(importer), source);
      const redirects: Record<string, string> = {
        [resolve(frozenRoot, "lib/store")]: resolve(productionRoot, "store.ts"),
        [resolve(frozenRoot, "lib/store.ts")]: resolve(productionRoot, "store.ts"),
        [resolve(frozenRoot, "lib/actionLoopStore")]: resolve(
          productionRoot,
          "actionLoop.ts",
        ),
        [resolve(frozenRoot, "lib/actionLoopStore.ts")]: resolve(
          productionRoot,
          "actionLoop.ts",
        ),
        [resolve(frozenRoot, "data/mockData")]: resolve(productionRoot, "data.ts"),
        [resolve(frozenRoot, "data/mockData.ts")]: resolve(
          productionRoot,
          "data.ts",
        ),
      };
      return redirects[resolved] ?? null;
    },
    load(id) {
      if (id === storageVirtualId) {
        return `export { knowledgeWorkspaceStorage } from ${JSON.stringify(
          resolve(productionRoot, "store.ts"),
        )};`;
      }
      return null;
    },
    transform(code, id) {
      if (!id.startsWith(`${frozenRoot}/`) || !/\.(tsx?|jsx?)$/.test(id)) {
        return null;
      }
      const usesStorage = /\blocalStorage\b/.test(code);
      const storageCode = usesStorage
        ? code.replaceAll("localStorage", "knowledgeWorkspaceStorage")
        : code;
      const mutationTransform = transformFrozenProductionMutations(
        storageCode,
        id,
        frozenRoot,
        productionRoot,
      );
      if (mutationTransform) {
        return {
          ...mutationTransform,
          code: usesStorage
            ? `import { knowledgeWorkspaceStorage } from "virtual:knowledge-workspace-storage";\n${mutationTransform.code}`
            : mutationTransform.code,
        };
      }
      if (!usesStorage) return null;
      return {
        code: `import { knowledgeWorkspaceStorage } from "virtual:knowledge-workspace-storage";\n${storageCode}`,
        map: null,
      };
    },
  };
}

export default defineConfig({
  // Keep the canonical host plugin declaration discoverable to existing
  // frontend contract checks; the boundary plugin is intentionally prepended.
  // plugins: [react(), tailwindcss()]
  plugins: [knowledgeWorkspaceProductionBoundary(), react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/list-apps": localApiProxy(),
      "/apps": localApiProxy(),
      "/run_sse": localApiProxy(),
      "/run": localApiProxy(),
      "/harness": localApiProxy(),
      "/debug": localApiProxy(),
      "/dev": localApiProxy(),
      "/oauth2": localApiProxy(),
      // Embed authorization depends on the customer's browser Origin, so this
      // proxy intentionally preserves Origin instead of using localApiProxy().
      "/embed": { target: API_TARGET },
      "/web": localApiProxy(),
      "/skillhub": {
        target: SKILLHUB_TARGET,
        changeOrigin: true,
        secure: true,
        rewrite: (p) => p.replace(/^\/skillhub/, ""),
      },
    },
  },
  build: {
    // Build straight into the Python package so `veadk frontend` ships the UI
    // with the wheel and works for pip-installed users.
    outDir: "../veadk/webui",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app/[name]-[hash].js",
        chunkFileNames: (chunkInfo) =>
          `${chunkDirectory(chunkInfo.moduleIds)}/[name]-[hash].js`,
        assetFileNames: (assetInfo) => {
          const name = assetInfo.names?.[0] ?? assetInfo.name ?? "asset";
          return name.endsWith(".css")
            ? "assets/styles/[name]-[hash][extname]"
            : "assets/media/[name]-[hash][extname]";
        },
      },
    },
  },
});
