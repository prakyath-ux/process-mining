"use client";

/** Authenticated app shell: sidebar navigation + session guard. */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearSession, getUser, type SessionUser } from "@/lib/api";

const NAV = [
  { href: "/logs", label: "Event Logs", icon: "▤" },
  { href: "/ingest", label: "Ingest Data", icon: "⇪" },
  { href: "/audit", label: "Audit Trail", icon: "⌾", adminOnly: true },
];

export default function Shell({
  children,
  title,
  subtitle,
  actions,
}: {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      router.replace("/login");
      return;
    }
    setUser(u);
    setReady(true);
  }, [router]);

  if (!ready) {
    return <div className="loading">Loading…</div>;
  }

  const isAdmin = user?.role === "admin";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo" /> ProMine
        </div>
        {NAV.filter((n) => !n.adminOnly || isAdmin).map((n) => {
          const active = pathname === n.href || pathname.startsWith(`${n.href}/`);
          return (
            <Link key={n.href} href={n.href} className={`nav${active ? " active" : ""}`}>
              {n.icon}  {n.label}
            </Link>
          );
        })}
        <div className="spacer" />
        <div className="userbox">
          <div className="email">{user?.email}</div>
          <div style={{ marginTop: 4, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>role: {user?.role}</span>
            <button
              className="btn sm secondary"
              onClick={() => {
                clearSession();
                router.replace("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        {title && (
          <div className="page-head">
            <div>
              <h1>{title}</h1>
              {subtitle && <div className="sub">{subtitle}</div>}
            </div>
            {actions && <div className="row">{actions}</div>}
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
