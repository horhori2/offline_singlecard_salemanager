"""
네이버 커머스 API 클라이언트
https://apicenter.commerce.naver.com/ko/reference
"""
import pybase64
import time
import logging
from typing import Any

import bcrypt
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class NaverCommerceClient:
    """네이버 커머스 API 인증 및 호출 담당"""

    def __init__(self):
        self.client_id = settings.naver_client_id
        self.client_secret = settings.naver_client_secret
        self.base_url = settings.naver_api_base
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    # ── 인증 ─────────────────────────────────────────────────────────────────

    def _make_signature(self) -> tuple[str, str]:
        """
        bcrypt 전자서명 생성
        password  = client_id + "_" + timestamp
        signature = Base64( bcrypt(password, client_secret) )
        ※ timestamp는 발급 직전 매번 새로 생성 (5분 유효)
        """
        timestamp = str(int((time.time() - 3) * 1000))
        password = f"{self.client_id}_{timestamp}"
        hashed = bcrypt.hashpw(
            password.encode("utf-8"),
            self.client_secret.encode("utf-8"),
        )
        signature = pybase64.standard_b64encode(hashed).decode("utf-8")
        return timestamp, signature

    async def _get_access_token(self) -> str:
        """
        OAuth2 액세스 토큰 발급 (만료 전 자동 갱신)
        ※ 문서: type=SELLER 시 account_id가 실무상 필수
                type=SELF  시 본인 계정 전용 (account_id 불필요)
        """
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        # ✅ 수정 1: timestamp는 토큰 요청 직전 매번 새로 생성
        timestamp, signature = self._make_signature()

        payload: dict[str, str] = {
            "client_id": self.client_id,
            "timestamp": timestamp,
            "client_secret_sign": signature,
            "grant_type": "client_credentials",
            "type": "SELF",  # 본인 계정용. 대리 인증이면 "SELLER" + account_id 추가
        }

        # ✅ 수정 2: account_id가 설정된 경우 SELLER 타입으로 전환
        if settings.naver_account_id:
            payload["type"] = "SELLER"
            payload["account_id"] = settings.naver_account_id

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.naver_auth_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        logger.info("네이버 액세스 토큰 갱신 완료")
        return self._access_token

    async def _headers(self) -> dict[str, str]:
        token = await self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ── 상품 조회 ──────────────────────────────────────────────────────────────

    async def get_product(self, origin_product_no: str) -> dict[str, Any]:
        """
        원상품 단건 조회
        GET /v2/products/origin-products/{originProductNo}
        ✅ 수정 3: v1 → v2 엔드포인트로 변경 (문서상 최신 버전)
        """
        url = f"{self.base_url}/v2/products/origin-products/{origin_product_no}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=await self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()

    async def get_channel_product(self, channel_product_no: str) -> dict[str, Any]:
        """
        채널 상품 단건 조회
        GET /v2/products/channel-products/{channelProductNo}
        """
        url = f"{self.base_url}/v2/products/channel-products/{channel_product_no}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=await self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()

    async def search_products(self, page: int = 1, size: int = 100) -> dict[str, Any]:
        """판매자 상품 목록 조회 POST /v1/products/search"""
        url = f"{self.base_url}/v1/products/search"
        payload = {"page": page, "size": size}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=await self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()

    async def search_products_by_seller_code(self, seller_management_code: str) -> dict[str, Any]:
        """판매자 관리코드(바코드)로 원상품번호 검색
        searchKeywordType=SELLER_CODE + sellerManagementCode 조합 필수
        """
        url = f"{self.base_url}/v1/products/search"
        payload = {
            "searchKeywordType": "SELLER_CODE",
            "sellerManagementCode": seller_management_code,
            "page": 1,
            "size": 1,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=await self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()

    async def search_products_by_channel_id(self, channel_product_no: str) -> dict[str, Any]:
        """채널상품번호로 원상품번호 조회 POST /v1/products/search"""
        url = f"{self.base_url}/v1/products/search"
        payload = {
            "channelProductNos": [int(channel_product_no)],
            "page": 1,
            "size": 1,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=await self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()

    # ── 재고 수정 ──────────────────────────────────────────────────────────────

    async def update_option_stock(
        self,
        origin_product_no: str,
        option_combinations: list[dict],
    ) -> dict[str, Any]:
        """
        원상품 옵션별 재고·가격 변경
        PUT /v1/products/origin-products/{originProductNo}/option-stock
        ✅ 수정 5: 문서 기준 정식 재고 수정 엔드포인트로 교체
        payload 예시:
          option_combinations = [
            {"id": "옵션ID", "stockQuantity": 50},
            ...
          ]
        동일 원상품에 동시 호출 시 정합성 문제 → 직렬 호출 필요
        """
        url = f"{self.base_url}/v1/products/origin-products/{origin_product_no}/option-stock"
        payload = {"optionCombinations": option_combinations}
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                url,
                json=payload,
                headers=await self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            logger.info(
                "네이버 옵션 재고 업데이트: originProductNo=%s, options=%s",
                origin_product_no, option_combinations,
            )
            return resp.json() if resp.text else {"success": True}

    async def update_stock(
        self,
        product_id: str,
        option_id: str,
        stock_quantity: int,
    ) -> dict[str, Any]:
        """
        단일 옵션 재고 수정 헬퍼 (update_option_stock 래퍼)
        기존 호출 코드와의 호환성 유지용
        """
        return await self.update_option_stock(
            origin_product_no=product_id,
            option_combinations=[{"id": option_id, "stockQuantity": stock_quantity}],
        )

    async def update_stock_by_origin_product(
        self,
        origin_product_id: str,
        stock_quantity: int,
    ) -> dict[str, Any]:
        """
        옵션 없는 단일 상품 재고 수정
        GET으로 현재 상품 정보 조회 후 stockQuantity만 바꿔서 PUT
        PUT /v2/products/origin-products/{originProductNo}
        """
        # 1) 현재 상품 정보 조회
        current = await self.get_product(origin_product_id)
        origin = current.get("originProduct", {})

        # 2) stockQuantity만 교체 후 전체 PUT
        origin["stockQuantity"] = stock_quantity

        url = f"{self.base_url}/v2/products/origin-products/{origin_product_id}"
        payload = {"originProduct": origin}

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                url,
                json=payload,
                headers=await self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            logger.info(
                "네이버 단일상품 재고 업데이트: originProductNo=%s, stock=%d",
                origin_product_id, stock_quantity,
            )
            return resp.json() if resp.text else {"success": True}

    # ── 주문 조회 ──────────────────────────────────────────────────────────────

    async def get_recent_orders(self, last_changed_from: str) -> dict[str, Any]:
        """
        변경된 상품 주문 내역 조회 (재고 자동 차감 검증용)
        GET /v1/pay-order/seller/product-orders/last-changed-statuses
        ✅ 수정 6: 올바른 엔드포인트로 수정 (orders → product-orders)
        1~3분 주기 폴링 권장
        """
        url = f"{self.base_url}/v1/pay-order/seller/product-orders/last-changed-statuses"
        params = {"lastChangedFrom": last_changed_from, "limitCount": 100}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=await self._headers(), params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()

    async def get_payed_orders_by_date(self, from_date: str) -> dict[str, Any]:
        """
        결제일 기준 PAYED/PRODUCT_PREPARE 주문 조회 (lastChangedDate가 없는 주문 보완용)
        GET /v1/pay-order/seller/product-orders/last-changed-statuses
        lastChangedType으로 필터하면 결제 시점 기준으로 조회 가능
        """
        url = f"{self.base_url}/v1/pay-order/seller/product-orders/last-changed-statuses"
        all_statuses = []
        for changed_type in ["PAYED", "PRODUCT_PREPARE"]:
            params = {
                "lastChangedFrom": from_date,
                "lastChangedType": changed_type,
                "limitCount": 100,
            }
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=await self._headers(), params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    statuses = data.get("lastChangeStatuses", [])
                    all_statuses.extend(statuses)
        return {"data": {"lastChangeStatuses": all_statuses}}

    async def get_product_order_details(self, product_order_ids: list[str]) -> dict[str, Any]:
        """
        상품 주문 상세 내역 다건 조회
        POST /v1/pay-order/seller/product-orders/query
        변경 피드와 묶어 OMS 동기화에 사용
        """
        url = f"{self.base_url}/v1/pay-order/seller/product-orders/query"
        payload = {"productOrderIds": product_order_ids}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=await self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()

    # ── 연결 테스트 ────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """API 키 유효성 확인"""
        try:
            await self._get_access_token()
            return True
        except Exception as e:
            logger.error("네이버 API 연결 실패: %s", e)
            return False


# 싱글톤 인스턴스
naver_client = NaverCommerceClient()