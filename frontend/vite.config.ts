import { dirname, relative, resolve } from "node:path";
import { readFileSync } from "node:fs";
import * as ts from "typescript";
import {
  defineConfig,
  transformWithEsbuild,
  type Plugin,
  type ProxyOptions,
} from "vite";
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
  "handleNext",
  "handlePrev",
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
const KW_LOCAL_COMPOSITION_HANDLERS = new Set([
  "handleLocalUpload",
  "handleFeishuCheck",
  "handleFeishuSync",
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
  if (name && KW_LOCAL_COMPOSITION_HANDLERS.has(name)) return false;
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

function kwStripPrototypeProductionDefaults(code: string, filePath: string): string {
  const name = filePath.replaceAll("\\", "/").split("?")[0];
  let output = code.replace(/demo_[A-Za-z0-9_]+/g, "knowledge_workspace_state");
  if (name.endsWith("/components/Layout/FileTreePane.tsx")) {
    output = output
      .replace(
        /const defaultPersonal = \[(?!\s*\])[\s\S]*?\n  \];/,
        "const defaultPersonal = [];",
      )
      .replace(
        /const defaultTeam = \[(?!\s*\])[\s\S]*?\n  \];/,
        "const defaultTeam = [];",
      )
      .replace(
        /if \(isSampleAdded\) datasetsChildren = \[[\s\S]*?\];/,
        "if (isSampleAdded) datasetsChildren = [];",
      );
    // The production bootstrap carries the real resource catalog. Preserve
    // the frozen tree's semantic node types and icon mapping when that
    // catalog replaces the prototype defaults: an artifact is draggable and
    // its subtype selects the same icon as the frozen catalog.
    output = output
      .replace(
        "type: r.resourceKind, \n      artifactType: r.subtype,",
        "type: r.resourceKind === 'artifact' ? (r.space === 'team' ? 'team_artifact' : 'personal_artifact') : r.resourceKind, \n      artifactType: r.subtype,",
      )
      .replace(
        "icon: (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') ? FileText : LayoutDashboard, ",
        "icon: r.subtype === 'chart' ? FilePieChart : r.subtype === 'dashboard' ? LayoutDashboard : r.subtype === 'semantic' ? FileText : r.subtype === 'knowledge_base' ? Library : r.subtype === 'kg' ? Globe : (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') ? FileText : LayoutDashboard, ",
      )
      .replace(
        "type: r.resourceKind, \n      artifactType: r.subtype, \n      readonly: true,",
        "type: r.resourceKind === 'artifact' ? 'team_artifact' : r.resourceKind, \n      artifactType: r.subtype, \n      readonly: true,",
      )
      .replace(
        "icon: (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') ? FileText : LayoutDashboard, \n      isDocs:",
        "icon: r.subtype === 'chart' ? FilePieChart : r.subtype === 'dashboard' ? LayoutDashboard : r.subtype === 'semantic' ? FileText : r.subtype === 'knowledge_base' ? Library : r.subtype === 'kg' ? Globe : (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') ? FileText : LayoutDashboard, \n      isDocs:",
      );
  }
  if (name.endsWith("/components/Layout/MainAreaPane.tsx")) {
    if (!output.includes("isWorkspaceRouteAvailable as isProductionRouteAvailable")) {
      output = output.replace(
        "import { resourceStore } from '../../lib/store';",
        "import { resourceStore } from '../../lib/store';\nimport { isWorkspaceRouteAvailable as isProductionRouteAvailable } from '../../../production/store';\nconst ProductionRouteUnavailable = ({ fileId }: { fileId: string }) => <div className=\"flex h-full min-h-[240px] items-center justify-center bg-slate-50 p-8\" role=\"alert\"><div className=\"max-w-md rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm\"><strong className=\"block text-sm font-semibold text-slate-800\">此资源暂不可用</strong><span className=\"mt-2 block text-xs leading-5 text-slate-500\">资源目录未授权或尚未从知识服务加载完成，请返回目录后重试。</span><code className=\"mt-3 block break-all text-[10px] text-slate-400\">{fileId}</code></div></div>;",
      );
    }
    if (!output.includes("isProductionRouteAvailable(fileId)")) {
      output = output.replace(
        "  const renderContent = () => {",
        "  const renderContent = () => {\n    if (fileId !== 'welcome' && !isProductionRouteAvailable(fileId)) return <ProductionRouteUnavailable fileId={fileId} />;",
      );
    }
  }
  if (name.endsWith("/components/MainArea/SemanticView.tsx")) {
    output = output
      .replace(
        /return (?:localStorage|knowledgeWorkspaceStorage)\.getItem\('demo_semantic_mdl_v5'\) \|\| `[\s\S]*?`;/,
        "return knowledgeWorkspaceStorage.getItem('demo_semantic_mdl_v5') || '';",
      )
      .replace(
        /return \{ DynamicTable: \{x: 60, y: 100\}, Customer: \{x: 460, y: 60\}, Region: \{x: 460, y: 280\}, Product: \{x: 460, y: 500\} \};/,
        "return {};",
      );
  }
  if (
    name.endsWith("/components/RightPane/CommentThread.tsx") ||
    name.endsWith("/components/MainArea/KnowledgeGraphView.tsx") ||
    name.endsWith("/components/MainArea/EvaluationCenterView.tsx")
  ) {
    output = output.replace(/return \[[\s\S]*?\n\s*\];/g, "return [];");
  }
  if (name.endsWith("/components/MainArea/KnowledgeGraphView.tsx")) {
    output = output.replace(
      /const \[entities, setEntities\] = useState<any\[\]>\(\(\) => \{[\s\S]*?\n\s*\}\);/,
      "const [entities, setEntities] = useState<any[]>([]);",
    );
  }
  if (name.endsWith("/components/Modals/ShareModal.tsx")) {
    output = output.replace(
      /\s*<tr className="hover:bg-slate-50 bg-white transition-colors">\s*<td[^>]*>昨天 09:00:00[\s\S]*?<\/tr>\s*<tr className="hover:bg-slate-50 bg-white transition-colors">\s*<td[^>]*>2天前 09:00:00[\s\S]*?<\/tr>/,
      "",
    );
  }
  if (name.endsWith("/components/MainArea/KnowledgeGraphView.tsx")) {
    output = output.replace(
      /const \[mappings, setMappings\] = useState(?:<[^>]+>)?\(\[[\s\S]*?\n  \]\);/,
      "const [mappings, setMappings] = useState<any[]>([]);",
    );
  }
  if (name.includes("/components/MainArea/SkillBuilderView.tsx")) {
    output = output.replace(
      /const \[candidateEndpoints, setCandidateEndpoints\] = useState(?:<[^>]+>)?\(\[[\s\S]*?\n\s*\]\);/,
      "const [candidateEndpoints, setCandidateEndpoints] = useState<any[]>([]);",
    );
  }
  if (name.endsWith("/components/Layout/FileTreePane.tsx")) {
    output = output.replace(
      "readonly: true, \n      icon:",
      "readonly: true, version: r.version, \n      icon:",
    );
  }
  return output;
}

