import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig()
main_log = "./logs/main.log"
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt="%Y-%m-%d %H:%M:%S")

# Logs the transaction data
tx_logger = logging.getLogger('tx')
tx_logger.setLevel(logging.INFO)

# Logs the main log
main_logger = logging.getLogger()
main_logger.setLevel(logging.DEBUG)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

main_handler = RotatingFileHandler(main_log, maxBytes=500000, backupCount=10)
main_handler.setLevel(logging.INFO)
main_handler.setFormatter(formatter)

main_logger.addHandler(main_handler)
main_logger.addHandler(stream_handler)
