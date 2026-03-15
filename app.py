from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import json
import os

app = Flask(__name__)
app.secret_key = 'selva_premium_key_2026'

ADMIN_PASS = "1234"
ARCHIVO_DATOS = 'datos.json'

# --- 1. BASE DE DATOS PERMANENTE ---
def cargar_datos():
    if os.path.exists(ARCHIVO_DATOS):
        with open(ARCHIVO_DATOS, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return {
            "mesas": {"1": "CLAVE1", "2": "CLAVE2"},
            "menu": [
                {"id": 1, "cat": "Comida", "nombre": "Tacacho con Cecina", "precio": 25, "img": "https://images.unsplash.com/photo-1604908176997-125f25cc6f3d?w=500"},
                {"id": 2, "cat": "Bebida", "nombre": "Cocona Helada", "precio": 8, "img": "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?w=500"}
            ],
            "pedidos_activos": [],
            "historial_ventas": []
        }

def guardar_datos(datos):
    with open(ARCHIVO_DATOS, 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4)

db = cargar_datos()

# --- 2. RUTAS DEL CLIENTE ---
@app.route('/')
def welcome():
    session.clear()
    return render_template('welcome.html')

@app.route('/login-mesa', methods=['GET', 'POST'])
def login_mesa():
    if request.method == 'POST':
        m, p = request.form.get('mesa'), request.form.get('password')
        if db['mesas'].get(m) == p:
            session['mesa_id'] = m
            return redirect(url_for('ver_menu'))
        flash("❌ Clave incorrecta")
    return render_template('login_mesa.html', mesas=db['mesas'])

@app.route('/carta')
def ver_menu():
    if 'mesa_id' not in session: return redirect(url_for('login_mesa'))
    return render_template('index.html', menu=db['menu'], mesa_n=session['mesa_id'])

@app.route('/enviar-pedido', methods=['POST'])
def enviar_pedido():
    if 'mesa_id' not in session: return redirect(url_for('login_mesa'))
    
    platos_pedidos = []
    total = 0
    
    for item in db['menu']:
        cantidad_str = request.form.get(f"cant_{item['id']}")
        if cantidad_str and cantidad_str.isdigit() and int(cantidad_str) > 0:
            cantidad = int(cantidad_str)
            subtotal = item['precio'] * cantidad
            platos_pedidos.append({"cantidad": cantidad, "nombre": item['nombre'], "subtotal": subtotal})
            total += subtotal
            
    if platos_pedidos:
        pedido = {
            "id": len(db['historial_ventas']) + 1, 
            "mesa": session['mesa_id'], 
            "hora": datetime.now().strftime("%H:%M"), 
            "platos": platos_pedidos, 
            "total": total
        }
        db['pedidos_activos'].append(pedido)
        db['historial_ventas'].append(pedido)
        guardar_datos(db)
        return render_template('gracias.html', total=total)
        
    return redirect(url_for('ver_menu'))

# --- 3. RUTAS DE ADMINISTRADOR ---
@app.route('/admin-login', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        if request.form.get('pass') == ADMIN_PASS:
            session['admin_ok'] = True
            return redirect(url_for('admin_panel'))
        flash("Clave de jefe incorrecta")
    return render_template('login_admin.html')

@app.route('/admin-panel')
def admin_panel():
    if not session.get('admin_ok'): return redirect(url_for('login_admin'))
    total_dia = sum(p['total'] for p in db['historial_ventas'])
    
    estado_mesas = []
    for num_mesa, clave in db['mesas'].items():
        pedidos_de_esta_mesa = [p for p in db['pedidos_activos'] if p['mesa'] == num_mesa]
        estado_mesas.append({
            "numero": num_mesa,
            "clave": clave,
            "pedidos": pedidos_de_esta_mesa
        })
        
    return render_template('admin.html', estado_mesas=estado_mesas, total_dia=total_dia, menu=db['menu'], mesas=db['mesas'])

@app.route('/completar/<int:id>')
def completar(id):
    db['pedidos_activos'] = [p for p in db['pedidos_activos'] if p['id'] != id]
    guardar_datos(db)
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_item', methods=['POST'])
def add_item():
    nuevo_id = max([i['id'] for i in db['menu']] + [0]) + 1
    db['menu'].append({
        "id": nuevo_id,
        "cat": request.form.get('cat'),
        "nombre": request.form.get('nombre'),
        "precio": int(request.form.get('precio')),
        "img": request.form.get('img') or "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500"
    })
    guardar_datos(db)
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_item/<int:id>')
def delete_item(id):
    db['menu'] = [i for i in db['menu'] if i['id'] != id]
    guardar_datos(db)
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_mesa', methods=['POST'])
def add_mesa():
    n = request.form.get('numero')
    c = request.form.get('clave')
    if n and c: 
        db['mesas'][n] = c
        guardar_datos(db)
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_mesa/<n>')
def delete_mesa(n):
    if n in db['mesas']: 
        del db['mesas'][n]
        guardar_datos(db)
    return redirect(url_for('admin_panel'))

@app.route('/admin/reset_ventas')
def reset_ventas():
    if not session.get('admin_ok'): return redirect(url_for('login_admin'))
    db['historial_ventas'] = []
    guardar_datos(db)
    return redirect(url_for('admin_panel'))

@app.route('/admin/logout')
def logout():
    session.clear()
    return redirect(url_for('welcome'))

if __name__ == '__main__':
    app.run(debug=True)