import React from "react";
import Layout from "../Layout";

export default function Home() {
  return (
    <Layout>
      <main className="shell hero">
        <p className="muted">VPN в Telegram и на сайте</p>
        <h1>Подписка, которую можно открыть из чата.</h1>
        <p className="muted" style={{maxWidth:560}}>HeroshishVPN выдаёт доступ через бота и личный кабинет: баланс, тариф, ссылка и QR. Пробный день один раз и без оплаты, дальше — 30, 90 или 180 дней.</p>
        <p className="row"><a className="btn" href="/cabinet">Открыть кабинет</a><a className="btn ghost" href="https://t.me/Heroshish">Канал</a></p>
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
