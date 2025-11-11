
from loguru import logger
import sys
from common.config import settings

def setup_logging():
    logger.remove()
    logger.add(sys.stderr, level=settings.LOG_LEVEL)
    return logger

logger = setup_logging()
