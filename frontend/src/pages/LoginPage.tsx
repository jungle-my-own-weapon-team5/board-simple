import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await login(email, password);
      const next = (location.state as { next?: string } | null)?.next ?? "/";
      navigate(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "로그인에 실패했습니다.");
    }
  };

  return (
    <section className="narrow-panel">
      <h1>Login</h1>
      <form className="stack" onSubmit={handleSubmit}>
        <label className="field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error ? <p className="error">{error}</p> : null}
        <button className="primary-button" type="submit">
          Login
        </button>
      </form>
      <p className="muted">
        계정이 없으면 <Link to="/register">회원가입</Link>
      </p>
    </section>
  );
}
