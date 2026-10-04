import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "AI Control Layer",
  description: "HackYeah policy and decision operations dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

