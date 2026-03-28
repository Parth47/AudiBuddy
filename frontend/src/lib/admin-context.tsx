"use client";

import { createContext, useContext, useEffect, useState } from "react";

interface AdminContextValue {
  isAdmin: boolean;
  loading: boolean;
}

const AdminContext = createContext<AdminContextValue>({
  isAdmin: false,
  loading: true,
});

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function AdminProvider({ children }: { children: React.ReactNode }) {
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await fetch(`${API_URL}/api/admin/status`, {
          cache: "no-store",
        });
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setIsAdmin(Boolean(data.admin));
        }
      } catch {
        // Backend unreachable — default to non-admin (safe)
        if (!cancelled) setIsAdmin(false);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void check();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AdminContext.Provider value={{ isAdmin, loading }}>
      {children}
    </AdminContext.Provider>
  );
}

export function useAdmin(): AdminContextValue {
  return useContext(AdminContext);
}
