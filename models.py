"""Modelos principales de La Selva del Prado (mesas, carta y pedidos)."""
from extensions import db, obtener_hora_peru


class Mesa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer, unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    pedidos = db.relationship('Pedido', backref='mesa_asignada', lazy=True)

class Plato(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    precio = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    imagen = db.Column(db.String(300), default='https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=300&q=80')
    disponible = db.Column(db.Boolean, default=True)

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=False)
    estado = db.Column(db.String(50), default='Pendiente')
    total = db.Column(db.Float, default=0.0)
    fecha_hora = db.Column(db.DateTime, default=obtener_hora_peru)
    metodo_pago = db.Column(db.String(50), nullable=True)
    monto_recibido = db.Column(db.Float, default=0.0)
    vuelto = db.Column(db.Float, default=0.0)
    detalles = db.relationship('DetallePedido', backref='pedido', lazy=True)

class DetallePedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedido.id'), nullable=False)
    plato_id = db.Column(db.Integer, db.ForeignKey('plato.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False)
    hora_pedido = db.Column(db.DateTime, default=obtener_hora_peru)
    plato = db.relationship('Plato')
