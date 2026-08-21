import asyncio
import signal

import structlog


async def run():
    logger = structlog.get_logger()
    logger.info("ai-job-filter starting (Phase 1 Stub)")
    raise NotImplementedError("Phase 2: Wire real components")


def main():
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)
    try:
        loop.run_until_complete(run())
    except NotImplementedError as e:
        print(f"Exiting: {e}")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
