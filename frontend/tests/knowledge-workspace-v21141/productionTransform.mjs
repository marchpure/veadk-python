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

function commandForHandler(handlerName, source) {
  const value = `${handlerName ?? ""} ${source}`.toLowerCase();
  if (value.includes("publish") || value.includes("bind")) return "resource.publish";
  if (value.includes("share")) return "resource.share";
  if (value.includes("revoke") || value.includes("rollback")) return "resource.revoke";
  if (value.includes("export")) return "artifact.export";
  if (value.includes("connector") || value.includes("feishu") || value.includes("upload")) {
    return "connector.create";
  }
  if (value.includes("eval") || value.includes("regress")) return "evaluation.run";
  if (value.includes("todo") || value.includes("review") || value.includes("brief") || value.includes("alert")) {
    return "action.update";
  }
  if (value.includes("assistant") || value.includes("chat")) return "assistant.turn";
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
  const sourceFile = ts.createSourceFile(
    filePath,
    code,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const mutationNames = resolveMutationNames(sourceFile, code);
  const directPrototypeMutationNames = new Set();
  walk(sourceFile, (node) => {
    if (!isFunctionLike(node) || !node.body) return;
    const name = functionName(node);
    if (
      name &&
      !/^[A-Z]/.test(name) &&
      !containsJsx(node.body) &&
      prototypeEffect(nodeText(code, node.body))
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
      const body = nodeText(code, node.body);
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
    if (!handlerIsMutation(expression, node.name.text, code, mutationNames)) return;
    replacements.push({
      start: expression.getStart(sourceFile),
      end: expression.end,
      value: wrapperFor({
        sourcePath: filePath.slice(frozenRoot.length + 1).replaceAll("\\", "/"),
        eventName: node.name.text,
        handlerName,
        command: commandForHandler(handlerName, nodeText(code, expression)),
        index: index++,
      }),
    });
  });

  const allReplacements = [
    ...replacements,
    ...functionReplacements,
    ...effectReplacements,
  ];
  if (allReplacements.length === 0) return null;
  const runtimeImport = importPathFor(filePath, frozenRoot, productionRoot);
  let output = code;
  for (const replacement of allReplacements.sort(
    (left, right) => right.start - left.start,
  )) {
    output =
      output.slice(0, replacement.start) +
      replacement.value +
      output.slice(replacement.end);
  }
  output = `import { runProductionMutation as __runProductionMutation } from ${JSON.stringify(runtimeImport)};\n${output}`;
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
