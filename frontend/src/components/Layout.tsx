import { NavLink, Link } from "react-router-dom";
import { IS_MOCK } from "@/api/client";
import type { ReactNode } from "react";

const navItems = [
  { to: "/", label: "Swamp", end: true },
  { to: "/customers", label: "Customers" },
  { to: "/review", label: "Review" },
];

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-20 border-b border-swamp-200/60 bg-white/80 backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3 group">
            <span className="h-9 w-9 rounded-xl bg-gradient-to-br from-swamp-700 to-swamp-500 grid place-items-center text-gold-300 text-lg shadow-card">
              {"🦆"}
            </span>
            <div className="leading-tight">
              <div className="font-semibold tracking-tight text-swamp-900">Fabrikam SCV</div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-swamp-500">Single Customer View</div>
            </div>
          </Link>
          <nav className="flex items-center gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  [
                    "px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                    isActive
                      ? "bg-swamp-900 text-gold-200"
                      : "text-swamp-700 hover:bg-swamp-100",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto p-6">{children}</main>

      <footer className="border-t border-swamp-200/60 bg-white/60">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between text-xs text-swamp-600">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                IS_MOCK ? "bg-gold-500" : "bg-emerald-500"
              }`}
            />
            <span>
              {IS_MOCK ? "Mock data (VITE_MOCK=1)" : "Live API (/api proxied to :8000)"}
            </span>
          </div>
          <div>Scenario 3 · seven systems, one truth</div>
        </div>
      </footer>
    </div>
  );
}
