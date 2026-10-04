"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function ConsoleNav() {
  const path = usePathname();
  function toggleTheme() {
    const root = document.documentElement;
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("control-layer-theme", next); } catch { /* Theme still changes for this visit. */ }
  }
  return <nav className="console-nav" aria-label="Main navigation">
    <Link href="/" className="brand"><span className="brand-mark" aria-hidden="true">◇</span><span>Control Layer<small>AI SECURITY OPERATIONS</small></span></Link>
    <div className="nav-links"><Link href="/" aria-current={path === "/" ? "page" : undefined}>Overview</Link><Link href="/benchmark" aria-current={path === "/benchmark" ? "page" : undefined}>Benchmark</Link></div>
    <span className="nav-tag">HackYeah · V1</span>
    <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Toggle light and dark mode" title="Switch color theme"><span className="theme-switch-light" aria-hidden="true">☀ Light</span><span className="theme-switch-dark" aria-hidden="true">☾ Dark</span></button>
  </nav>;
}
