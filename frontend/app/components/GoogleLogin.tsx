"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, type AuthUser } from "../lib/api";

type GoogleCredentialResponse = { credential: string };

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: { theme: string; size: string; text: string; width: number },
          ) => void;
        };
      };
    };
  }
}

type Props = {
  onSignedIn: (user: AuthUser) => void;
};

export default function GoogleLogin({ onSignedIn }: Props) {
  const onSignedInRef = useRef(onSignedIn);
  onSignedInRef.current = onSignedIn;
  const buttonRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

  useEffect(() => {
    // Drop the pre-auth anonymous browser id; chats now live only on the signed-in account.
    try {
      window.localStorage.removeItem("nt_client_id");
    } catch {
      /* ignore quota / private-mode errors */
    }
  }, []);

  useEffect(() => {
    if (!clientId || !buttonRef.current) return;
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      if (!window.google || !buttonRef.current) return;
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async (response) => {
          setError("");
          try {
            const result = await apiFetch("/api/auth/google", {
              method: "POST",
              body: JSON.stringify({
                id_token: response.credential,
              }),
            });
            if (!result.ok) {
              const body = await result.json().catch(() => ({}));
              throw new Error(body.detail || "Google sign-in failed");
            }
            onSignedInRef.current((await result.json()) as AuthUser);
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : "Google sign-in failed");
          }
        },
      });
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: "outline",
        size: "large",
        text: "continue_with",
        width: 280,
      });
    };
    document.body.appendChild(script);
    return () => {
      script.remove();
    };
  }, [clientId]);

  return (
    <main className="loginScreen">
      <section className="loginCard">
        <p className="loginEyebrow">PROOF LAB</p>
        <h1>Sign in to keep your chats</h1>
        <p className="loginCopy">
          A correctness-first math proving workbench. Conversations, memories, and notebook entries
          stay with your Google account across browsers.
        </p>
        {clientId ? (
          <div className="loginButton" ref={buttonRef} />
        ) : (
          <p className="error">
            Google login is not configured. Set <code>GOOGLE_CLIENT_ID</code> and{" "}
            <code>NEXT_PUBLIC_GOOGLE_CLIENT_ID</code>.
          </p>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </main>
  );
}
