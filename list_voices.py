import pyttsx3


def main() -> int:
    engine = pyttsx3.init()
    for index, voice in enumerate(engine.getProperty("voices"), start=1):
        print(f"{index}. {voice.name}")
        print(f"   id: {voice.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
