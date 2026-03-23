import { ReactNode } from "react";

interface IconButtonProps {
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
}

export function IconButton({
  icon,
  label,
  active = false,
  onClick,
  disabled = false,
  className = ""
}: IconButtonProps) {
  const stateClass = active
    ? "border-neon-green/60 text-neon-green shadow-glow"
    : "border-panel-border/60 text-text-muted/85 hover:border-neon-green/45 hover:text-neon-green";

  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={`theme-subtle-surface inline-flex h-8 w-8 items-center justify-center rounded-[var(--theme-radius-control)] border transition-all duration-200 ${stateClass} ${
        disabled ? "cursor-not-allowed opacity-40" : ""
      } ${className}`}
    >
      {icon}
    </button>
  );
}
