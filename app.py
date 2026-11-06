from flask import Flask, Response, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import base64
import csv
import io
import json
import mimetypes
import os
import uuid

from extensions import db, obtener_hora_peru
from models import Mesa, Plato, Pedido, DetallePedido
import ruleta
from ruleta import sincronizar_giros, desvincular_pedido, estado_ruleta

# ==========================================
# 1. CONFIGURACIÓN INICIAL
# ==========================================
app = Flask(__name__)
app.secret_key = 'super_secreta_selva_2026' 

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')

db.init_app(app)

# ==========================================
# 2. MÓDULOS
# ==========================================
# Los modelos de mesas, carta y pedidos están en models.py.
# La Ruleta de la Suerte (modelos, lógica y rutas) está en ruleta.py.
app.register_blueprint(ruleta.bp)

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
        
    # AQUÍ BUSCAMOS LAS 4 CATEGORÍAS EN LA BASE DE DATOS
    platos_comida = Plato.query.filter_by(categoria='Comida', disponible=True).all()
    platos_bebida = Plato.query.filter_by(categoria='Bebida', disponible=True).all()
    platos_golosinas = Plato.query.filter_by(categoria='Golosinas', disponible=True).all()
    platos_piscina = Plato.query.filter_by(categoria='Piscina', disponible=True).all()
        
    return render_template('index.html', 
                           mesa_numero=session.get('mesa_numero'), 
                           comidas=platos_comida, 
                           bebidas=platos_bebida,
                           golosinas=platos_golosinas,
                           piscina=platos_piscina,
                           mesas=Mesa.query.order_by(Mesa.numero).all(),
                           pedido_actual=Pedido.query.filter_by(mesa_id=session['mesa_id'], estado='Pendiente').first(),
                           ruleta=estado_ruleta(session['mesa_id']))

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
        flash('Debes seleccionar al menos un producto.', 'error')
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
    db.session.flush()

    # Ruleta de la Suerte: cada plato de comida del pedido da un ticket (un giro)
    session['giros_nuevos'] = sincronizar_giros(pedido_actual)
    db.session.commit()
    return redirect(url_for('gracias'))

@app.route('/gracias')
def gracias():
    if 'mesa_id' not in session:
        return redirect(url_for('login_mesa'))
    return render_template('gracias.html', mesa_numero=session.get('mesa_numero'),
                           giros_nuevos=session.pop('giros_nuevos', 0),
                           ruleta=estado_ruleta(session['mesa_id']))

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
        # El botón Cobrar de la carta llega con ?mesa=N: se conserva para dejar esa cuenta lista
        mesa = request.args.get('mesa', type=int)
        if password == 'admin':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard', mesa=mesa))
        else:
            flash('Contraseña incorrecta.', 'error')
            return redirect(url_for('admin_login', mesa=mesa))
    return render_template('login_admin.html', mesa=request.args.get('mesa', type=int))

@app.route('/admin')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login', mesa=request.args.get('mesa', type=int)))

    todas_mesas = Mesa.query.order_by(Mesa.numero).all()
    todos_platos = Plato.query.all()
    pedidos_pagados = Pedido.query.filter_by(estado='Pagado').all()
    ganancias_hoy = sum(pedido.total for pedido in pedidos_pagados)
    
    return render_template('admin.html', mesas=todas_mesas, platos=todos_platos, ganancias=ganancias_hoy, pedidos_pagados=pedidos_pagados)

@app.route('/admin/exportar-csv')
def exportar_csv():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    # El apóstrofo evita que Excel ejecute como fórmula un nombre de producto
    def celda(valor):
        texto = str(valor)
        return "'" + texto if texto[:1] in ('=', '+', '-', '@') else texto

    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(['Ticket', 'Fecha', 'Mesa', 'Detalle', 'Metodo de pago', 'Total', 'Recibido', 'Vuelto'])
    for pedido in Pedido.query.filter_by(estado='Pagado').order_by(Pedido.fecha_hora).all():
        detalle = ' | '.join(f"{d.cantidad} x {d.plato.nombre if d.plato else 'Producto eliminado'}" for d in pedido.detalles)
        escritor.writerow([f'{pedido.id:06d}', pedido.fecha_hora.strftime('%d/%m/%Y %H:%M'), pedido.mesa_asignada.numero, celda(detalle),
                           pedido.metodo_pago, f'{pedido.total:.2f}', f'{pedido.monto_recibido:.2f}', f'{pedido.vuelto:.2f}'])

    nombre = f"ventas-selva-del-prado-{obtener_hora_peru().strftime('%Y-%m-%d')}.csv"
    return Response('﻿' + salida.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={nombre}'})

@app.route('/admin/copia-seguridad')
def copia_seguridad():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    def imagen_base64(imagen):
        ruta = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(imagen or ''))
        if not imagen or imagen.startswith('http') or not os.path.isfile(ruta):
            return None
        tipo = mimetypes.guess_type(ruta)[0] or 'application/octet-stream'
        with open(ruta, 'rb') as archivo:
            return f'data:{tipo};base64,' + base64.b64encode(archivo.read()).decode('ascii')

    catalogo = [{'id': p.id, 'nombre': p.nombre, 'descripcion': p.descripcion, 'precio': p.precio, 'categoria': p.categoria,
                 'disponible': p.disponible, 'imagen': p.imagen, 'imagen_base64': imagen_base64(p.imagen)} for p in Plato.query.all()]
    fecha = obtener_hora_peru()
    copia = {'exportado': fecha.isoformat(timespec='seconds'), 'platos': catalogo}
    return Response(json.dumps(copia, ensure_ascii=False, indent=2), mimetype='application/json',
                    headers={'Content-Disposition': f"attachment; filename=menu-selva-del-prado-{fecha.strftime('%Y-%m-%d')}.json"})

