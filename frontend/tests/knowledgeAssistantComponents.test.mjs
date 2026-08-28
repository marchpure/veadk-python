import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";
import { JSDOM } from "jsdom";

const require = createRequire(import.meta.url);

async function loadComponent(entry, exportName) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(entry, import.meta.url))],
    bundle: true,
    external: ["react", "react-dom", "react-dom/*"],
    format: "cjs",
    platform: "node",
    plugins: [{
      name: "assistant-component-stubs",
      setup(buildContext) {
        buildContext.onResolve(
          { filter: /\/AssistantMessage$/ },
          () => ({ path: "assistant-message-stub", namespace: "test" }),
        );
        buildContext.onLoad(
          { filter: /^assistant-message-stub$/, namespace: "test" },
          () => ({
            contents: "export function AssistantMessage() { return null; }",
            loader: "js",
          }),
        );
      },
    }],
    write: false,
  });
  const module = { exports: {} };
  Function("require", "module", "exports", result.outputFiles[0].text)(
    require,
    module,
    module.exports,
  );
  return module.exports[exportName];
}

async function render(Component, props) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', {
    pretendToBeVisual: true,
  });
  const names = [
    "window",
    "document",
    "navigator",
    "HTMLElement",
    "Node",
    "Event",
    "MouseEvent",
    "KeyboardEvent",
    "getComputedStyle",
    "requestAnimationFrame",
    "cancelAnimationFrame",
    "IS_REACT_ACT_ENVIRONMENT",
  ];
  const previous = new Map(names.map((name) => [
    name,
    Object.getOwnPropertyDescriptor(globalThis, name),
  ]));
  for (const [name, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    getComputedStyle: dom.window.getComputedStyle,
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value,
      writable: true,
    });
  }
  const React = require("react");
  const { createRoot } = require("react-dom/client");
  const { act } = React;
  const root = createRoot(dom.window.document.getElementById("root"));
  await act(async () => root.render(React.createElement(Component, props)));
  return {
    act,
    container: dom.window.document.getElementById("root"),
    cleanup: async () => {
      await act(async () => root.unmount());
      dom.window.close();
      for (const [name, descriptor] of previous) {
        if (descriptor === undefined) delete globalThis[name];
        else Object.defineProperty(globalThis, name, descriptor);
      }
    },
  };
}

const activities = [{
  id: "call-1",
  callId: "call-1",
  kind: "tool",
  title: "查询",
  status: "succeeded",
  startedAt: "2026-08-28T00:00:00Z",
  completedAt: "2026-08-28T00:00:01Z",
}];

test("activity timeline is open while running and collapsed after completion", async () => {
  const ActivityTimeline = await loadComponent(
    "../src/features/knowledge-workspace/assistant/ActivityTimeline.tsx",
    "ActivityTimeline",
  );
  const running = await render(ActivityTimeline, { activities, status: "running" });
  try {
    assert.equal(running.container.querySelector("details")?.open, true);
  } finally {
    await running.cleanup();
  }
  const complete = await render(ActivityTimeline, { activities, status: "succeeded" });
  try {
    const details = complete.container.querySelector("details");
    assert.equal(details?.open, false);
    await complete.act(async () => details?.querySelector("summary")?.click());
    assert.equal(details?.open, true);
  } finally {
    await complete.cleanup();
  }
});

test("assistant composer blocks duplicate submits and ignores IME enter", async () => {
  const AssistantPanel = await loadComponent(
    "../src/features/knowledge-workspace/assistant/AssistantPanel.tsx",
    "AssistantPanel",
  );
  let resolveSend;
  const calls = [];
  const view = await render(AssistantPanel, {
    turns: [],
    busy: false,
    onSend: (message, intent) => {
      calls.push([message, intent]);
      return new Promise((resolve) => { resolveSend = resolve; });
    },
    onCancel: async () => {},
    onReconnect: () => {},
    onRetry: () => {},
  });
  try {
    const textarea = view.container.querySelector("textarea");
    await view.act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        view.container.ownerDocument.defaultView.HTMLTextAreaElement.prototype,
        "value",
      ).set;
      setter.call(textarea, "运行一次");
      textarea.dispatchEvent(new view.container.ownerDocument.defaultView.Event(
        "input",
        { bubbles: true },
      ));
    });
    await view.act(async () => {
      textarea.dispatchEvent(new view.container.ownerDocument.defaultView.KeyboardEvent(
        "keydown",
        { key: "Enter", keyCode: 229, bubbles: true },
      ));
    });
    assert.equal(calls.length, 0);

    const send = view.container.querySelector('button[type="submit"]');
    await view.act(async () => {
      send.click();
      send.click();
      await Promise.resolve();
    });
    assert.deepEqual(calls, [["运行一次", "run"]]);
    await view.act(async () => resolveSend());
  } finally {
    await view.cleanup();
  }
});
