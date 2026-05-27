from datetime import datetime
from pydantic import BaseModel, Field


# ── 상품 ──────────────────────────────────────────
class ProductCreate(BaseModel):
    barcode: str = Field(..., description="상품 바코드 (없으면 채널상품번호 사용)")
    name: str = Field(..., description="상품명")
    offline_stock: int = Field(0, ge=0)
    naver_stock: int = Field(0, ge=0)
    naver_channel_id: str | None = Field(None, description="채널상품번호")
    naver_origin_id: str | None = Field(None, description="원상품번호")
    naver_option_id: str | None = Field(None, description="옵션ID (옵션상품만)")
    naver_sale_price: int = Field(0, ge=0, description="네이버 판매가")
    naver_image_url: str | None = Field(None, description="네이버 상품 이미지 URL")


class ProductUpdate(BaseModel):
    name: str | None = None
    offline_stock: int | None = Field(None, ge=0)
    naver_channel_id: str | None = None
    naver_origin_id: str | None = None
    naver_option_id: str | None = None


class ProductResponse(BaseModel):
    id: int
    barcode: str
    name: str
    offline_stock: int
    offline_price: int
    naver_stock: int
    naver_channel_id: str | None
    naver_origin_id: str | None
    naver_option_id: str | None
    naver_sale_price: int
    naver_image_url: str | None
    pending_online_orders: int = 0
    naver_status_type: str | None = None  # ← 추가
    is_synced: bool
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 엑셀 업로드 결과 ────────────────────────────────
class ExcelImportResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    skipped: int
    results: list[dict]


# ── 재고 수정 ──────────────────────────────────────
class StockAdjust(BaseModel):
    offline_stock: int | None = Field(None, ge=0)
    naver_stock: int | None = Field(None, ge=0)
    sync_to_naver: bool = Field(True)


class BarcodeStockUpdate(BaseModel):
    barcode: str
    quantity: int = Field(1, ge=1)
    sync_to_naver: bool = Field(True)


# ── 동기화 ──────────────────────────────────────────
class SyncResult(BaseModel):
    product_id: int
    product_name: str
    success: bool
    message: str
    naver_stock_after: int | None = None


class BulkSyncResult(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[SyncResult]


# ── 로그 ──────────────────────────────────────────
class SyncLogResponse(BaseModel):
    id: int
    product_id: int | None
    action: str
    message: str
    before_offline: int | None
    after_offline: int | None
    before_naver: int | None
    after_naver: int | None
    success: bool
    created_at: datetime

    model_config = {"from_attributes": True}