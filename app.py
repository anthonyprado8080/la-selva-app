from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import base64  # NUEVA HERRAMIENTA PARA NO USAR CARPETAS
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN INICIAL
# ==========================================
app = Flask(__name__)
app.secret_key = 'super_secreta_selva_2026' 

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# 2. MODELOS DE BASE DE DATOS
# ==========================================
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
    # CAMBIO IMPORTANTE: db.Text para poder guardar fotos grandes como texto
    imagen = db.Column(db.Text, default='https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=300&q=80')
    disponible = db.Column(db.Boolean, default=True)

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mesa_id = db.Column(db.Integer, db.ForeignKey('mesa.id'), nullable=False)
    estado = db.Column(db.String(50), default='Pendiente')
    total = db.Column(db.Float, default=0.0)
    fecha_hora = db.Column(db.DateTime, default=datetime.utcnow)
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
    plato = db.relationship('Plato')

# ==========================================
# 3. RUTAS PARA COMENSALES
# ==========================================
@app.route('/')
def home():
    return render_template('welcome.html')

@app.route('/login-mesa', methods=['GET', 'POST'])
def login_mesa():
    if request.method == 'POST':
        numero_mesa = request.form.get('numero_mesa')
        password = request.form.get('password')
        mesa = Mesa.query.filter_by(numero=numero_mesa).first()
        
        if mesa and check_password_hash(mesa.password_hash, password):
            session['mesa_id'] = mesa.id
            session['mesa_numero'] = mesa.numero
            return redirect(url_for('ver_carta'))
        else:
            flash('Número de mesa o contraseña incorrectos.', 'error')
            return redirect(url_for('login_mesa'))
            
    mesas_disponibles = Mesa.query.order_by(Mesa.numero).all()
    return render_template('login_mesa.html', mesas=mesas_disponibles)

@app.route('/carta')
def ver_carta():
    if 'mesa_id' not in session:
        return redirect(url_for('login_mesa'))
        
    platos_comida = Plato.query.filter_by(categoria='Comida', disponible=True).all()
    platos_bebida = Plato.query.filter_by(categoria='Bebida', disponible=True).all()
        
    return render_template('index.html', mesa_numero=session.get('mesa_numero'), comidas=platos_comida, bebidas=platos_bebida)

@app.route('/enviar-pedido', methods=['POST'])
def enviar_pedido():
    if 'mesa_id' not in session:
        return redirect(url_for('login_mesa'))
        
    mesa_id = session['mesa_id']
    subtotal_nuevo = 0.0
    platos_pedidos = []
    
    for clave, valor in request.form.items():
        if clave.startswith('plato_') and int(valor) > 0:
            id_plato = int(clave.split('_')[1])
            cantidad = int(valor)
            plato_db = Plato.query.get(id_plato)
            if plato_db:
                subtotal_nuevo += plato_db.precio * cantidad
                platos_pedidos.append({'plato_id': id_plato, 'cantidad': cantidad, 'precio_unitario': plato_db.precio})

    if not platos_pedidos:
        flash('Debes seleccionar al menos un plato.', 'error')
        return redirect(url_for('ver_carta'))

    pedido_actual = Pedido.query.filter_by(mesa_id=mesa_id, estado='Pendiente').first()
    
    if pedido_actual:
        pedido_actual.total += subtotal_nuevo
    else:
        pedido_actual = Pedido(mesa_id=mesa_id, total=subtotal_nuevo, estado='Pendiente')
        db.session.add(pedido_actual)
        
    db.session.commit() 

    for item in platos_pedidos:
        detalle = DetallePedido(pedido_id=pedido_actual.id, plato_id=item['plato_id'], cantidad=item['cantidad'], precio_unitario=item['precio_unitario'])
        db.session.add(detalle)
    
    db.session.commit()
    return redirect(url_for('gracias'))

