import React, { useState } from "react";
import { Link } from "react-router-dom";

export default function Layout({ authed, admin, children }) {
  const [open, setOpen] = useState(false);
  const items = [
    ["Главная", "/"],
    ["Кабинет", "/cabinet"],
    ["Подписка", "/cabinet#subscription"],
    ["История", "/cabinet#history"],
  ];
  if (admin) items.push(["Админка", "/admin"]);
  return (
    <>
      <header className="shell top">
        <button className="ghost" aria-label="Меню" onClick={() => setOpen(true)}>☰</button>
        <Link className="logo" to={authed ? "/cabinet" : "/"}>HeroshishVPN</Link>
        <span />
      </header>
      {open && <button className="backdrop" onClick={() => setOpen(false)} />}
      <aside className={open ? "drawer open" : "drawer"}>
        <p className="muted">HeroshishVPN</p>
        {items.map(([title, href]) => <Link key={title} to={href} onClick={() => setOpen(false)}>{title}</Link>)}
      </aside>
      {children}
    </>
  );
}
