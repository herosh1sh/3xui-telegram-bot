import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

async function api(path, body) {
  const res = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Ошибка");
  return data;
}

export default function Admin() {
  const [data, setData] = useState(null);
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ q:"", tg:"", sum:"", days:"", code:"авто", kind:"balance", value:"100", uses:"1", text:"" });
  const [note, setNote] = useState("");
  const set = (key, value) => setForm({...form, [key]: value});

  useEffect(() => { api("/api/admin/overview").then(setData).catch(e => setNote(e.message)); }, []);
  if (!data) return <main className="shell hero"><h1>{note || "Загрузка"}</h1></main>;

  return (
    <>
      <header className="shell top"><Link className="logo" to="/cabinet">HeroshishVPN</Link><Link className="btn ghost" to="/cabinet">Кабинет</Link></header>
      <main className="shell" style={{padding:"28px 0 48px"}}>
        <h1>Админка</h1>
        <section className="grid">{data.stats.map(item => <article className="card" key={item.label}><h2>{item.value}</h2><p className="muted">{item.label}</p></article>)}</section>
        <div className="split" style={{marginTop:14}}>
          <article className="card">
            <h2>Найти пользователя</h2>
            <div className="row"><input placeholder="Telegram ID или @username" value={form.q} onChange={e => set("q", e.target.value)} /><button onClick={() => api("/api/admin/users?q=" + encodeURIComponent(form.q)).then(d => setUsers(d.users))}>Найти</button></div>
            {users.map(user => <p key={user.tg_id}>{user.tg_id} @{user.username || "—"} · {user.balance} ₽ · {user.sub}</p>)}
          </article>
          <article className="card">
            <h2>Выдача</h2>
            <input placeholder="Telegram ID" value={form.tg} onChange={e => set("tg", e.target.value)} />
            <div className="row" style={{marginTop:8}}><input placeholder="Баланс, ₽" value={form.sum} onChange={e => set("sum", e.target.value)} /><button className="green" onClick={() => api("/api/admin/balance", {tg_id:Number(form.tg), amount:Number(form.sum)}).then(d => setNote(`Баланс: ${d.balance} ₽`))}>Выдать баланс</button></div>
            <div className="row" style={{marginTop:8}}><input placeholder="Дней" value={form.days} onChange={e => set("days", e.target.value)} /><button className="blue" onClick={() => api("/api/admin/sub", {tg_id:Number(form.tg), days:Number(form.days)}).then(() => setNote("Подписка выдана"))}>Выдать подписку</button></div>
          </article>
        </div>
        <div className="split" style={{marginTop:14}}>
          <article className="card">
            <h2>Промокод</h2>
            <input value={form.code} onChange={e => set("code", e.target.value)} />
            <div className="row" style={{marginTop:8}}>
              <select value={form.kind} onChange={e => set("kind", e.target.value)}><option value="balance">Баланс, ₽</option><option value="days">Дни</option></select>
              <input value={form.value} onChange={e => set("value", e.target.value)} />
              <input value={form.uses} onChange={e => set("uses", e.target.value)} />
              <button onClick={() => api("/api/admin/promo", {code:form.code, kind:form.kind, value:Number(form.value), uses:Number(form.uses)}).then(d => setNote(`Код ${d.code}`))}>Создать</button>
            </div>
          </article>
          <article className="card">
            <h2>Оповещение</h2>
            <textarea value={form.text} onChange={e => set("text", e.target.value)} placeholder="Текст всем пользователям" />
            <button className="red" onClick={() => api("/api/admin/announce", {text:form.text}).then(d => setNote(`Доставлено: ${d.sent}. Не дошло: ${d.failed}.`))}>Отправить</button>
          </article>
        </div>
        {note && <p>{note}</p>}
        <article className="card" style={{marginTop:14}}>
          <h2>Последние платежи</h2>
          <table>{data.orders.map((order, i) => <tr key={i}><td>{order.when}</td><td>{order.tg_id}</td><td>{order.provider}</td><td>{order.amount} ₽</td><td>{order.status}</td></tr>)}</table>
        </article>
      </main>
    </>
  );
}