@app.route('/gracias')
def gracias():
    if 'mesa_id' not in session:
        return redirect(url_for('login_mesa'))
    return render_template('gracias.html', mesa_numero=session.get('mesa_numero'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_mesa'))

# ==========================================
# 4. RUTAS DE ADMINISTRACIÓN
# ==========================================
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        if password == 'admin':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Contraseña incorrecta.', 'error')
            return redirect(url_for('admin_login'))
    return render_template('login_admin.html')

@app.route('/admin')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    todas_mesas = Mesa.query.order_by(Mesa.numero).all()
    todos_platos = Plato.query.all()
    pedidos_pagados = Pedido.query.filter_by(estado='Pagado').all()
    ganancias_hoy = sum(pedido.total for pedido in pedidos_pagados)
    
    return render_template('admin.html', mesas=todas_mesas, platos=todos_platos, ganancias=ganancias_hoy)

@app.route('/admin/cobrar/<int:pedido_id>', methods=['POST'])
def cobrar_pedido(pedido_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    pedido = Pedido.query.get(pedido_id)
    if pedido:
        pedido.estado = 'Pagado'
        pedido.metodo_pago = request.form.get('metodo_pago', 'Efectivo')
        
        monto_recibido = request.form.get('monto_recibido')
        if pedido.metodo_pago == 'Efectivo' and monto_recibido:
            try:
                pedido.monto_recibido = float(monto_recibido)
                pedido.vuelto = pedido.monto_recibido - pedido.total
            except ValueError:
                pedido.monto_recibido = pedido.total
                pedido.vuelto = 0.0
        else:
            pedido.monto_recibido = pedido.total
            pedido.vuelto = 0.0
            
        db.session.commit()
        return redirect(url_for('ver_boleta', pedido_id=pedido.id))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/boleta/<int:pedido_id>')
def ver_boleta(pedido_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    pedido = Pedido.query.get_or_404(pedido_id)
    return render_template('boleta.html', pedido=pedido)

@app.route('/admin/limpiar-caja', methods=['POST'])
def limpiar_caja():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    pedidos_pagados = Pedido.query.filter_by(estado='Pagado').all()
    for p in pedidos_pagados:
        p.estado = 'Archivado'
    db.session.commit()
    flash('Caja reiniciada a S/ 0.00.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/mesa/agregar', methods=['POST'])
def agregar_mesa():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    numero = request.form.get('numero')
    password_personalizada = request.form.get('password')
    mesa_existente = Mesa.query.filter_by(numero=numero).first()
    if mesa_existente:
        flash(f'La mesa {numero} ya existe.', 'error')
        return redirect(url_for('admin_dashboard'))
    password_mesa = generate_password_hash(password_personalizada)
    nueva_mesa = Mesa(numero=numero, password_hash=password_mesa)
    db.session.add(nueva_mesa)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/mesa/cambiar-clave/<int:id>', methods=['POST'])
def cambiar_clave_mesa(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    mesa = Mesa.query.get(id)
    nueva_clave = request.form.get('nueva_clave')
    if mesa and nueva_clave:
        mesa.password_hash = generate_password_hash(nueva_clave)
        db.session.commit()
        flash(f'Clave de la Mesa {mesa.numero} actualizada.', 'success')
    return redirect(url_for('admin_dashboard'))

# ==========================================
# RUTAS ACTUALIZADAS PARA GUARDAR FOTOS SIN CARPETAS
# ==========================================
@app.route('/admin/plato/agregar', methods=['POST'])
def agregar_plato():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion') 
    precio = float(request.form.get('precio', 0))
    categoria = request.form.get('categoria')
    
    imagen_file = request.files.get('imagen')
    # Imagen por defecto si no suben nada
    imagen_data = 'https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=300&q=80' 
    
    # ¡LA MAGIA OCURRE AQUÍ! Convirtiendo la foto en código Base64
    if imagen_file and imagen_file.filename != '':
        encoded_string = base64.b64encode(imagen_file.read()).decode('utf-8')
        imagen_data = f"data:{imagen_file.content_type};base64,{encoded_string}"
    
    nuevo_plato = Plato(nombre=nombre, descripcion=descripcion, precio=precio, categoria=categoria, imagen=imagen_data)
    db.session.add(nuevo_plato)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/plato/toggle/<int:id>', methods=['POST'])
def toggle_plato(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    plato = Plato.query.get(id)
    if plato:
        plato.disponible = not plato.disponible
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/plato/eliminar/<int:id>', methods=['POST'])
def eliminar_plato(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    plato = Plato.query.get(id)
    if plato:
        db.session.delete(plato)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# ==========================================
# 5. INICIALIZACIÓN
# ==========================================
with app.app_context():
    instance_path = os.path.join(basedir, 'instance')
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)