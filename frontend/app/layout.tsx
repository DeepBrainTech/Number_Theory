import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "数论 Agent",
  description: "正确性优先的数论学习与研究助手",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
