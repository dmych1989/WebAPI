"""Debug: Replicate exactly what DeepSeekProvider.login() does."""
import asyncio, sys, json, time
sys.path.insert(0, 'D:\\GitHub\\WebAPI')

async def test():
    from src.core.config import load_config
    from src.provider.deepseek import DeepSeekProvider

    config = load_config()
    ds_cfg = config.providers.get('deepseek')
    acc = ds_cfg.accounts[0]

    print('Account:', acc.name)
    print('Token set:', bool(acc.token))
    print('Cookie set:', bool(getattr(acc, 'cookie', None)))

    provider = DeepSeekProvider(acc)
    try:
        result = await provider.health_check()
        print('Health check result:', result)
    except Exception as e:
        print('Exception:', type(e).__name__, str(e)[:300])
        import traceback
        traceback.print_exc()

asyncio.run(test())