import asyncio
from app.services.naver_client import naver_client
from app.services.order_sync import _kst_ago_iso

async def test():
    from_time = _kst_ago_iso(60 * 24 * 7)
    print('조회 시작:', from_time)
    result = await naver_client.get_recent_orders(from_time)
    statuses = result.get('lastChangeStatuses', [])
    print('변경된 주문 수:', len(statuses))
    if statuses:
        for s in statuses[:5]:
            print(' -', s.get('productOrderStatus'), s.get('productOrderId'))

asyncio.run(test())
