async def main() -> None:
    from aiohttp import web

    from pay_return import add_routes

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    await store.init()
    app = web.Application()
    add_routes(app, store, pays, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(env("WEBAPP_PORT", "8080") or 8080)
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("bot started, inbounds=%s, return page=%s", INBOUND_IDS, port)
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await panel.close()
        await pays.close()
        await bot.session.close()
