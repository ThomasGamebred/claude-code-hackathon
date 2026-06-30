import type { ReactNode } from "react";

interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export default function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
}: CardProps) {
  return (
    <section
      className={`rounded-2xl border border-swamp-200/70 bg-white shadow-card p-5 ${className}`}
    >
      {(title || subtitle || action) && (
        <header className="flex items-start justify-between gap-3 mb-4">
          <div>
            {title && (
              <h2 className="text-base font-semibold tracking-tight text-swamp-900">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="text-xs text-swamp-600 mt-0.5">{subtitle}</p>
            )}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
