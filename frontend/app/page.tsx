"use client";

import { FormEvent, useEffect, useState } from "react";

type Stats = {
  documents: number;
  chunks: number;
  page_start: number | null;
  page_end: number | null;
  block_types: Record<string, number>;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  verification?: string;
};

type ToolStatus = {
  openai: { configured: boolean; model: string };
  sage: { available: boolean; engine?: string };
  lean: { available: boolean; engine?: string };
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [tools, setTools] = useState<ToolStatus | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "第一章已经准备好。你可以询问整除、欧几里得算法、Bézout 引理、线性同余、中国剩余定理和素数分解。",
      verification: "system",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/library/stats`),
      fetch(`${API_BASE}/api/tools/status`),
    ])
      .then(async ([statsResponse, toolsResponse]) => {
        if (!statsResponse.ok || !toolsResponse.ok) throw new Error("系统状态读取失败");
        setStats(await statsResponse.json());
        setTools(await toolsResponse.json());
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const question = input.trim();
    if (!question || loading) return;

    setMessages((current) => [...current, { role: "user", content: question }]);
    setInput("");
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, limit: 5 }),
      });
      if (!response.ok) throw new Error("后端回答失败");
      const data = await response.json();
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.answer,
          verification: data.verification,
        },
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "未知错误");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">NUMBER THEORY</p>
          <h1>数论 Agent</h1>
          <p className="subtitle">正确性优先，从一章可靠知识开始。</p>
        </div>

        <section className="statusCard">
          <div className="statusHeading">
            <span className="statusDot" />
            知识库状态
          </div>
          <dl>
            <div>
              <dt>文档</dt>
              <dd>{stats?.documents ?? "—"}</dd>
            </div>
            <div>
              <dt>知识块</dt>
              <dd>{stats?.chunks ?? "—"}</dd>
            </div>
            <div>
              <dt>PDF 范围</dt>
              <dd>{stats?.page_start ? `${stats.page_start}–${stats.page_end}` : "—"}</dd>
            </div>
          </dl>
        </section>

        <section className="scope">
          <h2>验证能力</h2>
          <ul className="toolList">
            <li className={tools?.openai.configured ? "online" : "offline"}>
              OpenAI · {tools?.openai.configured ? tools.openai.model : "等待 API Key"}
            </li>
            <li className={tools?.sage.available ? "online" : "offline"}>SageMath 精确计算</li>
            <li className={tools?.lean.available ? "online" : "offline"}>Lean 4 + mathlib 证明检查</li>
          </ul>
        </section>

        <section className="scope">
          <h2>当前范围</h2>
          <p>Euclid&apos;s Algorithm · Chapter 1</p>
          <ul>
            <li>整除与最大公因数</li>
            <li>线性同余与中国剩余定理</li>
            <li>素数与唯一分解</li>
          </ul>
        </section>
      </aside>

      <section className="chatPanel">
        <header className="chatHeader">
          <div>
            <span className="chapterTag">HILL · CHAPTER 1</span>
            <h2>开始讨论数论</h2>
          </div>
          <span className="modeTag">
            {tools?.openai.configured ? "OPENAI · 工具增强" : "资料检索模式"}
          </span>
        </header>

        <div className="messages" aria-live="polite">
          {messages.map((message, index) => (
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              <div className="avatar">{message.role === "assistant" ? "N" : "你"}</div>
              <div className="bubble">
                <p>{message.content}</p>
                {message.role === "assistant" && message.verification && (
                  <span className="verification">
                    {message.verification === "retrieval_only"
                      ? "仅资料检索，未生成证明"
                      : message.verification === "lean_verified"
                        ? "Lean 4 已通过形式化检查"
                        : message.verification === "sage_verified"
                          ? "SageMath 已完成精确验算"
                      : message.verification === "model_unverified"
                        ? "模型回答，尚未形式化"
                        : "系统消息"}
                  </span>
                )}
              </div>
            </article>
          ))}
          {loading && <p className="thinking">正在检索第一章…</p>}
        </div>

        <div className="composerWrap">
          {error && <p className="error">{error}</p>}
          <form className="composer" onSubmit={submit}>
            <textarea
              aria-label="输入数论问题"
              onChange={(event) => setInput(event.target.value)}
              placeholder="例如：如何用欧几里得算法求最大公因数？"
              rows={2}
              value={input}
            />
            <button disabled={loading || !input.trim()} type="submit">
              提问
            </button>
          </form>
          <p className="notice">当前只检索第一章；Sage/Lean 标签仅表示对应计算或形式命题已通过工具检查。</p>
        </div>
      </section>
    </main>
  );
}
