"use client";

import { Hash } from "lucide-react";

type TagChipProps = {
  name: string;
  compact?: boolean;
};

export default function TagChip({ name, compact = false }: TagChipProps) {
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded-full border border-primary/25 bg-primary/10 font-semibold text-primary shadow-sm ${
        compact ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-sm"
      }`}
      title={`#${name}`}
    >
      <Hash className="shrink-0" size={compact ? 12 : 14} />
      <span className="truncate">{name}</span>
    </span>
  );
}
