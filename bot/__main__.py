import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiohttp import web
from bot.config import cfg, validate_runtime_config
from bot.db import init_db
from bot.seed import seed
from bot.user import r as user_r
from bot.admin import r as admin_r
from bot.web import make_web, make_scheduler

async def main():
    logging.basicConfig(level=logging.INFO)
    validate_runtime_config()
    await init_db()
    n = await seed(); logging.info(f"каталог: {n} офферов")
    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode="HTML"))
    if cfg.webapp_url:
        from aiogram.types import MenuButtonWebApp, WebAppInfo
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="BONVERA", web_app=WebAppInfo(url=cfg.webapp_url)))
            logging.info("menu button Mini App установлен")
        except Exception as e:
            logging.warning(f"не удалось установить menu button: {e}")
    storage = RedisStorage.from_url(cfg.redis_url) if cfg.redis_url else None
    dp = Dispatcher(storage=storage)
    dp.include_router(admin_r); dp.include_router(user_r)
    runner = web.AppRunner(make_web(bot), access_log=None); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", cfg.port).start()
    scheduler = make_scheduler(bot); scheduler.start()
    logging.info(f"postback endpoint запущен на :{cfg.port}; секрет скрыт")
    try:
        from aiogram.types import BotCommand, BotCommandScopeChat
        user_commands = [
            BotCommand(command="start", description="Меню и приложение"),
            BotCommand(command="help", description="Как это работает"),
            BotCommand(command="balance", description="Баланс и начисления"),
            BotCommand(command="deals", description="Мои заявки"),
        ]
        admin_commands = user_commands + [
            BotCommand(command="stats", description="Сводка по системе"),
            BotCommand(command="deal", description="Карточка заявки: /deal 123"),
            BotCommand(command="admin", description="Админ-панель"),
        ]
        await bot.set_my_commands(user_commands)
        for admin_id in cfg.admins:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception:
                logging.warning("не удалось установить команды для %s", admin_id)
        logging.info("меню команд установлено")
    except Exception:
        logging.exception("не удалось установить меню команд")

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        if storage: await storage.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