@app.route('/admin/pedido/editar-detalle/<int:detalle_id>', methods=['POST'])
def editar_detalle(detalle_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    accion = request.form.get('accion')
    detalle = DetallePedido.query.get(detalle_id)
    
    if detalle:
        pedido = Pedido.query.get(detalle.pedido_id)
        if accion == 'restar' and detalle.cantidad > 1:
            detalle.cantidad -= 1
        elif accion == 'sumar':
            detalle.cantidad += 1
        elif accion == 'eliminar' or (accion == 'restar' and detalle.cantidad == 1):
            db.session.delete(detalle)
            db.session.commit()
            
        db.session.commit()
        detalles_restantes = DetallePedido.query.filter_by(pedido_id=pedido.id).all()
        if len(detalles_restantes) == 0:
            desvincular_pedido(pedido)
            db.session.delete(pedido)
        else:
            nuevo_total = sum(d.cantidad * d.precio_unitario for d in detalles_restantes)
            pedido.total = nuevo_total
            sincronizar_giros(pedido)  # si se quitaron productos, se retiran giros sin usar
            
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

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

@app.route('/admin/plato/agregar', methods=['POST'])
def agregar_plato():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion') 
    precio = float(request.form.get('precio', 0))
    categoria = request.form.get('categoria')
    
    imagen_file = request.files.get('imagen')
    nombre_imagen = 'https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=300&q=80' 
    
    if imagen_file and imagen_file.filename != '':
        filename = secure_filename(imagen_file.filename)
        unique_filename = str(uuid.uuid4().hex)[:8] + "_" + filename
        imagen_file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        nombre_imagen = unique_filename
    
    nuevo_plato = Plato(nombre=nombre, descripcion=descripcion, precio=precio, categoria=categoria, imagen=nombre_imagen)
    db.session.add(nuevo_plato)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/plato/editar/<int:id>', methods=['POST'])
def editar_plato(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    destino = url_for('ver_carta') if request.form.get('volver') == 'carta' and 'mesa_id' in session else url_for('admin_dashboard')
    plato = Plato.query.get(id)
    if not plato:
        return redirect(destino)

    # Solo cambia lo que llega: la carta envía únicamente la foto
    for campo in ('nombre', 'descripcion', 'categoria'):
        if campo in request.form:
            setattr(plato, campo, request.form[campo].strip())
    if 'precio' in request.form:
        try:
            plato.precio = float(request.form['precio'])
        except ValueError:
            flash('Error: El precio debe ser un número válido.', 'error')
            return redirect(destino)

    imagen_file = request.files.get('imagen')
    if imagen_file and imagen_file.filename != '':
        filename = secure_filename(imagen_file.filename)
        if os.path.splitext(filename)[1].lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            flash('La foto debe ser JPG, PNG o WEBP.', 'error')
            return redirect(destino)
        unique_filename = str(uuid.uuid4().hex)[:8] + "_" + filename
        imagen_file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        plato.imagen = unique_filename

    db.session.commit()
    flash(f'{plato.nombre} actualizado.', 'success')
    return redirect(destino)

@app.route('/admin/plato/editar-precio/<int:id>', methods=['POST'])
def editar_precio_plato(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    plato = Plato.query.get(id)
    nuevo_precio = request.form.get('nuevo_precio')
    if plato and nuevo_precio:
        try:
            plato.precio = float(nuevo_precio)
            db.session.commit()
            flash(f'Precio de {plato.nombre} actualizado a S/ {plato.precio:.2f}', 'success')
        except ValueError:
            flash('Error: El precio debe ser un número válido.', 'error')
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
    
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    ruleta.sembrar_premios_iniciales()  # solo la primera vez: premios de ejemplo editables
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)