import { useState, type FormEvent } from "react";
import { api, ApiError, type User } from "../api";
import { Logo } from "../components/Logo";

interface Props {
  onLoggedIn: (user: User) => void;
}

export function LoginPage({ onLoggedIn }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      onLoggedIn(await api.login(username.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Giriş yapılamadı.");
      setBusy(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand">
          <Logo />
          <span>Bayi Sipariş Portalı</span>
        </div>
        <h1 id="login-title">Bayi girişi</h1>
        <p className="muted">Sipariş vermek için bayi hesabınızla giriş yapın.</p>
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="login-username">Kullanıcı adı</label>
            <input
              id="login-username"
              data-testid="login-username"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="login-password">Parola</label>
            <input
              id="login-password"
              data-testid="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && (
            <p className="alert alert-error" role="alert" data-testid="login-error">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="btn btn-primary btn-block"
            data-testid="login-submit"
            disabled={busy || !username || !password}
          >
            {busy ? "Giriş yapılıyor…" : "Giriş yap"}
          </button>
        </form>
      </section>
    </main>
  );
}
