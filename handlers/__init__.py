from aiogram import Dispatcher
from .registration import router as registration_router
from .orders import router as orders_router
from .profile import router as profile_router
from .admin import router as admin_router
from .weekly import router as weekly_router
from .analytics import router as analytics_router
from .gifts import router as gifts_router
from .balance import router as balance_router
from .payment import router as payment_router
from .reviews import router as reviews_router


def register_all_handlers(dp: Dispatcher):
    dp.include_router(admin_router)      # ← первым
    dp.include_router(registration_router)
    dp.include_router(analytics_router)
    dp.include_router(orders_router)
    dp.include_router(profile_router)
    dp.include_router(weekly_router)
    dp.include_router(gifts_router)
    dp.include_router(balance_router)
    dp.include_router(payment_router)
    dp.include_router(reviews_router)
