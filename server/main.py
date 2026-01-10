import signal
import sys
import os

# Add server directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
import logger
import kafka_client
from handler import router as api_router


def create_app() -> FastAPI:
    """Create FastAPI application"""
    app = FastAPI(title="FE-Sentry Server")

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cfg.server.allowed_origins,
        allow_credentials=False,
        allow_methods=["POST", "OPTIONS", "GET"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # Routes
    app.include_router(api_router, prefix="/api")

    return app


def main() -> None:
    # Load config
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        config.load(config_path)
    except Exception as e:
        print(f"Failed to load config: {e}")
        sys.exit(1)

    # Initialize logger
    try:
        logger.init()
    except Exception as e:
        print(f"Failed to init logger: {e}")
        sys.exit(1)

    # Initialize Kafka Producer (optional, fallback to direct file write on failure)
    try:
        kafka_client.init_producer()
    except Exception as e:
        if logger.error_logger:
            logger.error_logger.warning(f"Kafka producer init warning: {e}")

    # Start Kafka Consumer (if Kafka enabled)
    kafka_client.start_consumer_with_retry()

    # Create app
    app = create_app()

    # Shutdown handler
    def shutdown_handler(signum, frame):
        if logger.info_logger:
            logger.info_logger.info("Shutting down...")

        # Stop Kafka consumer
        kafka_client.stop_consumer()

        # Close Kafka producer
        kafka_client.close_producer()

        # Close logger
        logger.close()

        if logger.info_logger:
            logger.info_logger.info("Server stopped")

        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Start server
    if logger.info_logger:
        logger.info_logger.info(f"Server started on port {config.cfg.server.port}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.cfg.server.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
