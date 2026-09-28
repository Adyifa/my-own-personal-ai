from __future__ import annotations

import asyncio

import edge_tts


async def main_async() -> None:
    voices = await edge_tts.list_voices()
    for voice in voices:
        locale = voice.get("Locale", "")
        if locale.startswith("id-"):
            print(f"{voice.get('ShortName')} - {voice.get('FriendlyName')}")


def main() -> int:
    asyncio.run(main_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
