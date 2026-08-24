import { relative } from "node:path";
import ts from "typescript";

const STORE_TOKEN = ["local", "Storage"].join("");
const MUTATION_SETTERS =
  /\bset(?:PublishedItems|ReusedItems|Comments|Shares|DynamicHistory|Scenes|Questions|Entities|Mappings|AgentBound|Todos|Reviews|Briefs|Alert|Alerts|Fix|FixPlan|Sources|JobState|FeishuState|UploadState|DraftCode|Manifest|CandidateEndpoints|MdlCode|LoopState|Resource|Connections|Publications|Registry)\s*\(/;
const STORE_MUTATION =
  /\b(?:resourceStore|connectionStore|actionLoopStore|customRegistryStore|agentPublicationStore|dragStore)\s*\.\s*setState\s*\(/;
const SUCCESS_MESSAGE =
  /\bshowToast\??\s*\([\s\S]{0,300}(?:成功|已成功|保存|发布|创建|同步|上传|执行|应用|验证|完成|提交|绑定|撤销|回滚|修复|测试|导出|生成)/;
const MUTATING_INTENT_TEXT =
  /\b(?:发布|创建|同步|上传|执行|应用|验证|提交|绑定|撤销|回滚|修复|测试|导出|生成)\b/;
const TIMER = /\b(?:setTimeout|setInterval)\s*\(/;
const EVENT_NAME = /^on[A-Z]/;
const NON_MUTATING_HANDLERS = new Set([
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

function nodeText(source, node) {
  return source.slice(node.getStart(), node.end);
}

function walk(node, visit) {
  visit(node);
  node.forEachChild((child) => walk(child, visit));
}

function functionName(node) {
  if (node.name?.text) return node.name.text;
  if (ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name)) {
    return node.parent.name.text;
  }
  if (
    (ts.isPropertyAssignment(node.parent) || ts.isPropertyDeclaration(node.parent)) &&
    (ts.isIdentifier(node.parent.name) || ts.isStringLiteral(node.parent.name))
  ) {
    return node.parent.name.text;
  }
  return undefined;
}

function isFunctionLike(node) {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isArrowFunction(node) ||
    ts.isFunctionExpression(node)
  );
}

function containsJsx(node) {
  let found = false;
  walk(node, (child) => {
    if (ts.isJsxElement(child) || ts.isJsxSelfClosingElement(child)) {
      found = true;
    }
  });
  return found;
}

function mutationLike(name, body) {
  if (name && NON_MUTATING_HANDLERS.has(name)) return false;
  if (
    name &&
    /^(?:handleSend|handleSuggestionClick|handleRealFileUpload|handleUpload|handleNext|handlePublish|handleConfirm|confirm|apply|startReEval|applySuggestions|generate|request|approve|save|submit|create|publish|share|revoke|test|sync|refresh|retry|delete|remove)/.test(
      name,
    )
  ) {
    return true;
  }
  if (STORE_MUTATION.test(body.replaceAll("dragStore", ""))) return true;
  if (new RegExp(`\\b${STORE_TOKEN}\\b`).test(body)) return true;
  if (MUTATION_SETTERS.test(body)) return true;
  if (SUCCESS_MESSAGE.test(body)) return true;
  if (
    TIMER.test(body) &&
    name &&
    /^(?:handle|start|apply|confirm|save|run|test|upload|sync|create|publish|share|send|submit|approve|complete|generate|refresh|retry|remove|delete|revoke)/.test(
      name,
    )
  ) {
    return true;
  }
  return false;
}

function prototypeEffect(body) {
  return (
    new RegExp(`\\b(?:${STORE_TOKEN}|knowledgeWorkspaceStorage)\\b`).test(body) ||
    STORE_MUTATION.test(body.replaceAll("dragStore", "")) ||
    SUCCESS_MESSAGE.test(body) ||
    (TIMER.test(body) &&
      (MUTATION_SETTERS.test(body) || MUTATING_INTENT_TEXT.test(body)))
  );
}

function resolveMutationNames(sourceFile, source) {
  const functions = new Map();
  walk(sourceFile, (node) => {
    if (!isFunctionLike(node)) return;
    const name = functionName(node);
    if (!name || !node.body || /^[A-Z]/.test(name)) return;
    functions.set(name, nodeText(source, node.body));
  });

  const names = new Set(
    [...functions].filter(([name, body]) => mutationLike(name, body)).map(([name]) => name),
  );
  let changed = true;
  while (changed) {
    changed = false;
    for (const [name, body] of functions) {
      if (names.has(name)) continue;
      for (const dependency of names) {
        if (new RegExp(`\\b${dependency}\\s*\\(`).test(body)) {
          names.add(name);
          changed = true;
          break;
        }
      }
    }
  }
  return names;
}

function handlerIsMutation(expression, eventName, source, mutationNames) {
  // Draft input and composition events are local editing state. They must not
  // become network commands on every keystroke.
  if (eventName === "onChange" || eventName === "onCompositionUpdate") {
    return false;
  }
  if (ts.isIdentifier(expression)) return mutationNames.has(expression.text);
  if (!ts.isArrowFunction(expression) && !ts.isFunctionExpression(expression)) {
    return false;
  }
  const body = nodeText(source, expression.body);
  if (mutationLike(undefined, body)) return true;
  return [...mutationNames].some((name) =>
    new RegExp(`\\b${name}\\s*\\(`).test(body),
  );
}

/**
 * The frozen package contains prototype-only catalog and in-memory seed
 * values. Keep those files immutable on disk, but remove those defaults from
 * the production module graph. Real resource data is admitted only through
 * the bootstrap store.
 */
export function stripPrototypeProductionDefaults(code, filePath) {
  let output = code;
  const name = filePath.replaceAll("\\", "/");
  output = output.replace(/demo_[A-Za-z0-9_]+/g, "knowledge_workspace_state");
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
        /return localStorage\.getItem\('demo_semantic_mdl_v5'\) \|\| `[\s\S]*?`;/,
        "return localStorage.getItem('demo_semantic_mdl_v5') || '';",
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
  if (name.endsWith("/components/MainArea/KnowledgeGraphView.tsx")) {
    output = output.replace(
      /const \[mappings, setMappings\] = useState(?:<[^>]+>)?\(\[[\s\S]*?\n  \]\);/,
      "const [mappings, setMappings] = useState<any[]>([]);",
    );
  }
  if (name.endsWith("/components/Modals/ShareModal.tsx")) {
    output = output.replace(
      /\s*<tr className="hover:bg-slate-50 bg-white transition-colors">\s*<td[^>]*>昨天 09:00:00[\s\S]*?<\/tr>\s*<tr className="hover:bg-slate-50 bg-white transition-colors">\s*<td[^>]*>2天前 09:00:00[\s\S]*?<\/tr>/,
      "",
    );
  }
  if (name.endsWith("/components/MainArea/SkillBuilderView.tsx")) {
    output = output.replace(
      /const \[candidateEndpoints, setCandidateEndpoints\] = useState\(\[[\s\S]*?\n  \]\);/,
      "const [candidateEndpoints, setCandidateEndpoints] = useState<any[]>([]);",
    );
  }
  return output;
}

function neutralizePrototypeSuccessMessages(code) {
  const positive =
    /成功|已成功|创建|发布|同步|上传|执行|应用|验证|完成|提交|绑定|授权|生效|更新|撤销|回滚|修复|导出|生成/;
  const sourceFile = ts.createSourceFile(
    "knowledge-workspace-production-toast.tsx",
    code,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const replacements = [];
  walk(sourceFile, (node) => {
    if (!ts.isCallExpression(node) || node.arguments.length === 0) return;
    const expression = node.expression;
    const isToast =
      (ts.isIdentifier(expression) && expression.text === "showToast") ||
      (ts.isPropertyAccessExpression(expression) &&
        expression.name.text === "showToast");
    if (!isToast) return;
    const argument = node.arguments[0];
    if (!positive.test(nodeText(code, argument))) return;
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

function commandForHandler(handlerName, source) {
  const value = `${handlerName ?? ""} ${source}`.toLowerCase();
  if (value.includes("publish") || value.includes("bind") || value.includes("发布") || value.includes("授权")) return "resource.publish";
  if (value.includes("share") || value.includes("分享")) return "resource.share";
  if (value.includes("revoke") || value.includes("rollback") || value.includes("撤销") || value.includes("回滚")) return "resource.revoke";
  if (value.includes("export") || value.includes("导出")) return "artifact.export";
  if (value.includes("connector") || value.includes("feishu") || value.includes("upload")) {
    return "connector.create";
  }
  if (value.includes("eval") || value.includes("regress") || value.includes("评测") || value.includes("回归")) return "evaluation.run";
  if (value.includes("todo") || value.includes("review") || value.includes("brief") || value.includes("alert")) {
    return "action.update";
  }
  if (value.includes("assistant") || value.includes("chat") || value.includes("助手") || value.includes("对话")) return "assistant.turn";
  return "workspace.mutation";
}

function importPathFor(filePath, frozenRoot, productionRoot) {
  const from = filePath.slice(0, filePath.lastIndexOf("/"));
  let path = relative(from, `${productionRoot}/store.ts`).replaceAll("\\", "/");
  if (!path.startsWith(".")) path = `./${path}`;
  return path;
}

function wrapperFor({
  sourcePath,
  eventName,
  handlerName,
  command,
  index,
}) {
  const args = `__kwArgs${index}`;
  const intent = JSON.stringify({
    command,
    sourcePath,
    eventName,
    ...(handlerName ? { handlerName } : {}),
  });
  return `(...${args}) => { void __runProductionMutation(${intent}); }`;
}

/**
 * Wrap only handlers that can persist or claim an async mutation. Navigation,
 * focus, drag, tab, and ordinary draft-input handlers remain byte-for-byte
 * represented in the emitted module.
 */
export function transformFrozenProductionMutations(
  code,
  filePath,
  frozenRoot,
  productionRoot,
) {
  const productionCode = stripPrototypeProductionDefaults(code, filePath);
  const sourceFile = ts.createSourceFile(
    filePath,
    productionCode,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const mutationNames = resolveMutationNames(sourceFile, productionCode);
  const directPrototypeMutationNames = new Set();
  walk(sourceFile, (node) => {
    if (!isFunctionLike(node) || !node.body) return;
    const name = functionName(node);
    if (
      name &&
      !/^[A-Z]/.test(name) &&
      !containsJsx(node.body) &&
      prototypeEffect(nodeText(productionCode, node.body))
    ) {
      directPrototypeMutationNames.add(name);
    }
  });
  const replacements = [];
  const functionReplacements = [];
  const effectReplacements = [];
  let index = 0;

  walk(sourceFile, (node) => {
    if (isFunctionLike(node) && node.body) {
      const name = functionName(node);
      if (
        name &&
        directPrototypeMutationNames.has(name) &&
        !containsJsx(node.body)
      ) {
        functionReplacements.push({
          start: node.body.getStart(sourceFile),
          end: node.body.end,
          value: ts.isBlock(node.body) ? "{}" : "undefined",
        });
      }
    }
    if (
      isFunctionLike(node) &&
      ts.isArrowFunction(node) &&
      ts.isCallExpression(node.parent) &&
      ts.isIdentifier(node.parent.expression) &&
      node.parent.expression.text === "useEffect" &&
      node.body
    ) {
      const body = nodeText(productionCode, node.body);
      if (prototypeEffect(body)) {
        effectReplacements.push({
          start: node.body.getStart(sourceFile),
          end: node.body.end,
          value: ts.isBlock(node.body) ? "{}" : "undefined",
        });
      }
    }
    if (!ts.isJsxAttribute(node) || !EVENT_NAME.test(node.name.text)) return;
    const initializer = node.initializer;
    if (!initializer || !ts.isJsxExpression(initializer) || !initializer.expression) return;
    const expression = initializer.expression;
    const handlerName = ts.isIdentifier(expression) ? expression.text : undefined;
    if (!handlerIsMutation(expression, node.name.text, productionCode, mutationNames)) return;
    replacements.push({
      start: expression.getStart(sourceFile),
      end: expression.end,
      value: wrapperFor({
        sourcePath: filePath.slice(frozenRoot.length + 1).replaceAll("\\", "/"),
        eventName: node.name.text,
        handlerName,
        command: commandForHandler(handlerName, nodeText(productionCode, expression)),
        index: index++,
      }),
    });
  });

  const allReplacements = [
    ...replacements,
    ...functionReplacements,
    ...effectReplacements,
  ];
  if (allReplacements.length === 0) {
    const adapted = neutralizePrototypeSuccessMessages(productionCode);
    return adapted === productionCode
      ? null
      : { code: adapted, map: null, mutationCount: 0 };
  }
  const runtimeImport = importPathFor(filePath, frozenRoot, productionRoot);
  let output = productionCode;
  for (const replacement of allReplacements.sort(
    (left, right) => right.start - left.start,
  )) {
    output =
      output.slice(0, replacement.start) +
      replacement.value +
      output.slice(replacement.end);
  }
  output = neutralizePrototypeSuccessMessages(
    `import { runProductionMutation as __runProductionMutation } from ${JSON.stringify(runtimeImport)};\n${output}`,
  );
  return { code: output, map: null, mutationCount: replacements.length };
}

export function analyzeFrozenProductionMutations(code, filePath) {
  const sourceFile = ts.createSourceFile(
    filePath,
    code,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const mutationNames = resolveMutationNames(sourceFile, code);
  const handlers = [];
  walk(sourceFile, (node) => {
    if (!ts.isJsxAttribute(node) || !EVENT_NAME.test(node.name.text)) return;
    const initializer = node.initializer;
    if (!initializer || !ts.isJsxExpression(initializer) || !initializer.expression) {
      return;
    }
    const expression = initializer.expression;
    const handlerName = ts.isIdentifier(expression) ? expression.text : undefined;
    if (!handlerIsMutation(expression, node.name.text, code, mutationNames)) return;
    handlers.push({
      eventName: node.name.text,
      handlerName,
      source: nodeText(code, expression),
    });
  });
  return { mutationNames, handlers };
}
