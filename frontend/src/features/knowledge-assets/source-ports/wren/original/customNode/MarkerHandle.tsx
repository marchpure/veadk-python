import { Handle, Position } from "@xyflow/react";

export default function MarkerHandle({ id }: { id: string }) {
  return (
    <>
      <Handle type="source" position={Position.Left} id={`${id}_${Position.Left}`} />
      <Handle type="source" position={Position.Right} id={`${id}_${Position.Right}`} />
      <Handle type="target" position={Position.Left} id={`${id}_${Position.Left}`} />
      <Handle type="target" position={Position.Right} id={`${id}_${Position.Right}`} />
    </>
  );
}
