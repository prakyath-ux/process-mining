import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Process Mining Platform",
  description: "Process mining for financial operations — discovery, bottlenecks, conformance",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
