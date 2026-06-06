import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";

export default function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await register(email, password, nickname);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "회원가입에 실패했습니다.");
    }
  };

  return (
    <section className="narrow-panel">
      <h1>Register</h1>
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
            minLength={8}
            required
          />
        </label>
        <label className="field">
          <span>Nickname</span>
          <input
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
            placeholder="비워두면 익명0000 형식으로 생성됩니다."
          />
        </label>
        {error ? <p className="error">{error}</p> : null}
        <button className="primary-button" type="submit">
          Register
        </button>
      </form>
      <p className="muted">
        이미 계정이 있으면 <Link to="/login">로그인</Link>
      </p>
    </section>
  );
}
