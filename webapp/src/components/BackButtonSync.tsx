import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { tg } from "../lib/telegram";

export function BackButtonSync() {
  const location = useLocation();
  const navigate = useNavigate();
  const isRoot = location.pathname === "/";

  useEffect(() => {
    const bb = tg?.BackButton;
    if (!bb) return;
    const handler = () => navigate(-1);
    if (isRoot) {
      bb.hide();
    } else {
      bb.show();
      bb.onClick(handler);
    }
    return () => {
      bb.offClick(handler);
    };
  }, [isRoot, navigate]);

  return null;
}