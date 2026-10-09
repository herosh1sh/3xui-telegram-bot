"""Счета: ЮKassa, Crypto Pay, 2328 и Antilopay. Статус проверяется по кнопке, вебхук не нужен."""

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
        antilopay_secret_id: str = "",
        antilopay_private_key: str = "",
        antilopay_project_id: str = "",
        antilopay_email: str = "",
        antilopay_success_url: str = "",
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
        self.io_return_url = io_return_url or self.yookassa_return_url
        self.antilopay_secret_id = antilopay_secret_id
        self.antilopay_private_key = antilopay_private_key
        self.antilopay_project_id = antilopay_project_id
        self.antilopay_email = antilopay_email or "pay@heroshishvpn.ru"
        self.antilopay_success_url = antilopay_success_url or self.yookassa_return_url
        self.http = httpx.AsyncClient(timeout=30)

    def enabled(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if self.yookassa_shop_id and self.yookassa_secret:
            items.append(("yookassa", "Карта, ЮKassa"))
        if self.cryptopay_token:
            items.append(("cryptopay", "Crypto Pay"))
        if self.io_project and self.io_api_key:
            items.append(("2328", "Крипта, 2328"))
        if self.antilopay_secret_id and self.antilopay_private_key and self.antilopay_project_id:
            items.append(("antilopay", "Antilopay"))
        return items

    async def close(self) -> None:
        await self.http.aclose()

    def _with_order(self, url: str, order_id: str) -> str:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}order_id={order_id}"

    async def create(self, provider: str, order_id: str, amount_rub: int, days: int) -> Invoice:
        if provider == "yookassa":
            return await self._yookassa(order_id, amount_rub, days)
        if provider == "cryptopay":
            return await self._cryptopay(order_id, amount_rub, days)
        if provider == "2328":
            return await self._2328(order_id, amount_rub, days)
        if provider == "antilopay":
            return await self._antilopay(order_id, amount_rub, days)
        raise PayError("неизвестный способ оплаты")

    async def is_paid(self, provider: str, provider_id: str) -> bool:
        return await self.status(provider, provider_id) == "succeeded"

    async def status(self, provider: str, provider_id: str) -> str:
        if provider == "yookassa":
            return await self._yookassa_status(provider_id)
        if provider == "cryptopay":
            return await self._cryptopay_status(provider_id)
        if provider == "2328":
            return "succeeded" if await self._2328_paid(provider_id) else "canceled"
        if provider == "antilopay":
            return await self._antilopay_status(provider_id)
        return "canceled"

    async def _yookassa(self, order_id: str, amount_rub: int, days: int) -> Invoice:
        def create() -> Invoice:
            from yookassa import Configuration, Payment

            Configuration.account_id = self.yookassa_shop_id
            Configuration.secret_key = self.yookassa_secret
            payment = Payment.create(
                {
                    "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
                    "confirmation": {"type": "redirect", "return_url": self._with_order(self.yookassa_return_url, order_id)},
                    "capture": True,
                    "description": f"Подписка {days} дней",
                    "metadata": {"order_id": order_id},
                },
                order_id,
            )
            return Invoice(str(payment.id), str(payment.confirmation.confirmation_url))

        return await asyncio.to_thread(create)

    async def _yookassa_status(self, payment_id: str) -> str:
        def check() -> str:
            from yookassa import Configuration, Payment

            Configuration.account_id = self.yookassa_shop_id
            Configuration.secret_key = self.yookassa_secret
            return str(Payment.find_one(payment_id).status)

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
                "paid_btn_name": "callback",
                "paid_btn_url": self._with_order(self.yookassa_return_url, order_id),
            },
        )
        data = resp.json()
        if not data.get("ok"):
            raise PayError(str(data.get("error") or resp.text[:200]))
        result = data["result"]
        return Invoice(str(result["invoice_id"]), str(result["bot_invoice_url"]))

    async def _cryptopay_status(self, invoice_id: str) -> str:
        resp = await self.http.get(
            f"{self.cryptopay_base}/getInvoices",
            headers={"Crypto-Pay-API-Token": self.cryptopay_token},
            params={"invoice_ids": invoice_id},
        )
        data = resp.json()
        if not data.get("ok"):
            raise PayError(str(data.get("error") or resp.text[:200]))
        items = data.get("result", {}).get("items") or data.get("result") or []
        for item in items:
            if str(item.get("invoice_id")) == invoice_id:
                return "succeeded" if item.get("status") == "paid" else "canceled"
        return "canceled"

    async def _2328(self, order_id: str, amount_rub: int, days: int) -> Invoice:
        body = json.dumps(
            {
                "amount": f"{amount_rub:.2f}",
                "currency": "RUB",
                "order_id": order_id,
                "url_return": self._with_order(self.io_return_url, order_id),
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
        resp = await self.http.get(
            f"https://api.2328.io/api/v1/payment/{provider_id}",
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

    async def _antilopay(self, order_id: str, amount_rub: int, days: int) -> Invoice:
        payload = {
            "project_identificator": self.antilopay_project_id,
            "amount": amount_rub,
            "order_id": order_id,
            "currency": "RUB",
            "product_name": "Пополнение баланса",
            "product_type": "services",
            "description": f"Пополнение баланса на {amount_rub} ₽",
            "customer": {"email": self.antilopay_email},
        }
        success = self.antilopay_success_url
        if success.startswith("https://"):
            payload["success_url"] = self._with_order(success, order_id)
            payload["fail_url"] = self._with_order(success, order_id)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        resp = await self.http.post(
            "https://lk.antilopay.com/api/v1/payment/create",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Apay-Secret-Id": self.antilopay_secret_id,
                "X-Apay-Sign": _antilopay_sign(body, self.antilopay_private_key),
                "X-Apay-Sign-Version": "1",
            },
        )
        data = resp.json()
        if resp.status_code >= 400 or data.get("code") not in (0, None):
            raise PayError(str(data.get("error") or data)[:300])
        pay_url = str(data.get("payment_url") or "")
        if not pay_url:
            raise PayError(f"Antilopay не вернул ссылку: {str(data)[:300]}")
        return Invoice(order_id, pay_url)

    async def _antilopay_status(self, order_id: str) -> str:
        body = json.dumps(
            {"project_identificator": self.antilopay_project_id, "order_id": order_id},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        resp = await self.http.post(
            "https://lk.antilopay.com/api/v1/payment/check",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Apay-Secret-Id": self.antilopay_secret_id,
                "X-Apay-Sign": _antilopay_sign(body, self.antilopay_private_key),
                "X-Apay-Sign-Version": "1",
            },
        )
        data = resp.json()
        if resp.status_code >= 400 or data.get("code") not in (0, None):
            raise PayError(str(data.get("error") or data)[:300])
        status = str(data.get("status") or "").upper()
        if status == "SUCCESS":
            return "succeeded"
        if status == "PENDING":
            return "pending"
        return "canceled"


def _antilopay_sign(payload: bytes, private_key: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    raw = "".join(private_key.split())
    for marker in (
        "-----BEGINPRIVATEKEY-----",
        "-----ENDPRIVATEKEY-----",
        "-----BEGINRSAPRIVATEKEY-----",
        "-----ENDRSAPRIVATEKEY-----",
    ):
        raw = raw.replace(marker, "")
    der = base64.b64decode(raw)
    try:
        key = serialization.load_der_private_key(der, password=None)
    except ValueError:
        pem = b"-----BEGIN RSA PRIVATE KEY-----\n" + base64.b64encode(der) + b"\n-----END RSA PRIVATE KEY-----\n"
        key = serialization.load_pem_private_key(pem, password=None)
    signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()
