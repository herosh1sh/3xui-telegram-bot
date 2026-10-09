import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

export default function Layout({ authed, children }) {
  const [loginUrl, setLoginUrl] = useState("");

  useEffect(() => {
    if (authed) return;
    fetch("/api/telegram").then(res => res.json()).then(data => {
      if (!data.bot_id) return;
      const origin = window.location.origin;
      const back = encodeURIComponent(origin + "/auth/telegram");
      setLoginUrl(`https://oauth.telegram.org/auth?bot_id=${data.bot_id}&origin=${encodeURIComponent(origin)}&return_to=${back}&request_access=write`);
    }).catch(() => {});
  }, [authed]);

  return (
    <>
      <header className="shell top">
        <Link className="logo" to={authed ? "/cabinet" : "/"}>HeroshishVPN</Link>
        {authed ? <Link to="/cabinet">Кабинет</Link> : <a className="btn" href={loginUrl || "#"}>Войти через Telegram</a>}
      </header>
      {children}
    </>
  );
}
