"""Клиент панели 3x-ui: токен или логин, новый API и запасной старый."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger("xui")


class PanelError(RuntimeError):
    pass


class XuiPanel:
    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        api_token: str = "",
        verify_ssl: bool = True,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.api_token = api_token.strip()
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._csrf: str | None = None
        self._logged_in = bool(self.api_token)

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                verify=self.verify_ssl,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ensure_auth(self) -> httpx.AsyncClient:
        http = await self.client()
        if self.api_token or self._logged_in:
            return http
        resp = await http.post(
            "/login",
            json={"username": self.username, "password": self.password},
        )
        data = _json(resp)
        if resp.status_code >= 400 or not data.get("success", False):
            raise PanelError(data.get("msg") or f"логин не удался: HTTP {resp.status_code}")
        self._logged_in = True
        await self._load_csrf(http)
        return http

    async def _load_csrf(self, http: httpx.AsyncClient) -> None:
        for path in ("/panel/api/csrf-token", "/csrf-token"):
            try:
                resp = await http.get(path)
                data = _json(resp)
            except (httpx.HTTPError, ValueError):
                continue
            token = data.get("obj")
            if isinstance(token, dict):
                token = token.get("token") or token.get("csrf")
            if isinstance(token, str) and token:
                self._csrf = token
                return

    def _headers(self, json_body: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self._csrf and not self.api_token:
            headers["X-CSRF-Token"] = self._csrf
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        http = await self._ensure_auth()
        headers = self._headers(json_body="json" in kwargs)
        headers.update(kwargs.pop("headers", {}))
        resp = await http.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401 and not self.api_token:
            self._logged_in = False
            http = await self._ensure_auth()
            resp = await http.request(method, path, headers=self._headers(json_body="json" in kwargs), **kwargs)
        data = _json(resp)
        if resp.status_code >= 400 or data.get("success") is False:
            raise PanelError(data.get("msg") or f"{method} {path}: HTTP {resp.status_code}")
        return data

    async def list_inbounds(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/panel/api/inbounds/list")
        obj = data.get("obj") or []
        return obj if isinstance(obj, list) else []

    async def get_client(self, email: str) -> dict[str, Any] | None:
        try:
            data = await self._request("GET", f"/panel/api/clients/get/{quote(email, safe='')}")
        except PanelError:
            return None
        obj = data.get("obj")
        return obj if isinstance(obj, dict) else None

    async def client_links(self, email: str) -> list[str]:
        try:
            data = await self._request("GET", f"/panel/api/clients/links/{quote(email, safe='')}")
        except PanelError as exc:
            log.info("links endpoint unavailable: %s", exc)
            return []
        obj = data.get("obj") or []
        if isinstance(obj, list):
            return [str(item) for item in obj]
        return []

    async def add_client(
        self,
        *,
        email: str,
        inbound_ids: list[int],
        tg_id: int,
        sub_id: str,
        total_bytes: int,
        expiry_ms: int,
        limit_ip: int,
        flow: str,
        comment: str,
    ) -> None:
        client_obj: dict[str, Any] = {
            "email": email,
            "subId": sub_id,
            "tgId": tg_id,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "limitIp": limit_ip,
            "enable": True,
            "comment": comment,
        }
        if flow:
            client_obj["flow"] = flow
        payload = {"client": client_obj, "inboundIds": inbound_ids}
        try:
            await self._request("POST", "/panel/api/clients/add", json=payload)
            return
        except PanelError as modern_err:
            log.info("modern add failed, trying legacy addClient: %s", modern_err)

        if len(inbound_ids) != 1:
            raise PanelError(
                "старая панель умеет добавить клиента только в один inbound; "
                "укажите один INBOUND_IDS или обновите 3x-ui"
            )
        legacy_client = {
            "id": str(uuid.uuid4()),
            "email": email,
            "enable": True,
            "flow": flow,
            "limitIp": limit_ip,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "tgId": str(tg_id),
            "subId": sub_id,
            "comment": comment,
        }
        legacy = {
            "id": inbound_ids[0],
            "settings": json.dumps({"clients": [legacy_client]}, ensure_ascii=False),
        }
        await self._request("POST", "/panel/api/inbounds/addClient", json=legacy)

    async def extend_client(self, email: str, expiry_ms: int, total_bytes: int) -> None:
        payload = {"email": email, "expiryTime": expiry_ms, "totalGB": total_bytes, "enable": True}
        try:
            await self._request("POST", f"/panel/api/clients/update/{quote(email, safe='')}", json=payload)
            return
        except PanelError as modern_err:
            log.info("modern update failed: %s", modern_err)
        client = await self.get_client(email)
        client_id = ""
        if client:
            client_id = str(client.get("id") or client.get("uuid") or "")
        if not client_id:
            raise PanelError("не удалось продлить клиента: панель не отдала id")
        await self._request(
            "POST",
            f"/panel/api/inbounds/updateClient/{quote(client_id, safe='')}",
            json={"id": client_id, "expiryTime": expiry_ms, "totalGB": total_bytes, "enable": True},
        )

    async def delete_client(self, email: str) -> None:
        try:
            await self._request("POST", f"/panel/api/clients/del/{quote(email, safe='')}")
            return
        except PanelError:
            pass
        inbounds = await self.list_inbounds()
        for inbound in inbounds:
            inbound_id = inbound.get("id")
            if inbound_id is None:
                continue
            try:
                await self._request(
                    "POST",
                    f"/panel/api/inbounds/{inbound_id}/delClient/{quote(email, safe='')}",
                )
                return
            except PanelError:
                continue
        raise PanelError(f"не удалось удалить клиента {email}")


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {"success": False, "msg": resp.text[:300]}
    return data if isinstance(data, dict) else {"success": True, "obj": data}


def expiry_from_days(days: int) -> int:
    if days <= 0:
        return 0
    return int((time.time() + days * 86400) * 1000)


def gb_to_bytes(gb: float) -> int:
    if gb <= 0:
        return 0
    return int(gb * 1024 * 1024 * 1024)
