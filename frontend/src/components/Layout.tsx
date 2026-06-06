import { LogIn, LogOut, PenLine, UserPlus } from "lucide-react";
import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";

export default function Layout() {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand">
          Board Simple
        </Link>
        <nav className="nav-actions">
          {user ? (
            <>
              <span className="user-chip">{user.nickname}</span>
              <Link to="/posts/new" className="icon-button" title="Write post">
                <PenLine size={18} />
                <span>Write</span>
              </Link>
              <button type="button" className="icon-button" onClick={handleLogout}>
                <LogOut size={18} />
                <span>Logout</span>
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="icon-button">
                <LogIn size={18} />
                <span>Login</span>
              </Link>
              <Link to="/register" className="icon-button">
                <UserPlus size={18} />
                <span>Register</span>
              </Link>
            </>
          )}
        </nav>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}
