import type { ToolCategory } from "./contracts";

type IconProps = { className?: string };

export function StatusIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" />
      <path d="m5 8 2 2 4-4" fill="none" stroke="currentColor" />
    </svg>
  );
}

export function ChevronIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
      <path d="m5 6 3 3 3-3" fill="none" stroke="currentColor" />
    </svg>
  );
}

export function ToolTypeIcon({
  category,
  className,
}: IconProps & { category: ToolCategory }) {
  if (category === "database") {
    return (
      <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
        <ellipse cx="8" cy="4" rx="5.5" ry="2.5" fill="none" stroke="currentColor" />
        <path d="M2.5 4v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5V4M2.5 8v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5V8" fill="none" stroke="currentColor" />
      </svg>
    );
  }
  if (category === "retrieval" || category === "connector") {
    return (
      <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="7" cy="7" r="4" fill="none" stroke="currentColor" />
        <path d="m10 10 3.5 3.5" fill="none" stroke="currentColor" />
      </svg>
    );
  }
  if (category === "skill" || category === "artifact") {
    return (
      <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
        <path d="M4 1.5h5l3 3V14H4zM9 1.5V5h3M6 8h4M6 11h4" fill="none" stroke="currentColor" />
      </svg>
    );
  }
  if (category === "mcp") {
    return (
      <svg className={className} viewBox="0 0 16 16" aria-hidden="true">
        <path d="M5 3v3M11 3v3M4 6h8v3a4 4 0 0 1-8 0zM8 13v2" fill="none" stroke="currentColor" />
      </svg>
    );
  }
  return <StatusIcon className={className} />;
}
