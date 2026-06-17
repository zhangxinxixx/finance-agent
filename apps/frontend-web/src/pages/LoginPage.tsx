import { useState, type FormEvent } from "react";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [focused, setFocused] = useState<string | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    // TODO: 接入认证 API
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#050b13]">
      {/* ── ambient glow ── */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-1/3 h-[520px] w-[520px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(59,130,246,0.10)_0%,transparent_70%)]" />
        <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#16233b] to-transparent" />
      </div>

      {/* ── card ── */}
      <div className="relative z-10 w-full max-w-[380px] px-5">
        {/* brand */}
        <div className="mb-10 text-center">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-[#1c3357] bg-[linear-gradient(135deg,#0e1a2a,#0a1422)] shadow-[0_0_24px_rgba(59,130,246,0.08)]">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <rect x="2" y="2" width="7" height="7" rx="1.5" fill="#3b82f6" opacity="0.9" />
              <rect x="11" y="2" width="7" height="7" rx="1.5" fill="#3b82f6" opacity="0.45" />
              <rect x="2" y="11" width="7" height="7" rx="1.5" fill="#3b82f6" opacity="0.45" />
              <rect x="11" y="11" width="7" height="7" rx="1.5" fill="#3b82f6" opacity="0.2" />
            </svg>
          </div>
          <h1 className="text-[15px] font-semibold tracking-wide text-[#edf3ff]">
            金融分析中台
          </h1>
          <p className="mt-1 text-[11px] tracking-[0.08em] text-[#587093]">
            FinAnalytics · Secure Access
          </p>
        </div>

        {/* form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* email */}
          <div className="space-y-1.5">
            <label
              htmlFor="login-email"
              className="block text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[#7f94b7]"
            >
              邮箱
            </label>
            <div
              className={`flex items-center rounded-md border bg-[#0a1422] px-3 py-2.5 transition-colors duration-200 ${
                focused === "email"
                  ? "border-[#3b82f6]/50 shadow-[0_0_0_1px_rgba(59,130,246,0.15)]"
                  : "border-[#16233b] hover:border-[#21304c]"
              }`}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 16 16"
                fill="none"
                className="mr-2.5 flex-shrink-0 text-[#587093]"
              >
                <path
                  d="M2 4.5l6 4 6-4"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <rect
                  x="1.5"
                  y="3"
                  width="13"
                  height="10"
                  rx="2"
                  stroke="currentColor"
                  strokeWidth="1.4"
                />
              </svg>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={() => setFocused("email")}
                onBlur={() => setFocused(null)}
                placeholder="name@example.com"
                autoComplete="email"
                required
                className="w-full bg-transparent text-[13px] text-[#edf3ff] outline-none placeholder:text-[#3d5275]"
              />
            </div>
          </div>

          {/* password */}
          <div className="space-y-1.5">
            <label
              htmlFor="login-password"
              className="block text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[#7f94b7]"
            >
              密码
            </label>
            <div
              className={`flex items-center rounded-md border bg-[#0a1422] px-3 py-2.5 transition-colors duration-200 ${
                focused === "password"
                  ? "border-[#3b82f6]/50 shadow-[0_0_0_1px_rgba(59,130,246,0.15)]"
                  : "border-[#16233b] hover:border-[#21304c]"
              }`}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 16 16"
                fill="none"
                className="mr-2.5 flex-shrink-0 text-[#587093]"
              >
                <rect
                  x="3"
                  y="7"
                  width="10"
                  height="7"
                  rx="1.5"
                  stroke="currentColor"
                  strokeWidth="1.4"
                />
                <path
                  d="M5.5 7V5a2.5 2.5 0 015 0v2"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                />
              </svg>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setFocused("password")}
                onBlur={() => setFocused(null)}
                placeholder="输入密码"
                autoComplete="current-password"
                required
                className="w-full bg-transparent text-[13px] text-[#edf3ff] outline-none placeholder:text-[#3d5275]"
              />
            </div>
          </div>

          {/* submit */}
          <button
            type="submit"
            className="group mt-2 w-full rounded-md bg-[linear-gradient(180deg,#2563eb_0%,#1d4ed8_100%)] px-4 py-2.5 text-[12.5px] font-semibold tracking-[0.04em] text-white shadow-[0_1px_2px_rgba(0,0,0,0.3),inset_0_1px_0_rgba(255,255,255,0.08)] transition-all duration-200 hover:shadow-[0_0_20px_rgba(59,130,246,0.25),0_1px_2px_rgba(0,0,0,0.3)] hover:brightness-110 active:scale-[0.98] active:brightness-95"
          >
            登 录
          </button>
        </form>

        {/* footer */}
        <p className="mt-8 text-center text-[10px] tracking-wide text-[#3d5275]">
          仅限授权人员访问 · 系统操作将被审计记录
        </p>
      </div>
    </div>
  );
}
