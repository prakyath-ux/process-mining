"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/logs");
  }, [router]);
  return <div className="loading">Redirecting…</div>;
}
