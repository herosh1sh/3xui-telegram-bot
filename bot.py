async def issue(tg_id: int, username: str | None, days: int) -> tuple[str, str]:
    email = f"tg{tg_id}"
    existing = await store.get(tg_id)
    now_ms = int(time.time() * 1000)
    base = existing["expiry_ms"] if existing and existing["expiry_ms"] > now_ms else now_ms
    expiry_ms = base + days * 86400 * 1000
    total_bytes = gb_to_bytes(TRAFFIC_GB)
    inbound_ids = await panel.enabled_inbound_ids()
    if existing:
        await panel.extend_client(email, expiry_ms, total_bytes)
        sub_id = existing["sub_id"]
        try:
            await panel.add_client(
                email=email,
                inbound_ids=inbound_ids,
                tg_id=tg_id,
                sub_id=sub_id,
                total_bytes=total_bytes,
                expiry_ms=expiry_ms,
                limit_ip=LIMIT_IP,
                flow=FLOW,
                comment=f"telegram:{username or tg_id}",
            )
        except PanelError:
            log.info("client %s already attached to inbounds", email)
    else:
        sub_id = secrets.token_hex(8)
        await panel.add_client(
            email=email,
            inbound_ids=inbound_ids,
            tg_id=tg_id,
            sub_id=sub_id,
            total_bytes=total_bytes,
            expiry_ms=expiry_ms,
            limit_ip=LIMIT_IP,
            flow=FLOW,
            comment=f"telegram:{username or tg_id}",
        )
        created = await panel.get_client(email)
        if created and created.get("subId"):
            sub_id = str(created["subId"])
    await store.save(tg_id, username, email, sub_id, expiry_ms)
    links = await panel.client_links(email)
    return format_card(email, sub_id, expiry_ms, links), sub_id
