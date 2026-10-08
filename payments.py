"""Счета: ЮKassa, Crypto Pay и 2328. Статус проверяется по кнопке, вебхук не нужен."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

import httpx


class PayError(RuntimeError):
    pass


@dataclass
class Invoice:
    provider_id: str
    pay_url: str


def _2328_sign(body: str, api_key: str) -> str:
    digest = base64.b64encode(body.encode("utf-8"))
    return hmac.new(api_key.encode("utf-8"), digest, hashlib.sha256).hexdigest()


class Payments:
    def __init__(
        self,
        *,
        yookassa_shop_id: str,
        yookassa_secret: str,
        yookassa_return_url: str,
        cryptopay_token: str,
        cryptopay_testnet: bool,
        io_project: str,
        io_api_key: str,
        io_return_url: str,
    ) -> None:
        self.yookassa_shop_id = yookassa_shop_id
        self.yookassa_secret = yookassa_secret
        self.yookassa_return_url = yookassa_return_url or "https://t.me"
        self.cryptopay_token = cryptopay_token
        self.cryptopay_base = (
            "https://testnet-pay.crypt.bot/api" if cryptopay_testnet else "https://pay.crypt.bot/api"
        )
        self.io_project = io_project
        self.io_api_key = io_api_key
        self.io_return_url = io_return_url or "https://t.me"
        self.http = httpx.AsyncClient(timeout=30)

    def enabled(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if self.yookassa_shop_id and self.yookassa_secret:
            items.append(("yookassa", "Карта, ЮKassa"))
        if self.cryptopay_token:
            items.append(("cryptopay", "Crypto Pay"))
        if self.io_project and self.io_api_key:
            items.append(("2328", "Крипта, 2328"))
        return items

    async def close(self) -> None:
        await self.http.aclose()

    async def create(self, provider: str, order_id: str, amount_rub: int, days: int) -> Invoice:
        if provider == "yookassa":
            return await self._yookassa(order_id, amount_rub, days)
        if provider == "cryptopay":
            return await self._cryptopay(order_id, amount_rub, days)
        if provider == "2328":
            return await self._2328(order_id, amount_rub, days)
        raise PayError("неизвестный способ оплаты")

    async def is_paid(self, provider: str, provider_id: str) -> bool:
        if provider == "yookassa":
            return await self._yookassa_paid(provider_id)
        if provider == "cryptopay":
            return await self._cryptopay_paid(provider_id)
        if provider == "2328":
            return await self._2328_paid(provider_id)
        return False

    async def _yookassa(self, order_id: str, amount_rub: int, days: int) -> Invoice:
        def create() -> Invoice:
            from yookassa import Configuration, Payment

            Configuration.account_id = self.yookassa_shop_id
            Configuration.secret_key = self.yookassa_secret
            payment = Payment.create(
                {
                    "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
                    "confirmation": {"type": "redirect", "return_url": self.yookassa_return_url},
                    "capture": True,
                    "description": f"Подписка {days} дней",
                    "metadata": {"order_id": order_id},
                },
                order_id,
            )
            return Invoice(str(payment.id), str(payment.confirmation.confirmation_url))

        return await asyncio.to_thread(create)

    async def _yookassa_paid(self, payment_id: str) -> bool:
        def check() -> bool:
            from yookassa import Configuration, Payment

            Configuration.account_id = self.yookassa_shop_id
            Configuration.secret_key = self.yookassa_secret
            payment = Payment.find_one(payment_id)
            return str(payment.status) == "succeeded"

        return await asyncio.to_thread(check)

    async def _cryptopay(self, order_id: str, amount_rub: int, days: int) -> Invoice:
        resp = await self.http.post(
            f"{self.cryptopay_base}/createInvoice",
            headers={"Crypto-Pay-API-Token": self.cryptopay_token},
            json={
                "currency_type": "fiat",
                "fiat": "RUB",
                "amount": str(amount_rub),
                "description": f"Подписка {days} дней",
                "payload": order_id,
                "expires_in": 3600,
            },
        )
        data = resp.json()
        if not data.get("ok"):
            raise PayError(str(data.get("error") or resp.text[:200]))
        result = data["result"]
        return Invoice(str(result["invoice_id"]), str(result["bot_invoice_url"]))

    async def _cryptopay_paid(self, invoice_id: str) -> bool:
        resp = await self.http.get(
            f"{self.cryptopay_base}/getInvoices",
            headers={"Crypto-Pay-API-Token": self.cryptopay_token},
            params={"invoice_ids": invoice_id},
        )
        data = resp.json()
        if not data.get("ok"):
            raise PayError(str(data.get("error") or resp.text[:200]))
        items = data.get("result", {}).get("items") or data.get("result") or []
        return any(str(item.get("invoice_id")) == invoice_id and item.get("status") == "paid" for item in items)

    async def _2328(self, order_id: str, amount_rub: int, days: int) -> Invoice:
        body = json.dumps(
            {
                "amount": f"{amount_rub:.2f}",
                "currency": "RUB",
                "order_id": order_id,
                "url_return": self.io_return_url,
                "description": f"Подписка {days} дней",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        resp = await self.http.post(
            "https://api.2328.io/api/v1/payment",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "3xui-bot/1.0",
                "project": self.io_project,
                "sign": _2328_sign(body, self.io_api_key),
            },
            content=body,
        )
        data = resp.json()
        if resp.status_code >= 400:
            raise PayError(str(data)[:300])
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        pay_url = str(result.get("url") or result.get("link") or result.get("payment_url") or "")
        provider_id = str(result.get("uuid") or result.get("id") or order_id)
        if not pay_url:
            raise PayError(f"2328 не вернул ссылку: {str(data)[:300]}")
        return Invoice(provider_id, pay_url)

    async def _2328_paid(self, provider_id: str) -> bool:
        path = f"/v1/payment/{provider_id}"
        resp = await self.http.get(
            f"https://api.2328.io/api{path}",
            headers={
                "User-Agent": "3xui-bot/1.0",
                "project": self.io_project,
                "sign": _2328_sign("", self.io_api_key),
            },
        )
        if resp.status_code >= 400:
            return False
        data = resp.json()
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        status = str(result.get("status") or result.get("payment_status") or "").lower()
        return status in {"paid", "success", "succeeded", "completed", "confirmed"}
