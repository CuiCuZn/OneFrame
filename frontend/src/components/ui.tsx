import { useEffect, useId, type ButtonHTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useEsc } from "../lib/hooks";
import { useStore } from "../lib/store";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "soft" | "ghost" | "danger" | "outline";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  loading?: boolean;
  block?: boolean;
};

export function Button({
  variant = "soft",
  size = "md",
  icon,
  loading,
  block,
  className = "",
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`btn btn-${variant} btn-${size} ${block ? "btn-block" : ""} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <span className="spinner spinner-sm" /> : icon}
      {children != null && <span>{children}</span>}
    </button>
  );
}

export function IconButton({
  label,
  active,
  children,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      className={`icon-btn ${active ? "is-active" : ""} ${className}`}
      title={label}
      aria-label={label}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Chip({
  active,
  children,
  onClick,
  title,
}: {
  active?: boolean;
  children: ReactNode;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <button type="button" className={`chip ${active ? "is-active" : ""}`} onClick={onClick} title={title}>
      {children}
    </button>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className={`segmented segmented-${size}`} role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          className={option.value === value ? "is-active" : ""}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
  inline,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  inline?: boolean;
}) {
  const id = useId();
  return (
    <label className={`field ${inline ? "field-inline" : ""}`} htmlFor={id}>
      <span className="field-label">
        {label}
        {hint && <em>{hint}</em>}
      </span>
      {children}
    </label>
  );
}

export function Modal({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
  width = 560,
}: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  useEsc(onClose, open);
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal"
        style={{ width: `min(${width}px, calc(100vw - 32px))` }}
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <header className="modal-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <IconButton label="关闭" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  compact,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty ${compact ? "empty-compact" : ""}`}>
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="loading-row">
      <span className="spinner" />
      {label && <span>{label}</span>}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
  dot,
}: {
  tone?: "neutral" | "ok" | "warn" | "error" | "accent";
  children: ReactNode;
  dot?: boolean;
}) {
  return (
    <span className={`badge badge-${tone}`}>
      {dot && <i />}
      {children}
    </span>
  );
}

export function ToastHost() {
  const { toasts, dismiss } = useStore();
  if (!toasts.length) return null;
  return createPortal(
    <div className="toast-host">
      {toasts.map((toast) => (
        <button
          key={toast.id}
          className={`toast toast-${toast.kind}`}
          onClick={() => dismiss(toast.id)}
          type="button"
        >
          <span className="toast-dot" />
          {toast.message}
        </button>
      ))}
    </div>,
    document.body,
  );
}

export function PageHead({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      className={`toggle ${checked ? "is-on" : ""}`}
      onClick={() => onChange(!checked)}
      role="switch"
      aria-checked={checked}
      aria-label={label}
    >
      <span />
    </button>
  );
}