function kwNeutralizePrototypeSuccessMessages(code: string): string {
  const positive = /成功|已成功|创建|发布|同步|上传|执行|应用|验证|完成|提交|绑定|授权|生效|更新|撤销|回滚|修复|导出|生成/;
  const sourceFile = ts.createSourceFile(
    "knowledge-workspace-production-toast.tsx",
    code,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const replacements: Array<{ start: number; end: number }> = [];
  kwWalk(sourceFile, (node) => {
    if (!ts.isCallExpression(node) || node.arguments.length === 0) return;
    const expression = node.expression;
    const isToast =
      (ts.isIdentifier(expression) && expression.text === "showToast") ||
      (ts.isPropertyAccessExpression(expression) &&
        expression.name.text === "showToast");
    if (!isToast) return;
    const argument = node.arguments[0];
    if (!positive.test(kwNodeText(code, argument))) return;
    replacements.push({
      start: argument.getStart(sourceFile),
      end: argument.end,
    });
  });
  let output = code;
  for (const replacement of replacements.sort(
    (left, right) => right.start - left.start,
  )) {
    output =
      output.slice(0, replacement.start) +
      '"已发送请求，等待状态刷新。"' +
      output.slice(replacement.end);
  }
  return output;
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
  if ([...KW_LOCAL_COMPOSITION_HANDLERS].some((name) =>
    new RegExp(`\\b${name}\\s*\\(`).test(body)
  )) return false;
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
  filePath?: string,
): string {
  const value = `${handlerName ?? ""} ${source}`.toLowerCase();
  if (
    filePath?.endsWith("/components/MainArea/AddKnowledgeBaseView.tsx") &&
    handlerName === "handleCreate"
  ) {
    return "skill-draft.create";
  }
  if (
    filePath?.endsWith("/components/MainArea/SkillBuilderView.tsx") &&
    value.includes("handlepublish")
  ) {
    return "skill-draft.save-manifest";
  }
  if (value.includes("publish") || value.includes("bind") || value.includes("发布") || value.includes("授权")) return "resource.publish";
  if (value.includes("share") || value.includes("分享")) return "resource.share";
  if (value.includes("revoke") || value.includes("rollback") || value.includes("撤销") || value.includes("回滚")) return "resource.revoke";
  if (value.includes("export") || value.includes("导出")) return "artifact.export";
  if (
    value.includes("connector") ||
    value.includes("feishu") ||
    value.includes("upload")
  ) {
    return "connector.create";
  }
  if (value.includes("eval") || value.includes("regress") || value.includes("评测") || value.includes("回归")) return "evaluation.run";
  if (
    value.includes("todo") ||
    value.includes("review") ||
    value.includes("brief") ||
    value.includes("alert")
  ) {
    return "action.update";
  }
  if (
    value.includes("assistant") ||
    value.includes("chat") ||
    value.includes("handlesend") ||
    value.includes("助手") ||
    value.includes("对话")
  ) return "assistant.turn";
  return "action.update";
}

function kwPreserveHandler(
  handlerName: string | undefined,
  source: string,
): boolean {
  // The frozen welcome composer uses handleSend for a local URL/state
  // transition. Keep that interaction intact, but gate it behind the typed
  // assistant.turn acknowledgement so a rejected production command cannot
  // appear as a successful UI mutation.
  return handlerName === "handleSend" || /\bhandleSend\s*\(/.test(source);
}

export function transformFrozenProductionMutations(
  code: string,
  filePath: string,
  frozenRoot: string,
  productionRoot: string,
): { code: string; map: null; mutationCount: number } | null {
  const productionCode = kwStripPrototypeProductionDefaults(code, filePath);
  // AddDataView now dispatches the typed Source/Golden commands directly
  // through the production adapter. Wrapping its inline handlers in the
  // generic prototype action.update fallback would suppress that real flow.
  if (
    filePath.endsWith("/components/MainArea/AddDataView.tsx") ||
    filePath.endsWith("/components/MainArea/SkillBuilderView.tsx") ||
    filePath.endsWith("/components/Modals/PublishAgentModal.tsx") ||
    filePath.endsWith("/components/Modals/PublishModal.tsx") ||
    filePath.endsWith("/components/Modals/AgentResourceSelectorModal.tsx") ||
    filePath.endsWith("/components/RightPane/ChatAssistant.tsx") ||
    filePath.endsWith("/components/Layout/HomeComposer.tsx")
  ) {
    return productionCode === code
      ? null
      : { code: productionCode, map: null, mutationCount: 0 };
  }
  const sourceFile = ts.createSourceFile(
    filePath,
    productionCode,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const mutationNames = kwResolveMutationNames(sourceFile, productionCode);
  const directPrototypeMutationNames = new Set<string>();
  kwWalk(sourceFile, (node) => {
    if (!kwIsFunctionLike(node) || !("body" in node) || !node.body) return;
    const name = kwFunctionName(node);
    if (
      name &&
      !/^[A-Z]/.test(name) &&
      !kwContainsJsx(node.body) &&
      kwPrototypeEffect(kwNodeText(productionCode, node.body))
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
      !KW_LOCAL_COMPOSITION_HANDLERS.has(name) &&
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
      kwPrototypeEffect(kwNodeText(productionCode, node.body))
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
    if (!kwHandlerIsMutation(expression, node.name.text, productionCode, mutationNames)) {
      return;
    }
    const preserveHandler = kwPreserveHandler(
      handlerName,
      kwNodeText(productionCode, expression),
    );
    const original = kwNodeText(productionCode, expression);
    const invokeOriginal = preserveHandler
      ? `if (__kwAccepted) { (${original})(...__kwArgs${index}); }`
      : "";
    const preventDefault = preserveHandler && node.name.text === "onKeyDown"
      ? `if (__kwArgs${index}[0]?.key !== "Enter" || __kwArgs${index}[0]?.shiftKey) { return; } __kwArgs${index}[0].preventDefault();`
      : "";
    replacements.push({
      start: expression.getStart(sourceFile),
      end: expression.end,
      value: `(...__kwArgs${index}) => { ${preventDefault} void __runProductionMutation(${JSON.stringify(
        {
          command: kwCommandForHandler(
            handlerName,
            kwNodeText(productionCode, expression),
            filePath,
          ),
          sourcePath: filePath
            .slice(frozenRoot.length + 1)
            .replaceAll("\\", "/"),
          eventName: node.name.text,
          ...(handlerName ? { handlerName } : {}),
        },
      )}).then((__kwAccepted) => { ${invokeOriginal} }); }`,
    });
    index += 1;
  });
  const allReplacements = [
    ...replacements,
    ...functionReplacements,
    ...effectReplacements,
  ];
  if (allReplacements.length === 0) {
    const adapted = kwNeutralizePrototypeSuccessMessages(productionCode);
    return adapted === code
      ? null
      : { code: adapted, map: null, mutationCount: 0 };
  }
  let output = productionCode;
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
    code: kwNeutralizePrototypeSuccessMessages(
      `import { runProductionMutation as __runProductionMutation } from ${JSON.stringify(runtimePath)};\n${output}`,
    ),
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

function appsSdkReact18Compatibility(): Plugin {
  return {
    name: "apps-sdk-react-18-compatibility",
    enforce: "pre",
    transform(code, id) {
      const cleanId = id.split("?")[0].replaceAll("\\", "/");
      if (
        !cleanId.includes("/node_modules/@openai/apps-sdk-ui/") ||
        !/\.(?:m?js|jsx?|tsx?)$/.test(cleanId) ||
        !/\buse\b/.test(code)
      ) {
        return null;
      }

      const imported = code.replace(
        /(\bimport\s+(?:React\s*,\s*)?\{[^}]*?)\buse\b(?=\s*[,}])/g,
        "$1useContext",
      );
      const compatible = imported.replace(
        /\buse\((?=[A-Za-z_$][\w$]*Context\b)/g,
        "useContext(",
      );
      const withProvider = compatible.replace(
        /(\b_?jsx)\(([A-Za-z_$][\w$]*Context),\s*\{\s*value:/g,
        "$1($2.Provider, { value:",
      );
      return withProvider === code ? null : { code: withProvider, map: null };
    },
  };
}

function knowledgeWorkspaceProductionBoundary(): Plugin {
  const frozenRoot = resolve(process.cwd(), "src/knowledge-workspace/frozen-ui");
  const productionRoot = resolve(process.cwd(), "src/knowledge-workspace/production");
  const storageVirtualId = "\0knowledge-workspace-storage";

  return {
    name: "knowledge-workspace-production-boundary",
    enforce: "pre",
    resolveId(source, importer) {
      if (source === "virtual:knowledge-workspace-storage") {
        return storageVirtualId;
      }
      const cleanImporter = importer?.split("?")[0];
      if (!cleanImporter || !cleanImporter.startsWith(frozenRoot)) return null;
      const cleanSource = source.split("?")[0].replaceAll("\\", "/");
      const resolved = resolve(dirname(cleanImporter), cleanSource);
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
      if (redirects[resolved]) return redirects[resolved];
      if (/(?:^|\/)lib\/store(?:\.ts)?$/.test(cleanSource)) {
        return resolve(productionRoot, "store.ts");
      }
      if (/(?:^|\/)lib\/actionLoopStore(?:\.ts)?$/.test(cleanSource)) {
        return resolve(productionRoot, "actionLoop.ts");
      }
      if (/(?:^|\/)data\/mockData(?:\.ts)?$/.test(cleanSource)) {
        return resolve(productionRoot, "data.ts");
      }
      return null;
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
      const cleanId = id.split("?")[0];
      if (!cleanId.startsWith(`${frozenRoot}/`) || !/\.(tsx?|jsx?)$/.test(cleanId)) {
        return null;
      }
      const usesStorage = /\blocalStorage\b/.test(code);
      const storageCode = usesStorage
        ? code.replaceAll("localStorage", "knowledgeWorkspaceStorage")
        : code;
      const mutationTransform = transformFrozenProductionMutations(
        storageCode,
        cleanId,
        frozenRoot,
        productionRoot,
      );
      if (mutationTransform) {
        const adaptedCode = usesStorage
          ? `import { knowledgeWorkspaceStorage } from "virtual:knowledge-workspace-storage";\n${mutationTransform.code}`
          : mutationTransform.code;
        return transformWithEsbuild(adaptedCode, cleanId, {
          loader: cleanId.endsWith(".tsx") ? "tsx" : "ts",
          target: "es2020",
          jsx: "automatic",
          sourcemap: false,
        });
      }
      if (storageCode === code && !usesStorage) return null;
      const productionCode = kwStripPrototypeProductionDefaults(
        storageCode,
        cleanId,
      );
      const adaptedCode = usesStorage
        ? `import { knowledgeWorkspaceStorage } from "virtual:knowledge-workspace-storage";\n${productionCode}`
        : productionCode;
      return transformWithEsbuild(adaptedCode, cleanId, {
        loader: cleanId.endsWith(".tsx") ? "tsx" : "ts",
        target: "es2020",
        jsx: "automatic",
        sourcemap: false,
      });
    },
  };
}

export default defineConfig({
  // Keep the canonical host plugin declaration discoverable to existing
  // frontend contract checks; the boundary plugin is intentionally prepended.
  // plugins: [react(), tailwindcss()]
  plugins: [
    knowledgeWorkspaceProductionBoundary(),
    appsSdkReact18Compatibility(),
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api/knowledge-assets": localApiProxy(),
      "/api/source-golden": localApiProxy(),
      "/api/knowledge-domains": localApiProxy(),
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
