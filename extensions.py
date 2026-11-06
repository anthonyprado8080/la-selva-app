"""Objetos compartidos entre app.py y los módulos (blueprints).

Viven aquí para que cualquier módulo pueda importarlos sin crear
importaciones circulares con app.py.
"""
from datetime import datetime, timedelta

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def obtener_hora_peru():
    """Hora local de Perú (UTC-5, sin horario de verano)."""
    return datetime.utcnow() - timedelta(hours=5)
