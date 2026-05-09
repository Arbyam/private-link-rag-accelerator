import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Private RAG Accelerator",
  description: "Enterprise document chat with private Azure services",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
