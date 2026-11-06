"""Ruleta de la Suerte de La Selva del Prado.

Todo lo de la ruleta vive en este módulo:

* Modelos  -> ``PremioRuleta`` (tabla ``premios_ruleta``) y ``TicketRuleta``
              (tabla ``tickets_ruleta``: un ticket = un giro).
* Lógica   -> ``sincronizar_giros`` otorga o retira giros según los platos de
              comida del pedido (1 plato = 1 ticket) y ``estado_ruleta`` resume lo que tiene una mesa.
* Rutas    -> blueprint ``ruleta`` con la vista del cliente, el JSON de premios,
              el endpoint que gira y el panel de administración.

Reglas de seguridad:

* El premio lo sortea SIEMPRE el servidor; el navegador solo anima la ruleta
  hasta el premio que le devuelve el servidor.
* Cada ticket se marca como usado con un UPDATE condicional (``usado = 0``),
  así un doble clic o dos pestañas no pueden gastar el mismo giro dos veces.
* Los giros solo valen mientras el pedido sigue ``Pendiente``: al cobrar la
  cuenta, los giros que sobren no pasan a los siguientes clientes de la mesa.
"""
import re
import secrets
from functools import wraps

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from sqlalchemy import func, inspect

from extensions import db, obtener_hora_peru
from models import Pedido

# ==========================================
# CONFIGURACIÓN DE LA PROMOCIÓN
# ==========================================
CATEGORIA_CON_GIRO = 'Comida'  # solo los platos de comida dan tickets (bebidas, golosinas y piscina no)
MAX_PREMIOS_ACTIVOS = 12     # más segmentos ya no se leen bien en la ruleta
LARGO_MAX_TEXTO = 40

PATRON_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
_azar = secrets.SystemRandom()  # azar criptográfico: el sorteo no es predecible

PREMIOS_INICIALES = [
    ('Refresco gratis', '#1f9d6b', 3),
    ('10% de descuento', '#c98a3c', 3),
    ('Sigue participando', '#47806a', 4),
    ('Postre de la casa', '#a33222', 2),
    ('Golosina gratis', '#742284', 3),
    ('Entrada a piscina', '#1f4fa3', 1),
]

bp = Blueprint('ruleta', __name__)


# ==========================================
# MODELOS
# ==========================================
class PremioRuleta(db.Model):
    __tablename__ = 'premios_ruleta'

    id = db.Column(db.Integer, primary_key=True)
    texto = db.Column(db.String(LARGO_MAX_TEXTO), nullable=False)
    color = db.Column(db.String(7), nullable=False, default='#c98a3c')  # HEX #RRGGBB
    activo = db.Column(db.Boolean, nullable=False, default=True)
    # Peso relativo de probabilidad: un premio con peso 4 sale el doble que uno con peso 2
    peso = db.Column(db.Integer, nullable=False, default=1)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_peru)

    def a_dict(self):
        """Datos públicos del premio (el peso no se expone al cliente)."""
        return {'id': self.id, 'texto': self.texto, 'color': self.color}


class TicketRuleta(db.Model):
    __tablename__ = 'tickets_ruleta'

    id = db.Column(db.Integer, primary_key=True)
    # nullable: si el pedido se borra, el historial de premios ya ganados se conserva
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedido.id'), nullable=True, index=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=False, index=True)
    codigo = db.Column(db.String(8), unique=True, nullable=False, default=lambda: secrets.token_hex(3).upper())
    usado = db.Column(db.Boolean, nullable=False, default=False, index=True)
    premio_id = db.Column(db.Integer, db.ForeignKey('premios_ruleta.id'), nullable=True)
    # Copia del texto/color del premio: el historial no cambia si el admin lo edita o borra
    premio_texto = db.Column(db.String(LARGO_MAX_TEXTO), nullable=True)
    premio_color = db.Column(db.String(7), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_peru)
    fecha_uso = db.Column(db.DateTime, nullable=True)

    mesa = db.relationship('Mesa')


# ==========================================
# LÓGICA DE GIROS
# ==========================================
def platos_de_comida(pedido):
    """Unidades de platos de comida del pedido (2 × Juane = 2 platos)."""
    if pedido is None:
        return 0
    return sum(d.cantidad for d in pedido.detalles
               if d.plato is not None and d.plato.categoria == CATEGORIA_CON_GIRO)


def giros_merecidos(pedido):
    """Un ticket por cada plato de comida consumido."""
    return platos_de_comida(pedido)


def sincronizar_giros(pedido):
    """Ajusta los tickets del pedido a lo que merece. Devuelve cuántos giros nuevos dio.

    Es idempotente: se puede llamar tras cada envío a cocina o edición del
    admin. Nunca toca tickets ya usados (ese premio ya se ganó); si el admin
    quita productos, solo se retiran giros que aún no se usaron.
    No hace commit: lo hace quien llama, junto con el resto de cambios.
    """
    tickets = TicketRuleta.query.filter_by(pedido_id=pedido.id).all()
    usados = sum(1 for t in tickets if t.usado)
    libres = [t for t in tickets if not t.usado]
    faltan = giros_merecidos(pedido) - usados - len(libres)

    if faltan > 0:
        for _ in range(faltan):
            db.session.add(TicketRuleta(pedido_id=pedido.id, mesa_id=pedido.mesa_id))
        return faltan
    # Sobran giros (el admin quitó productos): se retiran los libres más recientes
    for ticket in sorted(libres, key=lambda t: t.id, reverse=True)[:-faltan]:
        db.session.delete(ticket)
    return 0


