import asyncio, aiohttp, yaml, json, sys
sys.stdout.reconfigure(encoding='utf-8')

async def test():
    with open('config/config.yaml', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    ds = config['providers']['deepseek']
    account = ds['accounts'][0]
    cookie = account['cookie']
    token = account['token']
    
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Origin': 'https://chat.deepseek.com',
        'Referer': 'https://chat.deepseek.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'X-Client-Locale': 'zh_CN',
        'X-Client-Platform': 'web',
        'Cookie': cookie,
        'Authorization': 'Bearer ' + token,
    }
    
    url = 'https://chat.deepseek.com/api/v0/users/current'
    print('GET ' + url)
    
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers=headers) as resp:
            print('Status:', resp.status)
            data = await resp.json()
            biz_data = (data.get('data') or {}).get('biz_data') or data.get('biz_data', {})
            print('biz_data keys:', list(biz_data.keys()))
            at = biz_data.get('token')
            print('access_token exists:', at is not None)
            if at:
                print('access_token len:', len(at))

asyncio.run(test())
