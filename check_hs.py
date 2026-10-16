import asyncio
import httpx

async def check():
    from app.config import get_settings
    s = get_settings()
    key = s.hubspot_api_key

    task_ids = ['402781065934', '402738558664', '402798693091']

    async with httpx.AsyncClient(timeout=15) as client:
        for tid in task_ids:
            resp = await client.get(
                f'https://api.hubapi.com/crm/v3/objects/tasks/{tid}',
                headers={'Authorization': f'Bearer {key}'},
                params={'properties': 'hs_task_subject,hs_task_status,hs_task_priority'}
            )
            if resp.is_success:
                d = resp.json()
                props = d.get('properties', {})
                print(f"Task {tid}: {props.get('hs_task_subject','?')} | {props.get('hs_task_status','?')}")
            else:
                print(f"Task {tid}: ERROR {resp.status_code} {resp.text[:100]}")

asyncio.run(check())