def desvincular_pedido(pedido):
    """Antes de borrar un pedido: quita sus giros libres y conserva el historial de premios."""
    for ticket in TicketRuleta.query.filter_by(pedido_id=pedido.id).all():
        if ticket.usado:
            ticket.pedido_id = None
        else:
            db.session.delete(ticket)


def _pedido_abierto(mesa_id):
    return Pedido.query.filter_by(mesa_id=mesa_id, estado='Pendiente').first()


def _consulta_tickets_libres(mesa_id, pedido):
    return TicketRuleta.query.filter_by(mesa_id=mesa_id, pedido_id=pedido.id, usado=False)


def estado_ruleta(mesa_id):
    """Resumen para las plantillas: giros libres, premios ganados y platos de comida pedidos."""
    pedido = _pedido_abierto(mesa_id)
    if pedido is None:
        return {'disponibles': 0, 'ganados': [], 'platos': 0}
    ganados = (TicketRuleta.query.filter_by(pedido_id=pedido.id, usado=True)
               .order_by(TicketRuleta.fecha_uso.desc()).all())
    return {
        'disponibles': _consulta_tickets_libres(mesa_id, pedido).count(),
        'ganados': ganados,
        'platos': platos_de_comida(pedido),
    }


def sembrar_premios_iniciales():
    """Crea premios de ejemplo solo la primera vez que existe la tabla."""
    if inspect(db.engine).has_table(PremioRuleta.__tablename__):
        return False
    db.create_all()
    for texto, color, peso in PREMIOS_INICIALES:
        db.session.add(PremioRuleta(texto=texto, color=color, peso=peso))
    db.session.commit()
    return True


