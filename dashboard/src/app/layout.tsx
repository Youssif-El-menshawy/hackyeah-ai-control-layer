import type { Metadata } from "next";
import Script from "next/script";
import "./styles.css";
import { ConsoleNav } from "@/components/ConsoleNav";
import { OperatorSession } from "@/components/OperatorSession";

export const metadata: Metadata = {
  title: "AI Control Layer",
  description: "HackYeah policy and decision operations dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body><Script id="theme-init" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: `try { const saved = localStorage.getItem("control-layer-theme"); document.documentElement.dataset.theme = saved === "light" || saved === "dark" ? saved : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); } catch { document.documentElement.dataset.theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }` }} /><OperatorSession><ConsoleNav />{children}</OperatorSession></body>
    </html>
  );
}
