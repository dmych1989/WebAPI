"""Debug: Replicate EXACTLY what the server health check loop does."""
import asyncio, sys, os
sys.path.insert(0, 'D:\\GitHub\\WebAPI')
os.chdir(r'D:\GitHub\WebAPI')

async def test():
    from src.core.config import load_config
    from src.provider.base import ProviderRegistry
    from src.pool.account_pool import account_pool

    # Import providers to register them
    import src.provider.registration

    config = load_config()
    
    for provider_type, pcfg in config.providers.items():
        if not pcfg.enabled:
            continue
        provider_cls = ProviderRegistry.get(provider_type)
        if provider_cls is None:
            print(f'{provider_type}: NOT REGISTERED')
            continue
        for acc in pcfg.accounts:
            if not acc.enabled:
                continue
            print(f'Checking {provider_type}/{acc.name}...')
            try:
                provider = provider_cls(acc)
                is_healthy = await provider.health_check()
                print(f'  Result: healthy={is_healthy}')
            except Exception as e:
                print(f'  Exception: {type(e).__name__}: {e}')
                import traceback
                traceback.print_exc()

asyncio.run(test())