# ==========================================
# DECORADORES DE ACCESO
# ==========================================
def mesa_requerida(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if 'mesa_id' not in session:
            if request.is_json or request.path.startswith('/ruleta/api'):
                return jsonify(error='La sesión de la mesa expiró. Vuelve a ingresar.'), 401
            return redirect(url_for('login_mesa'))
        return vista(*args, **kwargs)
    return envoltura


def admin_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return vista(*args, **kwargs)
    return envoltura


# ==========================================
# RUTAS DEL CLIENTE
# ==========================================
@bp.route('/ruleta')
@mesa_requerida
def vista():
    return render_template('ruleta.html',
                           mesa_numero=session.get('mesa_numero'),
                           estado=estado_ruleta(session['mesa_id']))


@bp.route('/ruleta/api/premios')
@mesa_requerida
def api_premios():
    """Premios activos en el orden en que se dibujan en la ruleta."""
    premios = PremioRuleta.query.filter_by(activo=True).order_by(PremioRuleta.id).all()
    return jsonify(premios=[p.a_dict() for p in premios],
                   disponibles=estado_ruleta(session['mesa_id'])['disponibles'])


@bp.route('/ruleta/api/girar', methods=['POST'])
@mesa_requerida
def api_girar():
    """Gasta un ticket, sortea el premio y devuelve el resultado para animarlo."""
    mesa_id = session['mesa_id']
    pedido = _pedido_abierto(mesa_id)
    if pedido is None:
        return jsonify(error='No tienes una cuenta abierta.'), 409

    premios = PremioRuleta.query.filter_by(activo=True).order_by(PremioRuleta.id).all()
    if not premios:
        return jsonify(error='La ruleta no tiene premios activos por ahora.'), 409

    ticket = _consulta_tickets_libres(mesa_id, pedido).order_by(TicketRuleta.id).first()
    if ticket is None:
        return jsonify(error='Ya no te quedan giros disponibles.'), 409

    premio = _azar.choices(premios, weights=[max(p.peso, 1) for p in premios], k=1)[0]

    # UPDATE condicional: si otra petición ganó la carrera, rowcount será 0
    marcado = (TicketRuleta.query
               .filter(TicketRuleta.id == ticket.id, TicketRuleta.usado.is_(False))
               .update({'usado': True, 'premio_id': premio.id, 'premio_texto': premio.texto,
                        'premio_color': premio.color, 'fecha_uso': obtener_hora_peru()},
                       synchronize_session=False))
    if marcado != 1:
        db.session.rollback()
        return jsonify(error='Ese giro ya se usó. Intenta de nuevo.'), 409
    db.session.commit()

    return jsonify(
        indice=premios.index(premio),
        premio=premio.a_dict(),
        codigo=ticket.codigo,
        hora=obtener_hora_peru().strftime('%I:%M %p'),
        disponibles=_consulta_tickets_libres(mesa_id, pedido).count(),
    )


# ==========================================
# PANEL DE ADMINISTRACIÓN
# ==========================================
def _leer_formulario_premio():
    """Valida el formulario de premio. Devuelve (datos, error)."""
    texto = ' '.join(request.form.get('texto', '').split())
    color = request.form.get('color', '').strip()
    try:
        peso = int(request.form.get('peso', 1))
    except ValueError:
        peso = 0
    if not texto:
        return None, 'Escribe el texto del premio.'
    if len(texto) > LARGO_MAX_TEXTO:
        return None, f'El texto no puede pasar de {LARGO_MAX_TEXTO} caracteres.'
    if not PATRON_HEX.match(color):
        return None, 'El color debe tener formato HEX, por ejemplo #C98A3C.'
    if not 1 <= peso <= 100:
        return None, 'La probabilidad debe ser un número entre 1 y 100.'
    return {'texto': texto, 'color': color.lower(), 'peso': peso}, None


def _hay_cupo_activo():
    return PremioRuleta.query.filter_by(activo=True).count() < MAX_PREMIOS_ACTIVOS


@bp.route('/admin/ruleta')
@admin_requerido
def admin_premios():
    premios = PremioRuleta.query.order_by(PremioRuleta.activo.desc(), PremioRuleta.id).all()
    activos = [p for p in premios if p.activo]
    peso_total = sum(p.peso for p in activos) or 1
    ganados = (TicketRuleta.query.filter_by(usado=True)
               .order_by(TicketRuleta.fecha_uso.desc()).limit(30).all())
    libres = TicketRuleta.query.filter_by(usado=False).count()
    entregados = db.session.query(func.count(TicketRuleta.id)).filter(TicketRuleta.usado.is_(True)).scalar()
    return render_template('admin_ruleta.html', premios=premios, activos=activos, peso_total=peso_total,
                           activos_json=[p.a_dict() for p in activos],
                           ganados=ganados, libres=libres, entregados=entregados,
                           ganados_hoy=_consulta_ganados_hoy().count(),
                           max_activos=MAX_PREMIOS_ACTIVOS, largo_max=LARGO_MAX_TEXTO)


def _consulta_ganados_hoy():
    """Premios ganados (tickets usados) desde las 00:00 de hoy, hora de Perú."""
    inicio_dia = obtener_hora_peru().replace(hour=0, minute=0, second=0, microsecond=0)
    return TicketRuleta.query.filter(TicketRuleta.usado.is_(True), TicketRuleta.fecha_uso >= inicio_dia)


@bp.route('/admin/ruleta/limpiar-dia', methods=['POST'])
@admin_requerido
def limpiar_premios_dia():
    """Borra el historial de premios ganados hoy. Los premios configurados de la ruleta no se tocan."""
    borrados = _consulta_ganados_hoy().delete(synchronize_session=False)
    db.session.commit()
    flash(f'Se eliminaron {borrados} premios ganados hoy.' if borrados else 'No había premios ganados hoy.', 'success')
    return redirect(url_for('ruleta.admin_premios'))


@bp.route('/admin/ruleta/premio/agregar', methods=['POST'])
@admin_requerido
def agregar_premio():
    datos, error = _leer_formulario_premio()
    if error:
        flash(error, 'error')
    elif not _hay_cupo_activo():
        flash(f'La ruleta admite hasta {MAX_PREMIOS_ACTIVOS} premios activos. Desactiva uno primero.', 'error')
    else:
        db.session.add(PremioRuleta(**datos))
        db.session.commit()
        flash(f'Premio «{datos["texto"]}» agregado a la ruleta.', 'success')
    return redirect(url_for('ruleta.admin_premios'))


@bp.route('/admin/ruleta/premio/editar/<int:id>', methods=['POST'])
@admin_requerido
def editar_premio(id):
    premio = db.get_or_404(PremioRuleta, id)
    datos, error = _leer_formulario_premio()
    if error:
        flash(error, 'error')
    else:
        for campo, valor in datos.items():
            setattr(premio, campo, valor)
        db.session.commit()
        flash(f'Premio «{premio.texto}» actualizado.', 'success')
    return redirect(url_for('ruleta.admin_premios'))


@bp.route('/admin/ruleta/premio/toggle/<int:id>', methods=['POST'])
@admin_requerido
def toggle_premio(id):
    premio = db.get_or_404(PremioRuleta, id)
    if not premio.activo and not _hay_cupo_activo():
        flash(f'La ruleta admite hasta {MAX_PREMIOS_ACTIVOS} premios activos.', 'error')
    else:
        premio.activo = not premio.activo
        db.session.commit()
        flash(f'«{premio.texto}» {"activado" if premio.activo else "desactivado"}.', 'success')
    return redirect(url_for('ruleta.admin_premios'))


@bp.route('/admin/ruleta/premio/eliminar/<int:id>', methods=['POST'])
@admin_requerido
def eliminar_premio(id):
    premio = db.get_or_404(PremioRuleta, id)
    # El historial guarda su propia copia del texto: solo se suelta la referencia
    TicketRuleta.query.filter_by(premio_id=premio.id).update({'premio_id': None}, synchronize_session=False)
    db.session.delete(premio)
    db.session.commit()
    flash(f'Premio «{premio.texto}» eliminado.', 'success')
    return redirect(url_for('ruleta.admin_premios'))
