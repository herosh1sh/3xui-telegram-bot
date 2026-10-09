import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

async function api(path, body) {
  const res = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Ошибка");
  return data;
}

export default function Cabinet() {
  const [me, setMe] = useState(null);
  const [provider, setProvider] = useState("");
  const [amount, setAmount] = useState(150);
  const [promo, setPromo] = useState("");
  const [pay, setPay] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setMe(await api("/api/me"));
  }
  useEffect(() => { load().catch(() => setMe(null)); }, []);

  if (!me) return (
    <main className="shell hero">
      <h1>Вход</h1>
      <p className="muted">В боте нажмите «Кабинет». Бот пришлёт одноразовую ссылку, она откроет этот кабинет.</p>
    </main>
  );

  return (
    <>
      <header className="shell top"><Link className="logo" to="/">HeroshishVPN</Link>{me.admin && <Link className="btn" to="/admin">Админка</Link>}</header>
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
          <article className="card">
            <p className="muted">Подписка</p>
            {me.subscription ? <><p>Осталось: {me.subscription.left}<br/>Окончание: {me.subscription.until}<br/>Трафик: {me.subscription.traffic}</p><a href={me.subscription.url}>Подключиться</a><br/><img className="qr" src={me.subscription.qr} alt="QR" /></> : <p>Подписки нет. Выберите тариф или пробный день.</p>}
            <div className="row" style={{marginTop:12}}>{me.plans.map(plan => <button key={plan.days} onClick={() => api("/api/buy", {days:plan.days}).then(load).catch(e => setError(e.message))}>{plan.days} дн. · {plan.price} ₽</button>)}{me.trial && <button className="green" onClick={() => api("/api/trial", {}).then(load)}>Пробный {me.trial_days} дн.</button>}</div>
            <div className="row" style={{marginTop:12}}><input value={promo} onChange={e => setPromo(e.target.value)} placeholder="Промокод" /><button className="blue" onClick={() => api("/api/promo", {code:promo}).then(load).catch(e => setError(e.message))}>Активировать</button></div>
            {error && <p>{error}</p>}
          </article>
        </div>
        <article className="card" style={{marginTop:14}}>
          <h2>История</h2>
          {me.history.length ? <table>{me.history.map((row, i) => <tr key={i}><td>{row.when}</td><td>{row.title}</td><td>{row.amount} ₽</td><td>{row.status}</td></tr>)}</table> : <p className="muted">Пока пусто.</p>}
        </article>
      </main>
    </>
  );
}
