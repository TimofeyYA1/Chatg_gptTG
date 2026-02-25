import hmac
import hashlib
import base64
import httpx
import logging
from common.config import settings

logger = logging.getLogger(__name__)

class CloudPaymentsService:
    def __init__(self):
        self.public_id = settings.CLOUDPAYMENTS_PUBLIC_ID
        self.api_secret = settings.CLOUDPAYMENTS_API_SECRET
        self.base_url = "https://api.cloudpayments.ru"

    def check_signature(self, body: bytes, signature: str) -> bool:
        """Проверка HMAC подписи от CloudPayments"""
        if not self.api_secret:
            is_prod = (settings.APP_ENV or "").strip().lower() in {"prod", "production"}
            if is_prod:
                logger.error("CloudPayments API secret is missing in production.")
                return False
            return True  # Dev mode: если секрет не задан, пропускаем проверку

        computed = base64.b64encode(
            hmac.new(
                self.api_secret.encode('utf-8'),
                body,
                digestmod=hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        return hmac.compare_digest(computed, signature)

    async def cancel_subscription(self, cp_sub_id: str):
        """Отмена рекуррентной подписки в CloudPayments"""
        if not cp_sub_id:
            return
            
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/subscriptions/cancel",
                    auth=(self.public_id, self.api_secret),
                    json={"Id": cp_sub_id}
                )
                data = resp.json()
                if data.get("Success"):
                    logger.info(f"CP Subscription {cp_sub_id} cancelled.")
                else:
                    logger.error(f"Failed to cancel CP sub {cp_sub_id}: {data.get('Message')}")
            except Exception as e:
                logger.error(f"CP API Error: {e}")

cp_service = CloudPaymentsService()
