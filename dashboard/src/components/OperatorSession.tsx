"use client";

import { createContext, useContext, useState } from "react";

const Session = createContext<{ key: string; setKey: (key: string) => void } | null>(null);

export function OperatorSession({ children }: { children: React.ReactNode }) {
  const [key, setKey] = useState("");
  return <Session.Provider value={{ key, setKey }}>{children}</Session.Provider>;
}

export function useOperatorSession() {
  const session = useContext(Session);
  if (!session) throw new Error("Operator session provider is unavailable");
  return session;
}
