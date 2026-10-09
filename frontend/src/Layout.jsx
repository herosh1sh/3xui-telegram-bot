import React, { useEffect } from "react";
import { Link } from "react-router-dom";

export default function Layout({ authed, children }) {
  useEffect(() => {
    if (authed) return;
    fetch("/api/telegram").then(res => res.json()).then(data => {
      const box = document.getElementById("tg-login");
      if (!box || !data.bot || box.dataset.ready) return;
      box.dataset.ready = "1";
      const script = document.createElement("script");
      script.src = "https://telegram.org/js/telegram-widget.js?22";
      script.async = true;
      script.setAttribute("data-telegram-login", data.bot);
      script.setAttribute("data-size", "medium");
      script.setAttribute("data-auth-url", window.location.origin + "/auth/telegram");
      script.setAttribute("data-request-access", "write");
      box.appendChild(script);
    }).catch(() => {});
  }, [authed]);

  return (
    <>
      <header className="shell top">
        <Link className="logo" to={authed ? "/cabinet" : "/"}>HeroshishVPN</Link>
        {authed ? <Link to="/cabinet">Кабинет</Link> : <div id="tg-login" />}
      </header>
      {children}
    </>
  );
}
