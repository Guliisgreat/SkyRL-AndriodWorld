import logging
import os

_current_log_paths = {}

def get_logger(name, log_path):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if _current_log_paths.get(name) != log_path:
        handlers_to_remove = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        for h in handlers_to_remove:
            logger.removeHandler(h)
            h.close()

        # Ensure the log directory exists
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        # Create file handler
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)

        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)

        # Attach handler
        logger.addHandler(file_handler)
        
        # Update tracking
        _current_log_paths[name] = log_path

    return logger
