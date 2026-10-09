import React, { useEffect, useState } from "react";
import Layout from "../Layout";

async function api(path, body) {
  const res = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const raw = await res.text();
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; }
  catch { throw new Error("Сервер вернул страницу вместо ответа. Проверь, что Django запущен и nginx проксирует /api/ на порт 8000."); }
  if (!res.ok) throw new Error(data.error || "Ошибка");
  return data;
}

function Chart({ points }) {
  if (!points?.length) return <p className="muted">График появится после первого захода в кабинет с активной подпиской.</p>;
  const max = Math.max(...points.map(point => point.used), 1);
  const width = 520;
  const height = 180;
  const step = points.length === 1 ? width : width / (points.length - 1);
  const line = points.map((point, index) => `${index * step},${height - (point.used / max) * (height - 20)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart" role="img" aria-label="Потребление трафика">
      <polyline fill="none" stroke="#1d4ed8" strokeWidth="4" points={line} />
      {points.map((point, index) => <text key={point.when} x={index * step} y={height - 2} fontSize="11">{point.when.slice(0, 5)}</text>)}
    </svg>
  );
}

export default function Cabinet() {
  const [me, setMe] = useState(null);
  const [provider, setProvider] = useState("");
  const [amount, setAmount] = useState(150);
  const [promo, setPromo] = useState("");
  const [pay, setPay] = useState(null);
  const [error, setError] = useState("");
  async function load() { setMe(await api("/api/me")); }
  useEffect(() => { load().catch(() => setMe(null)); }, []);
  useEffect(() => {
    if (me) return;
    fetch("/api/telegram").then(res => res.json()).then(data => {
      const box = document.getElementById("tg-login");
      if (!box || !data.bot || box.dataset.ready) return;
      box.dataset.ready = "1";
      const script = document.createElement("script");
      script.src = "https://telegram.org/js/telegram-widget.js?22";
      script.async = true;
      script.setAttribute("data-telegram-login", data.bot);
      script.setAttribute("data-size", "large");
      script.setAttribute("data-auth-url", window.location.origin + "/auth/telegram");
      script.setAttribute("data-request-access", "write");
      box.appendChild(script);
    }).catch(e => setError(e.message));
  }, [me]);

  if (!me) return (
    <Layout>
      <main className="shell hero">
        <h1>Вход</h1>
        <p className="muted">Войдите через Telegram. Логин и пароль сайта больше не используются.</p>
        <article className="card" style={{maxWidth:460}}>
          <div id="tg-login" />
          {error && <p>{error}</p>}
        </article>
      </main>
    </Layout>
  );

  return (
    <Layout authed admin={me.admin}>
      <main className="shell" style={{padding:"28px 0 48px"}}>
        <div className="split">
          <article className="card dark">
            <p className="muted">Профиль</p>
            <h2>{me.balance} ₽</h2>
            <p className="muted">Telegram ID {me.tg_id} · ID в боте {me.bot_id}</p>
            <div className="row"><input style={{maxWidth:160}} type="number" value={amount} onChange={e => setAmount(e.target.value)} /></div>
            <div className="row" style={{marginTop:10}}>{me.providers.map(item => <button key={item.code} className={provider===item.code ? "" : "ghost"} onClick={() => setProvider(item.code)}>{item.title}</button>)}</div>
            <button className="green" onClick={async () => setPay(await api("/api/topup", {amount:Number(amount), provider}))}>Пополнить</button>
            {pay && <p><a href={pay.pay_url}>Оплатить</a> <button onClick={async () => alert((await api("/api/check", {order_id:pay.order_id})).message)}>Проверить</button></p>}
          </article>
          <article className="card" id="subscription">
            <p className="muted">Подписка</p>
            {me.subscription ? <><p>Осталось: {me.subscription.left}<br/>Окончание: {me.subscription.until}<br/>Трафик: {me.subscription.traffic}</p><a href={me.subscription.url}>Подключиться</a><br/><img className="qr" src={me.subscription.qr} alt="QR" /></> : <p>Подписки нет. Выберите тариф или пробный день.</p>}
            <div className="row" style={{marginTop:12}}>{me.plans.map(plan => <button key={plan.days} onClick={() => api("/api/buy", {days:plan.days}).then(load).catch(e => setError(e.message))}>{plan.days} дн. · {plan.price} ₽</button>)}{me.trial && <button className="green" onClick={() => api("/api/trial", {}).then(load)}>Пробный {me.trial_days} дн.</button>}</div>
            <div className="row" style={{marginTop:12}}><input value={promo} onChange={e => setPromo(e.target.value)} placeholder="Промокод" /><button className="blue" onClick={() => api("/api/promo", {code:promo}).then(load).catch(e => setError(e.message))}>Активировать</button></div>
            {error && <p>{error}</p>}
          </article>
        </div>
        <article className="card" style={{marginTop:14}}>
          <h2>Потребление трафика</h2>
          <Chart points={me.traffic} />
        </article>
        <article className="card" id="history" style={{marginTop:14}}>
          <h2>История</h2>
          {me.history.length ? <table>{me.history.map((row, i) => <tr key={i}><td>{row.when}</td><td>{row.title}</td><td>{row.amount} ₽</td><td>{row.status}</td></tr>)}</table> : <p className="muted">Пока пусто.</p>}
        </article>
      </main>
    </Layout>
  );
}
