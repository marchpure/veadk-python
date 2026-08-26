# Graph and ontology design contract

- Use a topology map with a legend and a right-hand evidence inspector.
- Nodes are selectable with keyboard focus and `data-node-id`; relation
  filtering is a declaration captured by the Shell.
- Avoid pretending a graph layout is semantic truth: evidence rows remain
  visible and conflicts use a distinct callout.
- Keep the SVG deterministic and free of scripts, markers and external assets.
