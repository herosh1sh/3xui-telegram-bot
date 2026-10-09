import React, { useEffect, useState } from "react";
import Layout from "../Layout";

export default function Home() {
  const [plans, setPlans] = useState([]);
  const [authed, setAuthed] = useState(false);
  const [loginUrl, setLoginUrl] = useState("");

  useEffect(() => {
    fetch("/api/plans").then(res => res.json()).then(data => setPlans(data.plans || [])).catch(() => {});
    fetch("/api/me").then(res => setAuthed(res.ok)).catch(() => setAuthed(false));
    fetch("/api/telegram").then(res => res.json()).then(data => {
      if (!data.bot_id) return;
      const origin = window.location.origin;
      const back = encodeURIComponent(origin + "/auth/telegram");
      setLoginUrl(`https://oauth.telegram.org/auth?bot_id=${data.bot_id}&origin=${encodeURIComponent(origin)}&return_to=${back}&request_access=write`);
    }).catch(() => {});
  }, []);

  function choose(days) {
    if (!authed) {
      window.location.href = loginUrl || "/cabinet";
      return;
    }
    window.location.href = "/cabinet#subscription";
  }

  return (
    <Layout authed={authed}>
      <main className="shell hero">
        <p className="muted">VPN в Telegram и на сайте</p>
        <h1>Подписка, которую можно открыть из чата.</h1>
        <p className="muted" style={{maxWidth:560}}>HeroshishVPN выдаёт доступ через бота и личный кабинет: баланс, тариф, ссылка и QR. Пробный день один раз и без оплаты, дальше — 30, 90 или 180 дней.</p>
        <p className="row"><a className="btn ghost" href="https://t.me/Heroshish">Канал</a></p>
        <section className="plans">
          {plans.map(plan => (
            <article className="card" key={plan.days}>
              <p className="muted">{plan.days} дней</p>
              <strong>{plan.price} ₽</strong>
              <p><button onClick={() => choose(plan.days)}>Выбрать</button></p>
            </article>
          ))}
        </section>
        <section className="grid">
          <article className="card"><h2>Профиль</h2><p className="muted">Баланс, Telegram ID, внутренний ID и история пополнений с покупками: дата, сумма и статус.</p></article>
          <article className="card"><h2>Подписка</h2><p className="muted">Если доступ уже есть, кабинет показывает срок, дату окончания и трафик. Если нет — предлагает тарифы.</p></article>
          <article className="card"><h2>Оплата</h2><p className="muted">Баланс пополняется теми же системами, что в боте. После оплаты можно проверить платёж.</p></article>
        </section>
      </main>
      <footer className="shell"><a href="https://telegra.ph/Politika-konfidencialnosti-HeroshishVPN-10-08">Политика</a> · <a href="https://telegra.ph/Publichnaya-oferta-na-uslugi-HeroshishVPN-10-08">Оферта</a> · <a href="https://t.me/Heroshish">Канал</a></footer>
    </Layout>
  );
}
