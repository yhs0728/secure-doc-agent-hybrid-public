import logging

from config.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    log_level = getattr(
        logging,
        settings.log_level.upper(),
        logging.INFO,
    )
    logging.basicConfig(
        level=log_level,
        format=(
            "%(asctime)s %(levelname)s "
            "%(name)s %(message)s"
        ),
    )
