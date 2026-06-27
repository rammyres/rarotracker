#!/usr/bin/env python3
"""
Script standalone para checagem de disponibilidade — chamado pelo systemd
timer 3x/dia (mesmo padrão do update.py do projeto mistq).

Uso manual:
    cd /home/claude/raro-tracker && python3 scheduler/check_availability.py

Ver raro-tracker.timer / raro-tracker.service em deploy/ para o agendamento.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("raro_tracker.scheduler")

from app import create_app  # noqa: E402
from checker import run_full_check  # noqa: E402


def main():
    app = create_app()
    with app.app_context():
        logger.info("Iniciando checagem de disponibilidade...")
        summary = run_full_check()
        logger.info(
            f"Checagem concluída: {summary['checked']} checados, "
            f"{summary['newly_available']} ficaram disponíveis agora, "
            f"{summary['errors']} erros."
        )


if __name__ == "__main__":
    main()
