"""
네이버 스마트스토어 × 오프라인 통합 재고 관리 서버
실행: uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.database import init_db, AsyncSessionLocal
from app.models.product import Product, SyncLog, OfflineOrder, OfflineOrderItem  # noqa: F401 — Base.metadata 등록용
from app.routers import products, system
from app.services import inventory as svc
from app.services.order_sync import poll_order_changes, verify_naver_stock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


async def _auto_sync_job():
    """스케줄러: 주기적 자동 동기화"""
    async with AsyncSessionLocal() as db:
        result = await svc.sync_all_unsynced(db)
        if result.total:
            logger.info(
                "자동 동기화: 총 %d건 / 성공 %d / 실패 %d",
                result.total, result.succeeded, result.failed,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 시작 ──
    logger.info("서버 시작 중...")
    await init_db()
    logger.info("DB 초기화 완료")

    if settings.auto_sync_interval > 0:
        scheduler.add_job(
            _auto_sync_job,
            "interval",
            seconds=settings.auto_sync_interval,
            id="auto_sync",
        )
        logger.info("자동 동기화 스케줄러 시작 (주기: %ds)", settings.auto_sync_interval)

    # 온라인 주문 폴링 스케줄러 (2분마다)
    scheduler.add_job(
        poll_order_changes,
        "interval",
        minutes=2,
        id="order_poll",
    )
    logger.info("주문 폴링 스케줄러 시작 (2분 주기)")

    # 네이버 재고 검증 스케줄러 (30분마다)
    scheduler.add_job(
        verify_naver_stock,
        "interval",
        minutes=30,
        id="stock_verify",
    )
    scheduler.start()
    logger.info("재고 검증 스케줄러 시작 (30분 주기)")

    yield

    # ── 종료 ──
    if scheduler.running:
        scheduler.shutdown()
    logger.info("서버 종료")


app = FastAPI(
    title="📦 네이버 스마트스토어 재고 관리 API",
    description="""
오프라인 매장 바코드 스캔과 네이버 스마트스토어 재고를 실시간 동기화합니다.

## 주요 기능
- **바코드 스캔** → 오프라인 재고 자동 차감
- **네이버 API 동기화** → 재고 변경 즉시 반영
- **재고 부족 감지** → 임계치 이하 시 로그 경고
- **자동 동기화** → 설정 주기마다 미반영 재고 일괄 처리
""",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 운영 시 대시보드 도메인으로 교체
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(products.router, prefix="/products")

import os
from fastapi.staticfiles import StaticFiles
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/", StaticFiles(directory=_root, html=True), name="static")