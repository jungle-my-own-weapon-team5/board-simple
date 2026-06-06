import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuthStore } from "./stores/authStore";
import LoginPage from "./pages/LoginPage";
import PostDetailPage from "./pages/PostDetailPage";
import PostEditorPage from "./pages/PostEditorPage";
import PostListPage from "./pages/PostListPage";
import RegisterPage from "./pages/RegisterPage";

export default function App() {
  const { bootstrap, isLoading } = useAuthStore();

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  if (isLoading) {
    return <div className="boot">Loading...</div>;
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<PostListPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/posts/new" element={<PostEditorPage />} />
        <Route path="/posts/:postId" element={<PostDetailPage />} />
        <Route path="/posts/:postId/edit" element={<PostEditorPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
