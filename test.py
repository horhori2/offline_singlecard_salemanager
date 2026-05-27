
import asyncio, httpx, bcrypt, pybase64, time
from app.core.config import get_settings

settings = get_settings()

async def test():
    timestamp = str(int((time.time() - 3) * 1000))
    password = settings.naver_client_id + '_' + timestamp
    hashed = bcrypt.hashpw(password.encode('utf-8'), settings.naver_client_secret.encode('utf-8'))
    signature = pybase64.standard_b64encode(hashed).decode('utf-8')

    print('client_id:', settings.naver_client_id)
    print('timestamp:', timestamp)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            'https://api.commerce.naver.com/external/v1/oauth2/token',
            data={
                'client_id': settings.naver_client_id,
                'timestamp': timestamp,
                'client_secret_sign': signature,
                'grant_type': 'client_credentials',
                'type': 'SELF',
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        print('status:', resp.status_code)
        print('response:', resp.text)

asyncio.run(test())
