    async def enabled_inbound_ids(self) -> list[int]:
        ids: list[int] = []
        for item in await self.list_inbounds():
            protocol = str(item.get("protocol") or "").lower()
            if protocol == "mtproto":
                continue
            if item.get("enable") is False:
                continue
            inbound_id = item.get("id")
            if inbound_id is None:
                continue
            ids.append(int(inbound_id))
        if not ids:
            raise PanelError("нет включённых инбаундов кроме mtproto")
        return ids

    async def add_client(
