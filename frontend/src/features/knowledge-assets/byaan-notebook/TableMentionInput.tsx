import { forwardRef, type KeyboardEvent } from "react";

export const TableMentionInput = forwardRef<HTMLTextAreaElement, {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
  disabled?: boolean;
  singleLine?: boolean;
}>(
  ({ value, onValueChange, onSubmit, placeholder, disabled, singleLine = false }, ref) => {
    function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        onSubmit?.();
      }
    }

    return (
      <textarea
        ref={ref}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={singleLine ? 1 : 4}
        disabled={disabled}
        placeholder={placeholder}
        className="min-h-[56px] w-full resize-none bg-transparent px-4 py-3 text-sm leading-6 text-[#18181b] outline-none placeholder:text-[#a1a1aa] disabled:cursor-not-allowed disabled:opacity-60"
      />
    );
  },
);
