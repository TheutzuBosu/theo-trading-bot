import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Theo Trading Bot · Dashboard",
  description: "Jurnal și stare pentru Theo Trading Bot (Faza B, Alpaca Paper)",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ro">
      <body>{children}</body>
    </html>
  );
}
